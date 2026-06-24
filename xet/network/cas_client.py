"""CAS (Content Addressable Storage) API 客户端。

与 HuggingFace CAS 服务交互，执行：
1. Reconstruction Query - 获取文件重建信息
2. Xorb Data Download - 下载 xorb 数据块
"""
import logging
import uuid
import threading
from typing import Dict, Optional, Tuple

import requests

from xet.protocol.types import (
    QueryReconstructionResponse,
    HttpRange,
    XetFileInfo,
    CASReconstructionFetchInfo,
)
from xet.network.retry import with_retry
from xet.network.auth import XetAuth
from xet.network.low_speed_timeout import LowSpeedTimeoutError
from xet.network.url_refresh_coordinator import URLRefreshCoordinator
from xet.network.adaptive_concurrency import AdaptiveConcurrencyController
import time
import random

logger = logging.getLogger(__name__)


class CASClient:
    """CAS REST API 客户端。

    封装与 CAS 服务的所有 HTTP 通信，包括：
    - 获取文件 reconstruction 信息
    - 下载 xorb 数据
    - Token 过期自动刷新

    Attributes:
        endpoint: CAS 服务基础 URL（如 https://cas-server.xethub.hf.co）
        access_token: CAS JWT token
        session: requests.Session 实例（复用连接池）
        session_id: 会话 ID（用于跟踪）
    """

    # Reconstruction URL 默认新鲜度阈值（30 秒主动刷新）
    _recon_refresh_interval = 30

    def __init__(
        self,
        endpoint: str,
        access_token: str,
        session: Optional[requests.Session] = None,
        auth: Optional[XetAuth] = None,
        repo_id: str = "",
        auth_url: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
        url_coordinator: Optional[URLRefreshCoordinator] = None,
        acc: Optional[AdaptiveConcurrencyController] = None,
        retry_max: int = 5,
        retry_coordinator: Optional['RetryCoordinator'] = None,
    ):
        """初始化 CAS 客户端。

        Args:
            endpoint: CAS 基础 URL
            access_token: 已认证的 JWT token
            session: 配置好的 requests.Session
            auth: XetAuth 实例（用于 token 过期自动刷新）
            repo_id: 仓库 ID（用于 token 刷新）
            auth_url: auth URL（用于 token 刷新）
            stop_event: 中断信号（用于 Ctrl+C）
            url_coordinator: URL 刷新协调器（可选）
            acc: 自适应并发控制器（可选）
            retry_max: 最大重试次数
            retry_coordinator: 全局重试协调器（可选）
        """
        self.endpoint = endpoint.rstrip('/')
        self.access_token = access_token
        self.session = session or requests.Session()
        self._auth = auth
        self._repo_id = repo_id
        self._auth_url = auth_url
        self._stop_event = stop_event
        self._url_coordinator = url_coordinator
        self._acc = acc
        self._retry_coordinator = retry_coordinator
        self.retry_max = retry_max
        self.timeout = 30  # 默认 30 秒超时
        # Session ID 用于 CloudFront 会话跟踪
        self.session_id = uuid.uuid4().hex[:16]
        # V2 API 版本探测缓存
        self._v2_available: Optional[bool] = None
        # Reconstruction 新鲜度跟踪（用于预检 URL 过期）
        self._last_recon_time: float = 0.0
        self._last_recon_file: str = ""
        # Reconstruction 响应缓存 {file_hash: (response, timestamp)}
        self._recon_cache: Dict[str, Tuple[QueryReconstructionResponse, float]] = {}
        self._recon_cache_lock = threading.Lock()
        # 共享刷新结果：最近一次 403 恢复中获取的 reconstruction（跨线程共享）
        self._shared_refresh_recon: Optional[Tuple[str, QueryReconstructionResponse, float]] = None
        self._shared_refresh_lock = threading.Lock()

    def _set_recon_cache(self, file_hash: str, recon: QueryReconstructionResponse):
        """缓存 reconstruction 响应供 403/401 恢复时复用。"""
        with self._recon_cache_lock:
            self._recon_cache[file_hash] = (recon, time.time())
            # 只保留最近一个文件（避免内存泄漏）
            for k in list(self._recon_cache.keys()):
                if k != file_hash:
                    del self._recon_cache[k]

    def _get_headers(self) -> dict:
        """获取标准请求头（含认证）。

        Returns:
            包含 Authorization 的请求头字典
        """
        return {"Authorization": f"Bearer {self.access_token}"}

    def _refresh_token(self):
        """刷新 CAS token（401 时调用）。

        Raises:
            RuntimeError: 如果没有配置 auth 或刷新失败
        """
        if not self._auth:
            raise RuntimeError("[CAS] 401 但无 XetAuth 配置，无法刷新 token")

        logger.info("[CAS] Token 过期，重新获取...")
        self._auth.clear_cache()
        new_info = self._auth.get_token(self._repo_id, auth_url=self._auth_url)
        self.access_token = new_info.access_token
        logger.info(f"[CAS] Token 刷新成功，新有效期至 {new_info.expiration}")

    @with_retry(max_attempts=3, backoff_base=2.0, retry_on=(requests.RequestException,))
    def get_reconstruction(
        self,
        file_hash: str,
    ) -> QueryReconstructionResponse:
        """获取文件的 reconstruction 信息。

        调用 CAS API 获取描述如何重建文件所需的 terms 和 xorb 位置信息。
        自动处理 V2/V1 API 版本，401 时自动刷新 token。

        Args:
            file_hash: 文件的 MerkleHash（64字符hex字符串，来自 X-Xet-Hash header）

        Returns:
            QueryReconstructionResponse 包含 terms 和 fetch_info

        Raises:
            requests.HTTPError: API 返回错误状态码
            ValueError: 响应格式无效
        """
        # 检查内存缓存
        with self._recon_cache_lock:
            if file_hash in self._recon_cache:
                cached_recon, cached_ts = self._recon_cache[file_hash]
                if time.time() - cached_ts < self._recon_refresh_interval:
                    logger.debug(f"[CAS] Reconstruction 缓存命中: {file_hash[:16]}...")
                    return cached_recon

        headers = self._get_headers()

        # 尝试 V2 API（如果尚未确认不可用）
        if self._v2_available is not False:
            try:
                url_v2 = f"{self.endpoint}/v2/reconstructions/{file_hash}"
                logger.debug(f"[CAS] 尝试 V2 API: {url_v2[:80]}...")
                resp = self.session.get(
                    url_v2, headers=headers, timeout=self.timeout
                )

                if resp.status_code == 200:
                    self._v2_available = True
                    recon = QueryReconstructionResponse.from_dict(resp.json())
                    self._set_recon_cache(file_hash, recon)
                    return recon
                elif resp.status_code == 401:
                    # 401: Token 过期，刷新后重试
                    self._refresh_token()
                    headers = self._get_headers()
                    resp = self.session.get(
                        url_v2, headers=headers, timeout=self.timeout
                    )
                    resp.raise_for_status()
                    self._v2_available = True
                    recon = QueryReconstructionResponse.from_dict(resp.json())
                    self._set_recon_cache(file_hash, recon)
                    return recon
                elif resp.status_code in (404, 501):
                    # V2 不可用，fallback V1
                    self._v2_available = False
                    logger.debug("[CAS] V2 不可用，fallback V1")
                else:
                    resp.raise_for_status()

            except requests.HTTPError as e:
                if e.response and e.response.status_code == 401:
                    raise  # 401 已经处理过，继续抛出
                # 其他错误，尝试 V1
                self._v2_available = False
                logger.debug(f"[CAS] V2 失败: {e}, fallback V1")

        # 使用 V1 API
        url_v1 = f"{self.endpoint}/v1/reconstructions/{file_hash}"
        logger.debug(f"[CAS] 使用 V1 API: {url_v1[:80]}...")

        resp = self.session.get(url_v1, headers=headers, timeout=self.timeout)

        if resp.status_code == 401:
            # 401: Token 过期，刷新后重试
            self._refresh_token()
            headers = self._get_headers()
            resp = self.session.get(
                url_v1, headers=headers, timeout=self.timeout
            )

        resp.raise_for_status()
        recon = QueryReconstructionResponse.from_dict(resp.json())
        self._set_recon_cache(file_hash, recon)
        return recon

    @with_retry(max_attempts=3, backoff_base=2.0, retry_on=(requests.RequestException,))
    def get_segment_reconstruction(
        self,
        file_hash: str,
        start: int,
        end: int,
    ) -> QueryReconstructionResponse:
        """获取文件指定分段的 reconstruction 信息。

        调用 CAS API 获取文件某个字节范围的 reconstruction 信息，用于分段下载。
        这样可以避免一次性加载整个文件的 reconstruction，降低内存占用。

        Args:
            file_hash: 文件的 MerkleHash
            start: 起始字节位置（包含）
            end: 结束字节位置（不包含）

        Returns:
            QueryReconstructionResponse 包含该分段的 terms 和 fetch_info

        Raises:
            requests.HTTPError: API 返回错误状态码
            ValueError: 响应格式无效或参数无效
        """
        if start < 0 or end <= start:
            raise ValueError(f"无效的分段范围: start={start}, end={end}")

        headers = self._get_headers()

        # 尝试 V2 API（如果支持分段查询）
        if self._v2_available is not False:
            try:
                # V2 API 可能支持 ?start=X&end=Y 查询参数
                url_v2 = f"{self.endpoint}/v2/reconstructions/{file_hash}"
                params = {"start": start, "end": end}
                logger.debug(
                    f"[CAS] 尝试 V2 Segment API: {url_v2[:80]}... "
                    f"range=[{start}, {end})"
                )
                resp = self.session.get(
                    url_v2, headers=headers, params=params, timeout=self.timeout
                )

                if resp.status_code == 200:
                    self._v2_available = True
                    return QueryReconstructionResponse.from_dict(resp.json())
                elif resp.status_code == 401:
                    # Token 过期，刷新后重试
                    self._refresh_token()
                    headers = self._get_headers()
                    resp = self.session.get(
                        url_v2, headers=headers, params=params, timeout=self.timeout
                    )
                    resp.raise_for_status()
                    self._v2_available = True
                    return QueryReconstructionResponse.from_dict(resp.json())
                elif resp.status_code in (404, 501):
                    # V2 不支持分段，fallback V1
                    self._v2_available = False
                    logger.debug("[CAS] V2 不支持分段查询，fallback V1")
                else:
                    resp.raise_for_status()

            except requests.HTTPError as e:
                if e.response and e.response.status_code == 401:
                    raise
                # 其他错误，尝试 V1
                self._v2_available = False
                logger.debug(f"[CAS] V2 Segment 失败: {e}, fallback V1")

        # 使用 V1 API（可能不支持分段查询）
        # 如果 V1 不支持，则先获取完整 reconstruction，然后在客户端过滤
        url_v1 = f"{self.endpoint}/v1/reconstructions/{file_hash}"
        logger.debug(
            f"[CAS] 使用 V1 API（可能需要客户端过滤）: {url_v1[:80]}..."
        )

        resp = self.session.get(url_v1, headers=headers, timeout=self.timeout)

        if resp.status_code == 401:
            self._refresh_token()
            headers = self._get_headers()
            resp = self.session.get(
                url_v1, headers=headers, timeout=self.timeout
            )

        resp.raise_for_status()
        full_recon = QueryReconstructionResponse.from_dict(resp.json())

        # 客户端过滤：只保留 [start, end) 范围内的 terms
        return self._filter_reconstruction_by_range(full_recon, start, end)

    def _filter_reconstruction_by_range(
        self,
        recon: QueryReconstructionResponse,
        start: int,
        end: int,
    ) -> QueryReconstructionResponse:
        """客户端过滤 reconstruction，只保留指定范围的 terms。

        Args:
            recon: 完整的 reconstruction
            start: 起始字节位置
            end: 结束字节位置

        Returns:
            过滤后的 reconstruction
        """
        filtered_terms = []
        current_offset = 0

        for term in recon.terms:
            term_start = current_offset
            term_end = current_offset + term.unpacked_length

            # 判断 term 是否与 [start, end) 有交集
            if term_end > start and term_start < end:
                # 有交集，添加该 term
                filtered_terms.append(term)

            current_offset = term_end

            # 如果已经超过 end，可以提前退出
            if current_offset >= end:
                break

        # 重新计算 offset_into_first_range
        # 如果 start 落在第一个 term 内部，需要调整 offset
        new_offset = 0
        if filtered_terms:
            first_term_start = sum(t.unpacked_length for t in recon.terms[:recon.terms.index(filtered_terms[0])])
            if start > first_term_start:
                new_offset = start - first_term_start

        # 只保留需要的 fetch_info（去重）
        needed_xorb_hashes = {term.hash for term in filtered_terms}
        filtered_fetch_info = [
            fi for fi in recon.fetch_info if fi.hash in needed_xorb_hashes
        ]

        logger.debug(
            f"[CAS] 客户端过滤: {len(recon.terms)} terms → {len(filtered_terms)} terms, "
            f"{len(recon.fetch_info)} xorbs → {len(filtered_fetch_info)} xorbs"
        )

        return QueryReconstructionResponse(
            terms=filtered_terms,
            fetch_info=filtered_fetch_info,
            offset_into_first_range=new_offset,
        )

    def get_xorb_data(self, url: str, url_range: HttpRange) -> bytes:
        """下载 xorb 数据。

        使用 HTTP Range 请求从 CDN 下载 xorb 的指定字节范围。

        Args:
            url: presigned 下载 URL（来自 fetch_info）
            url_range: 需要下载的字节范围

        Returns:
            原始 xorb 字节数据（尚未解压）

        Raises:
            requests.HTTPError: 下载失败
            ValueError: URL 或范围参数无效
        """
        if not url:
            raise ValueError("URL 不能为空")

        # 关键: 不发送 Authorization（避免 CloudFront 403）
        # 参考 Rust xet-core: xorb 下载使用未认证的 http_client
        headers = {
            "Range": url_range.to_header(),
            "X-Xet-Session-Id": self.session_id,
            "Authorization": None,  # 抑制 session 级别的默认头
        }

        logger.debug(
            f"[CAS] 下载 xorb: {url[:60]}... "
            f"range={url_range.start}-{url_range.end} ({url_range.length()} bytes)"
        )

        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()

        return resp.content

    def get_xorb_data_streaming(
        self,
        url: str,
        url_range: HttpRange,
        min_speed: int = 50 * 1024,  # 50 KB/s
        check_interval: float = 10.0,  # 每 10s 检查一次
        low_speed_grace: float = 30.0,  # 连续低速 30s 触发重试
    ) -> bytes:
        """下载 xorb 数据（带低速检测）。

        使用流式下载，每隔 check_interval 检查速度。
        如果连续 low_speed_grace 秒低于 min_speed，抛出 LowSpeedTimeoutError。

        Args:
            url: presigned 下载 URL
            url_range: 字节范围
            min_speed: 最低允许速度（字节/秒）
            check_interval: 检查间隔（秒）
            low_speed_grace: 低速容忍时间（秒）

        Returns:
            原始 xorb 字节数据

        Raises:
            LowSpeedTimeoutError: 持续低速超时（携带已接收字节数）
            requests.HTTPError: 下载失败
        """
        if not url:
            raise ValueError("URL 不能为空")

        headers = {
            "Range": url_range.to_header(),
            "X-Xet-Session-Id": self.session_id,
            "Authorization": None,
        }

        logger.debug(
            f"[CAS] 流式下载 xorb: {url[:60]}... "
            f"range={url_range.start}-{url_range.end} ({url_range.length()} bytes)"
        )

        resp = self.session.get(
            url, headers=headers, timeout=self.timeout, stream=True
        )
        resp.raise_for_status()

        # 低速检测状态
        chunk_size = 64 * 1024  # 64 KB per chunk
        total_received = 0
        buffer = bytearray()

        last_check_time = time.time()
        last_check_received = 0
        low_speed_streak = 0

        for chunk in resp.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue

            buffer.extend(chunk)
            total_received += len(chunk)

            # 检查速度
            now = time.time()
            elapsed = now - last_check_time

            if elapsed >= check_interval:
                interval_received = total_received - last_check_received
                interval_speed = interval_received / elapsed

                if interval_speed < min_speed:
                    low_speed_streak += 1
                    low_speed_duration = low_speed_streak * check_interval

                    logger.warning(
                        f"[CAS] 低速检测: {interval_speed / 1024:.1f} KB/s "
                        f"(< {min_speed / 1024:.1f} KB/s), "
                        f"累计 {low_speed_duration:.1f}s"
                    )

                    if low_speed_duration >= low_speed_grace:
                        raise LowSpeedTimeoutError(
                            f"持续低速 {low_speed_duration:.1f}s "
                            f"(< {min_speed / 1024:.1f} KB/s)",
                            received=total_received,
                        )
                else:
                    # 速度恢复，重置计数
                    low_speed_streak = 0

                # 更新检查点
                last_check_time = now
                last_check_received = total_received

        return buffer  # bytearray，避免 bytes() 的额外复制

    def get_xorb_data_with_retry(
        self,
        url: str,
        url_range: HttpRange,
        xorb_hash: str,
        file_hash: str,
        use_streaming: bool = False,
    ) -> bytes:
        """带 URL/Token 自动刷新的 xorb 下载（高级重试逻辑）。

        集成所有高级特性：
        - RetryCoordinator 全局重试协调
        - URLRefreshCoordinator 协调 403 刷新
        - AdaptiveConcurrencyController 许可管理
        - 401 自动刷新 token + 重新获取 reconstruction
        - 403 协调刷新 + 获取新 URL
        - 断点续传（LowSpeedTimeoutError）
        - 专用退避策略

        Args:
            url: 初始 presigned URL
            url_range: 初始字节范围
            xorb_hash: xorb 的 MerkleHash（用于在新 reconstruction 中查找）
            file_hash: 文件的 MerkleHash（用于重新获取 reconstruction）
            use_streaming: 是否使用流式下载（带低速检测）

        Returns:
            原始 xorb 字节数据

        Raises:
            RuntimeError: 重试耗尽或协调器 exhausted
            requests.HTTPError: HTTP 错误
        """
        # 注册到 RetryCoordinator（如果存在）
        if self._retry_coordinator:
            self._retry_coordinator.register_active(xorb_hash)

        acc_acquired = False
        current_url = url
        current_range = url_range
        is_retrying = False  # 标记当前是否在重试状态

        try:
            for attempt in range(self.retry_max):
                self._check_interrupt()

                # 优先使用共享刷新结果中的新 URL（防止同一 file_hash 反复 403）
                with self._shared_refresh_lock:
                    if self._shared_refresh_recon is not None:
                        s_file_hash, s_recon, s_ts = self._shared_refresh_recon
                        if s_file_hash == file_hash and time.time() - s_ts < 120:
                            if attempt == 0:
                                logger.debug(
                                    f"[CAS] xorb={xorb_hash[:16]}... 使用共享 reconstruction"
                                )
                            try:
                                current_url, current_range = self._find_xorb_in_recon(
                                    xorb_hash, s_recon, url_range
                                )
                            except Exception:
                                # 共享结果中找不到此 xorb，使用原始 URL
                                pass

                # 检查是否应该停止重试（全局协调）
                if self._retry_coordinator and self._retry_coordinator.should_stop_retrying():
                    status = self._retry_coordinator.get_status()
                    retry_elapsed = status.get('all_retry_elapsed') or 0
                    logger.error(
                        f"[CAS] RetryCoordinator 触发全局停止，"
                        f"xorb={xorb_hash[:16]}..., "
                        f"active={status['active']}, retrying={status['retrying']}, "
                        f"all_retry_elapsed={retry_elapsed:.0f}s"
                    )
                    raise RuntimeError(
                        f"全局重试协调器触发停止: "
                        f"{status['retrying']}/{status['active']} 个 xorb 全部重试 "
                        f"持续 {retry_elapsed:.0f}s "
                        f"(宽限 {self._retry_coordinator._all_retry_grace:.0f}s)"
                    )

                # 1. 获取 ACC 许可
                if self._acc:
                    acc_acquired = self._acc.acquire(timeout=300.0)
                    if not acc_acquired:
                        logger.error("[CAS] ACC acquire 超时，放弃")
                        raise RuntimeError("AdaptiveConcurrencyController acquire 超时")

                try:
                    # 2. 主动检查 token 过期
                    self._ensure_token()

                    # 2.5. 预检 URL 新鲜度：reconstruction 中的 presigned URL 有时效性
                    #    如果距离上次获取 recon 已超过阈值（或换了文件），主动刷新
                    _need_fresh_recon = (
                        file_hash != self._last_recon_file
                        or time.time() - self._last_recon_time > CASClient._recon_refresh_interval
                    )
                    if _need_fresh_recon and attempt == 0:
                        try:
                            _fresh_recon = self.get_reconstruction(file_hash)
                            _fresh_url, _fresh_range = self._find_xorb_in_recon(
                                xorb_hash, _fresh_recon, url_range
                            )
                            current_url = _fresh_url
                            current_range = _fresh_range
                            self._last_recon_time = time.time()
                            self._last_recon_file = file_hash
                            logger.debug(f"[CAS] 预检刷新 URL: {xorb_hash[:16]}...")
                        except Exception:
                            pass  # 预检失败不阻塞，后续 403 时再刷新

                    # 3. 下载 xorb 数据
                    if use_streaming:
                        data = self.get_xorb_data_streaming(current_url, current_range)
                    else:
                        data = self.get_xorb_data(current_url, current_range)

                    # 4. 成功：释放 ACC 并报告
                    if acc_acquired and self._acc:
                        self._acc.release()
                        self._acc.report_success(bytes_transferred=len(data))

                    # 5. 成功：注销重试状态
                    if is_retrying and self._retry_coordinator:
                        self._retry_coordinator.unregister_retry(xorb_hash)

                    return data

                except requests.HTTPError as e:
                    # 标记进入重试状态
                    if not is_retrying and self._retry_coordinator:
                        self._retry_coordinator.register_retry(xorb_hash)
                        is_retrying = True

                    # 释放 ACC 并报告失败
                    if acc_acquired and self._acc:
                        self._acc.release()
                        self._acc.report_failure(status_code=e.response.status_code)

                    status_code = e.response.status_code

                    # 401: Token 过期 → 强制刷新 + 重新获取 reconstruction
                    if status_code == 401:
                        logger.warning(
                            f"[CAS] 401 Token 过期 (尝试 {attempt + 1}/{self.retry_max})"
                        )
                        try:
                            self._force_refresh_token()
                            # token 已变，清除缓存强制获取新 presigned URL
                            with self._recon_cache_lock:
                                self._recon_cache.pop(file_hash, None)
                            recon = self.get_reconstruction(file_hash)
                            current_url, current_range = self._find_xorb_in_recon(
                                xorb_hash, recon, url_range
                            )
                            logger.info(
                                f"[CAS] 401 恢复: 获取新 URL {current_url[:60]}..."
                            )
                            continue
                        except Exception as refresh_err:
                            logger.error(f"[CAS] 401 恢复失败: {refresh_err}")
                            if attempt == self.retry_max - 1:
                                raise

                    # 403: URL 过期 → 通过 URLRefreshCoordinator 协调刷新
                    elif status_code == 403:
                        logger.warning(
                            f"[CAS] 403 URL 过期 (尝试 {attempt + 1}/{self.retry_max})"
                        )

                        # 检查协调器是否 exhausted
                        if self._url_coordinator and self._url_coordinator.is_exhausted:
                            logger.error("[CAS] URLRefreshCoordinator exhausted，放弃")
                            raise RuntimeError("URL 刷新失败次数过多")

                        # 尝试获取刷新权限
                        if self._url_coordinator and self._url_coordinator.acquire_refresh():
                            # 我获得了刷新权限
                            logger.info("[CAS] 获得 URL 刷新权限")
                            try:
                                self._force_refresh_token()  # 先刷新 token
                                # 403 后缓存中的旧 URL 已失效，强制走 API
                                with self._recon_cache_lock:
                                    self._recon_cache.pop(file_hash, None)
                                recon = self.get_reconstruction(file_hash)
                                # 共享给其他等待中的线程
                                with self._shared_refresh_lock:
                                    self._shared_refresh_recon = (
                                        file_hash, recon, time.time()
                                    )
                                current_url, current_range = self._find_xorb_in_recon(
                                    xorb_hash, recon, url_range
                                )
                                self._last_recon_time = time.time()  # 更新新鲜度
                                self._url_coordinator.release_refresh(success=True)
                                logger.info(
                                    f"[CAS] 403 恢复: 获取新 URL {current_url[:60]}..."
                                )
                            except Exception as refresh_err:
                                self._url_coordinator.release_refresh(success=False)
                                logger.error(f"[CAS] 403 恢复失败: {refresh_err}")
                                if attempt == self.retry_max - 1:
                                    raise
                        else:
                            # 其他线程在刷新或冷却期，尝试使用共享结果
                            logger.info("[CAS] 403: 等待刷新结果...")

                        # 403 专用退避（比普通错误更长）
                        base_403 = 5.0
                        delay = base_403 * (2.5 ** attempt) * random.uniform(0.7, 1.3)
                        logger.debug(f"[CAS] 403 退避: {delay:.2f}s")
                        self._interruptible_sleep(delay)

                        # 退避后检查是否有其他线程刷新的共享结果
                        with self._shared_refresh_lock:
                            if self._shared_refresh_recon is not None:
                                s_file_hash, s_recon, s_ts = self._shared_refresh_recon
                                if s_file_hash == file_hash and time.time() - s_ts < 60:
                                    try:
                                        current_url, current_range = self._find_xorb_in_recon(
                                            xorb_hash, s_recon, url_range
                                        )
                                        logger.info(
                                            f"[CAS] 403 恢复: 复用共享 reconstruction "
                                            f"(file={s_file_hash[:16]}..., age={time.time()-s_ts:.0f}s)"
                                        )
                                        continue  # 直接重试新 URL
                                    except Exception:
                                        # 共享结果中找不到此 xorb，继续正常循环
                                        pass

                        continue

                    else:
                        # 其他 HTTP 错误：标准退避
                        if attempt == self.retry_max - 1:
                            raise
                        delay = 1.5 ** attempt * random.uniform(0.8, 1.2)
                        logger.warning(
                            f"[CAS] HTTP {status_code} 错误，{delay:.2f}s 后重试..."
                        )
                        self._interruptible_sleep(delay)

                except LowSpeedTimeoutError as e:
                    # 标记进入重试状态
                    if not is_retrying and self._retry_coordinator:
                        self._retry_coordinator.register_retry(xorb_hash)
                        is_retrying = True

                    # 断点续传
                    logger.warning(
                        f"[CAS] 低速超时 (已接收 {e.received} 字节)，断点续传..."
                    )
                    if acc_acquired and self._acc:
                        self._acc.release()

                    # 调整 Range 从已接收位置继续
                    new_start = current_range.start + e.received
                    current_range = HttpRange(start=new_start, end=current_range.end)
                    logger.info(
                        f"[CAS] 断点续传: 从 {new_start} 继续 "
                        f"(剩余 {current_range.length()} 字节)"
                    )

                    # 低速超时不算入重试次数（只调整范围）
                    continue

                except Exception as e:
                    # 标记进入重试状态
                    if not is_retrying and self._retry_coordinator:
                        self._retry_coordinator.register_retry(xorb_hash)
                        is_retrying = True

                    # 其他异常
                    if acc_acquired and self._acc:
                        self._acc.release()
                        self._acc.report_failure()

                    if attempt == self.retry_max - 1:
                        raise

                    delay = 1.5 ** attempt
                    logger.warning(f"[CAS] 下载失败: {e}, {delay:.2f}s 后重试...")
                    self._interruptible_sleep(delay)

            raise RuntimeError(
                f"[CAS] 下载失败，已重试 {self.retry_max} 次: {xorb_hash[:16]}..."
            )

        finally:
            # 无论成功或失败，都要注销活跃状态
            if self._retry_coordinator:
                self._retry_coordinator.unregister_active(xorb_hash)

    @staticmethod
    def get_xet_file_info(
        url: str,
        session: requests.Session,
        timeout: int = 30,
    ) -> XetFileInfo:
        """从 HuggingFace URL 获取 Xet 文件信息。

        通过 HEAD 请求（不跟随重定向）检测文件是否为 Xet 格式，
        并提取 X-Xet-Hash、SHA256 等元数据。

        Args:
            url: HuggingFace 文件完整 URL
            session: requests.Session 实例（含代理等配置）
            timeout: 超时时间（秒）

        Returns:
            XetFileInfo 包含 xet_hash、sha256、size、location 等信息

        Raises:
            ValueError: 不是 Xet 文件（缺少 X-Xet-Hash header）
            requests.HTTPError: 请求失败
        """
        resp = session.head(
            url, allow_redirects=False, timeout=timeout
        )
        resp.raise_for_status()

        if 'X-Xet-Hash' not in resp.headers and 'x-xet-hash' not in resp.headers:
            raise ValueError(f"[Xet] 不是 Xet 文件 (缺少 X-Xet-Hash header): {url}")

        return XetFileInfo.from_headers(dict(resp.headers))

    # ========================================================================
    # 辅助方法 (高级重试逻辑支持)
    # ========================================================================

    def _ensure_token(self):
        """主动检查 token 是否即将过期（提前 10 分钟刷新）。

        在长时间运行的任务中定期调用，避免请求时才发现过期。
        """
        if not self._auth:
            return

        # 从 auth 获取当前缓存的 token info
        token_info = self._auth._token_cache
        if not token_info:
            return

        # 检查是否即将过期（10 分钟缓冲）
        if time.time() >= token_info.expiration - 600:
            logger.info("[CAS] Token 即将过期，主动刷新...")
            self._refresh_token()

    def _force_refresh_token(self, max_retries: int = 3):
        """强制刷新 token（401 时调用），带重试和指数退避。

        Args:
            max_retries: 最大重试次数

        Raises:
            RuntimeError: 刷新失败
        """
        if not self._auth:
            raise RuntimeError("[CAS] 无法刷新 token: 未配置 XetAuth")

        for attempt in range(max_retries):
            try:
                self._check_interrupt()
                logger.info(f"[CAS] 强制刷新 token (尝试 {attempt + 1}/{max_retries})...")
                self._auth.clear_cache()
                new_info = self._auth.get_token(self._repo_id, auth_url=self._auth_url)
                self.access_token = new_info.access_token
                logger.warning(f"[CAS] Token 刷新成功，有效期至 {new_info.expiration}")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"[CAS] Token 刷新失败: {e}") from e
                backoff = 2.0 ** attempt
                logger.warning(f"[CAS] Token 刷新失败: {e}, {backoff}s 后重试...")
                self._interruptible_sleep(backoff)

    def _interruptible_sleep(self, seconds: float):
        """可中断睡眠（每 500ms 检查 stop_event）。

        Args:
            seconds: 睡眠时间（秒）
        """
        if not self._stop_event:
            time.sleep(seconds)
            return

        end_time = time.time() + seconds
        while time.time() < end_time:
            if self._stop_event.is_set():
                raise KeyboardInterrupt("[CAS] 用户中断")
            time.sleep(min(0.5, end_time - time.time()))

    def _check_interrupt(self):
        """快捷检查点（Ctrl+C 中断）。

        Raises:
            KeyboardInterrupt: 如果 stop_event 已设置
        """
        if self._stop_event and self._stop_event.is_set():
            raise KeyboardInterrupt("[CAS] 用户中断")

    def _find_xorb_in_recon(
        self,
        xorb_hash: str,
        recon: QueryReconstructionResponse,
        url_range: Optional[HttpRange] = None,
    ) -> Tuple[str, HttpRange]:
        """从 reconstruction 中查找 xorb 对应的新 URL。

        支持 multipart xorb（多个 fetch_info）。
        当传入 url_range 时，匹配 hash + range 精确定位。

        Args:
            xorb_hash: xorb 的 MerkleHash
            recon: 新获取的 reconstruction 响应
            url_range: 原始请求的字节范围（可选，用于精确匹配）

        Returns:
            (url, url_range) 元组

        Raises:
            ValueError: 找不到对应的 xorb 或范围
        """
        if xorb_hash not in recon.fetch_info:
            raise ValueError(
                f"[CAS] Reconstruction 中找不到 xorb: {xorb_hash[:16]}..."
            )

        fetch_infos = recon.fetch_info[xorb_hash]
        if not fetch_infos:
            raise ValueError(
                f"[CAS] Xorb {xorb_hash[:16]}... 的 fetch_info 为空"
            )

        # 如果没有 url_range，返回第一个 fetch_info
        if url_range is None:
            fi = fetch_infos[0]
            return fi.url, fi.url_range

        # 精确匹配：找到与 url_range 重叠的 fetch_info
        for fi in fetch_infos:
            # 检查范围是否匹配（允许部分重叠）
            if (fi.url_range.start <= url_range.start <= fi.url_range.end or
                fi.url_range.start <= url_range.end <= fi.url_range.end):
                return fi.url, fi.url_range

        # 未找到精确匹配，返回第一个（fallback）
        logger.warning(
            f"[CAS] 未找到精确匹配的 range，使用第一个 fetch_info: "
            f"期望 {url_range.to_header()}, 实际 {fetch_infos[0].url_range.to_header()}"
        )
        return fetch_infos[0].url, fetch_infos[0].url_range
