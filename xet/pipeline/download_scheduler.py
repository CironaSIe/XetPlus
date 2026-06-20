"""下载调度器 - 并行下载 xorb。

负责并发下载多个 xorb，管理下载任务队列、进度追踪、checkpoint。
支持 multipart segments（一个 xorb 可能有多个不连续的范围）。
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.types import XorbDownloadTask, ReconstructionCheckpoint
from xet.pipeline.progress_tracker import ProgressTracker
from xet.pipeline.checkpoint_manager import CheckpointManager

logger = logging.getLogger(__name__)


class DownloadScheduler:
    """Xorb 下载调度器。

    职责：
    - 并行下载多个 xorbs
    - 处理 multipart segments（分别下载并合并）
    - 进度跟踪
    - Checkpoint 管理

    Attributes:
        cas_client: CAS API 客户端
        max_workers: 最大并发下载数
        progress_tracker: 进度跟踪器
        checkpoint_manager: Checkpoint 管理器
    """

    def __init__(
        self,
        cas_client,
        max_workers: int = 4,
        progress_tracker: Optional[ProgressTracker] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        """初始化下载调度器。

        Args:
            cas_client: CAS API 客户端
            max_workers: 最大并发下载数
            progress_tracker: 进度跟踪器
            checkpoint_manager: Checkpoint 管理器
            stop_event: 中断信号（用于 Ctrl+C）
        """
        self.cas_client = cas_client
        self.max_workers = max_workers
        self.progress_tracker = progress_tracker
        self.checkpoint_manager = checkpoint_manager
        self._stop_event = stop_event or threading.Event()

    def download_all_xorbs(
        self,
        recon: QueryReconstructionResponse,
        file_hash: str,
        checkpoint: Optional[ReconstructionCheckpoint] = None,
    ) -> Dict[str, bytes]:
        """并行下载所有 xorb（支持 multipart segments）。

        一个 xorb 可能有多个不连续的 segments，需要分别下载并合并。
        参考 ~/xet.py 和 XET.SPEC.md 的 multipart 处理逻辑。

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

            segment_data = self.cas_client.get_xorb_data_with_retry(
                url=fi.url,
                url_range=fi.url_range,
                xorb_hash=xorb_hash,
                file_hash=file_hash,
                use_streaming=True,
            )

            all_segments.append(segment_data)
            total_bytes += len(segment_data)

            # 更新进度
            if self.progress_tracker:
                self.progress_tracker.increment_downloaded(len(segment_data))

        # 合并所有 segments
        merged_data = b''.join(all_segments)

        logger.debug(
            f"[DownloadScheduler] Xorb {xorb_hash[:16]}... 下载完成: "
            f"{len(sorted_infos)} segments, {total_bytes} bytes total"
        )

        return merged_data
