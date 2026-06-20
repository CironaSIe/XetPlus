"""CAS (Content Addressable Storage) API 客户端。

与 HuggingFace CAS 服务交互，执行：
1. Reconstruction Query - 获取文件重建信息
2. Xorb Data Download - 下载 xorb 数据块
"""
import logging
import uuid
import threading
from typing import Optional, Tuple

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

    def __init__(
        self,
        endpoint: str,
        access_token: str,
        session: requests.Session,
        auth: Optional[XetAuth] = None,
        repo_id: str = "",
        auth_url: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
        url_coordinator: Optional[URLRefreshCoordinator] = None,
        acc: Optional[AdaptiveConcurrencyController] = None,
        retry_max: int = 5,
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
        """
        self.endpoint = endpoint.rstrip('/')
        self.access_token = access_token
        self.session = session
        self._auth = auth
        self._repo_id = repo_id
        self._auth_url = auth_url
        self._stop_event = stop_event
        self._url_coordinator = url_coordinator
        self._acc = acc
        self.retry_max = retry_max
        # Session ID 用于 CloudFront 会话跟踪
        self.session_id = uuid.uuid4().hex[:16]
        # V2 API 版本探测缓存
        self._v2_available: Optional[bool] = None

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
        headers = self._get_headers()

        # 尝试 V2 API（如果尚未确认不可用）
        if self._v2_available is not False:
            try:
                url_v2 = f"{self.endpoint}/v2/reconstructions/{file_hash}"
                logger.debug(f"[CAS] 尝试 V2 API: {url_v2[:80]}...")
                resp = self.session.get(
                    url_v2, headers=headers, timeout=self.session.timeout
                )

                if resp.status_code == 200:
                    self._v2_available = True
                    return QueryReconstructionResponse.from_dict(resp.json())
                elif resp.status_code == 401:
                    # 401: Token 过期，刷新后重试
                    self._refresh_token()
                    headers = self._get_headers()
                    resp = self.session.get(
                        url_v2, headers=headers, timeout=self.session.timeout
                    )
                    resp.raise_for_status()
                    self._v2_available = True
                    return QueryReconstructionResponse.from_dict(resp.json())
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

        resp = self.session.get(url_v1, headers=headers, timeout=self.session.timeout)

        if resp.status_code == 401:
            # 401: Token 过期，刷新后重试
            self._refresh_token()
            headers = self._get_headers()
            resp = self.session.get(
                url_v1, headers=headers, timeout=self.session.timeout
            )

        resp.raise_for_status()
        return QueryReconstructionResponse.from_dict(resp.json())

    @with_retry(max_attempts=5, backoff_base=1.5, retry_on=(requests.RequestException,))
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

        resp = self.session.get(url, headers=headers, timeout=self.session.timeout)
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
            url, headers=headers, timeout=self.session.timeout, stream=True
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

        return bytes(buffer)

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
        acc_acquired = False
        current_url = url
        current_range = url_range

        for attempt in range(self.retry_max):
            self._check_interrupt()

            # 1. 获取 ACC 许可
            if self._acc:
                acc_acquired = self._acc.acquire(timeout=300.0)
                if not acc_acquired:
                    logger.error("[CAS] ACC acquire 超时，放弃")
                    raise RuntimeError("AdaptiveConcurrencyController acquire 超时")

            try:
                # 2. 主动检查 token 过期
                self._ensure_token()

                # 3. 下载 xorb 数据
                if use_streaming:
                    data = self.get_xorb_data_streaming(current_url, current_range)
                else:
                    data = self.get_xorb_data(current_url, current_range)

                # 4. 成功：释放 ACC 并报告
                if acc_acquired and self._acc:
                    self._acc.release()
                    self._acc.report_success(bytes_transferred=len(data))

                return data

            except requests.HTTPError as e:
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
                            recon = self.get_reconstruction(file_hash)
                            current_url, current_range = self._find_xorb_in_recon(
                                xorb_hash, recon, url_range
                            )
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
                        # 其他线程在刷新或冷却期，等待后重试
                        logger.info("[CAS] 其他线程在刷新 URL，等待...")

                    # 403 专用退避（比普通错误更长）
                    base_403 = 5.0
                    delay = base_403 * (2.5 ** attempt) * random.uniform(0.7, 1.3)
                    logger.debug(f"[CAS] 403 退避: {delay:.2f}s")
                    self._interruptible_sleep(delay)
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

    @staticmethod
    def get_xet_file_info(
        url: str,
        session: requests.Session,
    ) -> XetFileInfo:
        """从 HuggingFace URL 获取 Xet 文件信息。

        通过 HEAD 请求（不跟随重定向）检测文件是否为 Xet 格式，
        并提取 X-Xet-Hash、SHA256 等元数据。

        Args:
            url: HuggingFace 文件完整 URL
            session: requests.Session 实例（含代理等配置）

        Returns:
            XetFileInfo 包含 xet_hash、sha256、size、location 等信息

        Raises:
            ValueError: 不是 Xet 文件（缺少 X-Xet-Hash header）
            requests.HTTPError: 请求失败
        """
        resp = session.head(
            url, allow_redirects=False, timeout=session.timeout
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
                logger.info(f"[CAS] Token 刷新成功，有效期至 {new_info.expiration}")
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
