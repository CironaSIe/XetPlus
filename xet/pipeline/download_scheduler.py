"""下载调度器 - 并行下载 xorb。

负责并发下载多个 xorb，管理下载任务队列、进度追踪、checkpoint。
支持 multipart segments（一个 xorb 可能有多个不连续的范围）。
支持 IP 故障转移（自动切换失败的 IP）。
"""
import logging
import threading
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.types import XorbDownloadTask, ReconstructionCheckpoint
from xet.pipeline.progress_tracker import ProgressTracker
from xet.pipeline.checkpoint_manager import CheckpointManager
from xet.pipeline.xorb_disk_cache import XorbDiskCache

logger = logging.getLogger(__name__)


class DownloadScheduler:
    """Xorb 下载调度器。

    职责：
    - 并行下载多个 xorbs
    - 处理 multipart segments（分别下载并合并）
    - 进度跟踪
    - Checkpoint 管理
    - IP 故障转移（自动切换失败的 IP）

    Attributes:
        cas_client: CAS API 客户端
        max_workers: 最大并发下载数
        progress_tracker: 进度跟踪器
        checkpoint_manager: Checkpoint 管理器
        ip_pool_manager: IP 池管理器（可选，用于故障转移）
        failure_detector: 故障检测器（可选）
        host_optimizer: HOST 优选器（可选，用于重新优选）
    """

    def __init__(
        self,
        cas_client,
        max_workers: int = 4,
        progress_tracker: Optional[ProgressTracker] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        stop_event: Optional[threading.Event] = None,
        xorb_cache: Optional[XorbDiskCache] = None,
        ip_pool_manager=None,  # Optional[IPPoolManager]
        host_optimizer=None,  # Optional[HostOptimizer]
    ):
        """初始化下载调度器。

        Args:
            cas_client: CAS API 客户端
            max_workers: 最大并发下载数
            progress_tracker: 进度跟踪器
            checkpoint_manager: Checkpoint 管理器
            stop_event: 中断信号（用于 Ctrl+C）
            xorb_cache: Xorb 磁盘缓存（可选）
            ip_pool_manager: IP 池管理器（可选，用于故障转移）
            host_optimizer: HOST 优选器（可选，用于重新优选）
        """
        self.cas_client = cas_client
        self.max_workers = max_workers
        self.progress_tracker = progress_tracker
        self.checkpoint_manager = checkpoint_manager
        self._stop_event = stop_event or threading.Event()
        self.xorb_cache = xorb_cache
        self.ip_pool_manager = ip_pool_manager
        self.host_optimizer = host_optimizer

        # 故障转移支持
        self._domain_cache: Dict[str, str] = {}  # URL → domain 缓存

    def download_all_xorbs(
        self,
        recon: QueryReconstructionResponse,
        file_hash: str,
        checkpoint: Optional[ReconstructionCheckpoint] = None,
    ) -> Dict[str, bytes]:
        """并行下载所有 xorb（支持 multipart segments）——已弃用。

        此方法将所有 xorb 同时加载到内存，大文件时会导致 OOM。
        已被 SegmentedReconstructor 的 ChunkAssembler 流式方案替代，
        仅在外部遗留调用中保留。

        一个 xorb 可能有多个不连续的 segments，需要分别下载并合并。

        Args:
            recon: Reconstruction 响应
            file_hash: 文件的 MerkleHash（用于 checkpoint 保存）
            checkpoint: 已有的 checkpoint（可选，用于增量恢复）

        Returns:
            {xorb_hash: merged_compressed_data} 映射
            注意：返回的数据是所有 segments 合并后的结果

        Raises:
            KeyboardInterrupt: 用户中断
            RuntimeError: 下载失败
        """
        logger.warning(
            "[DownloadScheduler] download_all_xorbs 已弃用，"
            "大文件可能 OOM。请使用 ChunkAssembler 流式方案。"
        )
        # 1. 提取所有唯一 xorb
        unique_xorbs = list(recon.fetch_info.keys())
        logger.info(f"[DownloadScheduler] 发现 {len(unique_xorbs)} 个唯一 xorb")

        # 2. 过滤已完成的 xorb（从 checkpoint）
        if checkpoint:
            original_count = len(unique_xorbs)
            unique_xorbs = [
                xorb_hash for xorb_hash in unique_xorbs
                if not checkpoint.is_completed(xorb_hash)
            ]
            skipped = original_count - len(unique_xorbs)
            if skipped > 0:
                logger.info(
                    f"[DownloadScheduler] 从 checkpoint 恢复，跳过 {skipped} 个已完成 xorb"
                )

        # 3. 如果没有待下载任务，直接返回空
        if not unique_xorbs:
            logger.info("[DownloadScheduler] 所有 xorb 已完成")
            return {}

        # 4. 并行下载所有 xorbs（每个 xorb 可能有多个 segments）
        xorb_data_map = {}
        failed_xorbs = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有 xorb 任务（每个 xorb 一个任务，内部处理 multipart）
            futures = {
                executor.submit(
                    self._download_single_xorb_multipart,
                    xorb_hash,
                    recon.fetch_info[xorb_hash],
                    file_hash,
                ): xorb_hash
                for xorb_hash in unique_xorbs
            }

            # 收集结果
            for future in as_completed(futures):
                xorb_hash = futures[future]

                # 检查中断
                if self._stop_event.is_set():
                    logger.info("[DownloadScheduler] 检测到中断信号，取消剩余任务")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise KeyboardInterrupt("用户中断下载")

                try:
                    merged_data = future.result()
                    xorb_data_map[xorb_hash] = merged_data

                    # 保存 checkpoint
                    if self.checkpoint_manager:
                        self.checkpoint_manager.mark_completed(file_hash, xorb_hash)

                except Exception as e:
                    logger.error(
                        f"[DownloadScheduler] Xorb {xorb_hash[:16]}... 下载失败: {e}"
                    )
                    failed_xorbs.append(xorb_hash)

        # 5. 检查失败
        if failed_xorbs:
            raise RuntimeError(
                f"[DownloadScheduler] {len(failed_xorbs)} 个 xorb 下载失败"
            )

        logger.info(
            f"[DownloadScheduler] 所有 xorb 下载完成: {len(xorb_data_map)} 个"
        )
        return xorb_data_map

    def _download_single_xorb_multipart(
        self,
        xorb_hash: str,
        fetch_infos: List,
        file_hash: str,
    ) -> bytes:
        """下载单个 xorb 的所有 segments 并合并。

        支持磁盘缓存：下载前检查缓存，下载后保存到缓存。

        参考 ~/xet.py 和 XET.SPEC.md 的实现。

        Args:
            xorb_hash: Xorb 的 MerkleHash
            fetch_infos: 该 xorb 的所有 fetch_info（可能有多个 segments）
            file_hash: 文件的 MerkleHash

        Returns:
            合并后的 xorb 数据（所有 segments 按顺序拼接）

        Raises:
            RuntimeError: 下载失败
        """
        if not fetch_infos:
            raise ValueError(f"[DownloadScheduler] Xorb {xorb_hash[:16]}... 没有 fetch_info")

        # 1. 尝试从磁盘缓存加载
        if self.xorb_cache:
            # 计算期望的最小大小（所有 segments 的 url_range 总和）
            expected_size = sum(fi.url_range.length() for fi in fetch_infos)

            cached_data = self.xorb_cache.get(xorb_hash, expected_size)
            if cached_data is not None:
                # 缓存命中，直接返回
                logger.info(
                    f"[DownloadScheduler] ✅ 缓存命中: {xorb_hash[:16]}... "
                    f"({len(cached_data)} bytes，跳过下载）"
                )
                # 更新进度（即使没有实际下载）
                if self.progress_tracker:
                    self.progress_tracker.increment_downloaded(len(cached_data))
                return cached_data

        # 2. 缓存未命中，从网络下载
        # 按 chunk_range.start 排序 segments
        sorted_infos = sorted(fetch_infos, key=lambda fi: fi.chunk_range.start)

        logger.debug(
            f"[DownloadScheduler] 下载 xorb: {xorb_hash[:16]}..., "
            f"{len(sorted_infos)} segment(s)"
        )

        # 分别下载每个 segment
        all_segments = []
        total_bytes = 0

        for idx, fi in enumerate(sorted_infos):
            logger.debug(
                f"[DownloadScheduler] 下载 segment {idx + 1}/{len(sorted_infos)}: "
                f"{xorb_hash[:16]}... "
                f"chunks=[{fi.chunk_range.start},{fi.chunk_range.end}), "
                f"bytes=[{fi.url_range.start},{fi.url_range.end}] "
                f"({fi.url_range.length()} bytes)"
            )

            # 带故障转移的下载
            segment_data = self._download_segment_with_failover(
                url=fi.url,
                url_range=fi.url_range,
                xorb_hash=xorb_hash,
                file_hash=file_hash,
            )

            all_segments.append(segment_data)
            total_bytes += len(segment_data)

            # 更新进度
            if self.progress_tracker:
                self.progress_tracker.increment_downloaded(len(segment_data))

        # 3. 合并所有 segments
        merged_data = b''.join(all_segments)

        logger.debug(
            f"[DownloadScheduler] Xorb {xorb_hash[:16]}... 下载完成: "
            f"{len(sorted_infos)} segments, {total_bytes} bytes total"
        )

        # 4. 保存到磁盘缓存
        if self.xorb_cache:
            self.xorb_cache.put(xorb_hash, merged_data)

        return merged_data

    def _download_segment_with_failover(
        self,
        url: str,
        url_range,
        xorb_hash: str,
        file_hash: str,
    ) -> bytes:
        """带故障转移的 segment 下载。

        Args:
            url: presigned URL
            url_range: 字节范围
            xorb_hash: xorb 的 MerkleHash
            file_hash: 文件的 MerkleHash

        Returns:
            segment 数据

        Raises:
            RuntimeError: IP 池耗尽或下载失败
        """
        max_failover_attempts = 5  # 最多 5 次 IP 切换

        for attempt in range(max_failover_attempts):
            try:
                # 调用 CASClient 的现有方法
                data = self.cas_client.get_xorb_data_with_retry(
                    url=url,
                    url_range=url_range,
                    xorb_hash=xorb_hash,
                    file_hash=file_hash,
                    use_streaming=True,
                )

                return data

            except Exception as e:
                # 检查是否应该触发故障转移
                if self.ip_pool_manager and self._should_trigger_failover(e):
                    logger.warning(
                        f"[Failover] 下载失败 (尝试 {attempt + 1}/{max_failover_attempts}): {e}"
                    )

                    # 尝试故障转移
                    success = self._handle_failover(url, str(e))

                    if success:
                        # 转移成功，重试下载
                        continue
                    else:
                        # IP 池耗尽
                        raise RuntimeError(
                            f"[Failover] IP 池耗尽，无法继续下载: {self._extract_domain(url)}"
                        )
                else:
                    # 不应转移，或无故障转移支持，直接抛出
                    raise

        # 超过最大重试次数
        raise RuntimeError(
            f"[Failover] 下载失败，已尝试 {max_failover_attempts} 次 IP 切换"
        )

    def _extract_domain(self, url: str) -> str:
        """从 URL 提取域名（带缓存）。

        Args:
            url: 完整 URL

        Returns:
            域名（不含端口和路径）
        """
        if url not in self._domain_cache:
            parsed = urlparse(url)
            self._domain_cache[url] = parsed.hostname or ""
        return self._domain_cache[url]

    def _should_trigger_failover(self, exception: Exception) -> bool:
        """判断异常是否应触发故障转移。

        Args:
            exception: 捕获的异常

        Returns:
            True: 应该转移，False: 不应转移
        """
        # 连接异常 → 转移
        if isinstance(exception, (ConnectionResetError, BrokenPipeError)):
            return True

        # 超时异常 → 转移
        if isinstance(exception, (socket.timeout, TimeoutError)):
            return True

        # HTTP 错误 → 部分转移
        if isinstance(exception, requests.HTTPError):
            # 5xx 服务器错误 → 转移
            if exception.response and 500 <= exception.response.status_code < 600:
                return True

        return False

    def _handle_failover(self, url: str, reason: str) -> bool:
        """处理故障转移。

        Args:
            url: 当前失败的 URL
            reason: 失败原因

        Returns:
            True: 转移成功，False: 转移失败（IP 池耗尽）
        """
        if not self.ip_pool_manager:
            logger.debug("[Failover] IPPoolManager 未启用，跳过故障转移")
            return False

        domain = self._extract_domain(url)
        if not domain:
            logger.warning(f"[Failover] 无法从 URL 提取域名: {url[:60]}...")
            return False

        # 1. 获取当前 IP 并标记失败
        current_result = self.ip_pool_manager.get_current_ip(domain)
        if current_result:
            current_ip, current_use_proxy = current_result
            # 标记当前 IP 失败
            self.ip_pool_manager.mark_failed(domain, current_ip, reason)

            # WARNING 级别日志
            logger.warning(
                f"[Failover] 域名 {domain} 的 IP {current_ip} 失败: {reason}"
            )

            # 用户通知
            mode_str = "代理" if current_use_proxy else "直连"
            print(f"\n⚠️  IP 故障: {current_ip} ({mode_str}) - {reason}")
            print(f"🔄 正在切换 {domain} 到新 IP...")

        # 2. 获取下一个可用 IP
        next_result = self.ip_pool_manager.get_next_ip(domain)

        if not next_result:
            # IP 池耗尽 → 触发重新优选
            logger.error(
                f"[Failover] 域名 {domain} 的 IP 池已耗尽，尝试重新优选"
            )
            print(f"⚠️  {domain} IP 池耗尽")

            if self.host_optimizer:
                print(f"🚀 正在重新优选 {domain}...")
                logger.info(f"[Failover] 调用 HostOptimizer 重新优选 {domain}")

                try:
                    # 重新优选该域名
                    new_mapping = self.host_optimizer.optimize([domain])

                    if domain in new_mapping:
                        logger.info(
                            f"[Failover] 重新优选成功: {domain} → "
                            f"{new_mapping[domain]['ip']}"
                        )

                        # 触发 IP 池重载
                        self.ip_pool_manager.trigger_reoptimization(domain)

                        # 再次尝试获取 IP
                        next_result = self.ip_pool_manager.get_next_ip(domain)
                    else:
                        logger.error(f"[Failover] 重新优选未返回 {domain} 的映射")
                        print(f"✗ 重新优选失败: 无可用 IP")
                        return False

                except Exception as e:
                    logger.error(f"[Failover] 重新优选异常: {e}", exc_info=True)
                    print(f"✗ 重新优选失败: {e}")
                    return False
            else:
                logger.error("[Failover] 无 HostOptimizer 实例，无法重新优选")
                print(f"✗ 无法重新优选: 未启用 HOST 优选")
                return False

        if next_result:
            next_ip, use_proxy = next_result

            # 3. 动态更新 IP 映射
            from xet.network.host_optimizer import update_ip_mapping
            update_ip_mapping(domain, next_ip)

            logger.debug(f"[Failover] 已更新动态映射: {domain} → {next_ip}")

            # 4. 获取统计信息并通知用户
            stats = self.ip_pool_manager.get_pool_stats(domain)
            mode = "代理" if use_proxy else "直连"

            # INFO 级别日志
            logger.info(
                f"[Failover] ✓ 切换成功: {domain} → {next_ip} ({mode}), "
                f"剩余可用 IP: {stats['available']}/{stats['total']}"
            )

            # 用户通知（成功）
            print(
                f"✅ 切换成功: {next_ip} ({mode}), "
                f"剩余 {stats['available']} 个可用 IP\n"
            )

            return True

        # 未能获取新 IP
        logger.error(f"[Failover] 无法为 {domain} 获取新 IP")
        return False

