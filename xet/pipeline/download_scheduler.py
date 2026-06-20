"""下载调度器 - 并行下载 xorb 数据。

负责解析 reconstruction 响应，生成下载任务，并使用线程池并行下载。
"""
import logging
import threading
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from xet.network.cas_client import CASClient
from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.types import XorbDownloadTask, ReconstructionCheckpoint
from xet.pipeline.progress_tracker import ProgressTracker
from xet.pipeline.checkpoint_manager import CheckpointManager

logger = logging.getLogger(__name__)


class DownloadScheduler:
    """Xorb 并行下载调度器。

    职责：
    - 从 reconstruction 提取唯一 xorb 下载任务
    - 使用线程池并行下载
    - 集成 CheckpointManager 支持增量恢复
    - 集成 ProgressTracker 实时进度更新

    Attributes:
        cas_client: CAS API 客户端
        max_workers: 最大并发下载数
        progress_tracker: 进度跟踪器（可选）
        checkpoint_manager: Checkpoint 管理器（可选）
    """

    def __init__(
        self,
        cas_client: CASClient,
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
        """并行下载所有 xorb。

        Args:
            recon: Reconstruction 响应
            file_hash: 文件的 MerkleHash（用于 checkpoint 保存）
            checkpoint: 已有的 checkpoint（可选，用于增量恢复）

        Returns:
            {xorb_hash: compressed_xorb_data} 映射

        Raises:
            KeyboardInterrupt: 用户中断
            RuntimeError: 下载失败
        """
        # 1. 提取所有唯一 xorb 任务
        xorb_tasks = self._extract_xorb_tasks(recon)
        logger.info(f"[DownloadScheduler] 发现 {len(xorb_tasks)} 个唯一 xorb")

        # 2. 过滤已完成的 xorb（从 checkpoint）
        if checkpoint:
            original_count = len(xorb_tasks)
            xorb_tasks = [
                task for task in xorb_tasks
                if not checkpoint.is_completed(task.xorb_hash)
            ]
            skipped = original_count - len(xorb_tasks)
            if skipped > 0:
                logger.info(
                    f"[DownloadScheduler] 从 checkpoint 恢复，跳过 {skipped} 个已完成 xorb"
                )

        # 3. 如果没有待下载任务，直接返回空
        if not xorb_tasks:
            logger.info("[DownloadScheduler] 所有 xorb 已完成")
            return {}

        # 4. 并行下载
        xorb_data_map = {}
        failed_tasks = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            futures = {
                executor.submit(
                    self._download_single_xorb,
                    task,
                    file_hash,
                ): task
                for task in xorb_tasks
            }

            # 收集结果
            for future in as_completed(futures):
                task = futures[future]

                # 检查中断
                if self._stop_event.is_set():
                    logger.warning("[DownloadScheduler] 用户中断，取消剩余任务")
                    # 取消所有 pending 任务
                    for f in futures:
                        f.cancel()
                    raise KeyboardInterrupt("用户中断下载")

                try:
                    xorb_hash, data = future.result()
                    xorb_data_map[xorb_hash] = data

                    # 更新 checkpoint
                    if self.checkpoint_manager:
                        self.checkpoint_manager.mark_completed(file_hash, xorb_hash)

                    logger.debug(
                        f"[DownloadScheduler] 下载完成: {xorb_hash[:16]}... "
                        f"({len(data)} bytes)"
                    )

                except Exception as e:
                    logger.error(
                        f"[DownloadScheduler] 下载失败: {task.xorb_hash[:16]}..., {e}"
                    )
                    failed_tasks.append((task, e))

        # 5. 检查失败
        if failed_tasks:
            raise RuntimeError(
                f"下载失败: {len(failed_tasks)}/{len(xorb_tasks)} 个 xorb 失败"
            )

        logger.info(
            f"[DownloadScheduler] 所有 xorb 下载完成: {len(xorb_data_map)} 个"
        )
        return xorb_data_map

    def _download_single_xorb(
        self,
        task: XorbDownloadTask,
        file_hash: str,
    ) -> tuple[str, bytes]:
        """下载单个 xorb（使用 CASClient 的高级重试逻辑）。

        Args:
            task: Xorb 下载任务
            file_hash: 文件的 MerkleHash

        Returns:
            (xorb_hash, compressed_data) 元组

        Raises:
            RuntimeError: 下载失败
        """
        logger.debug(
            f"[DownloadScheduler] 开始下载: {task.xorb_hash[:16]}... "
            f"({task.url_range.length()} bytes)"
        )

        # 使用 CASClient 的 get_xorb_data_with_retry（集成所有高级特性）
        data = self.cas_client.get_xorb_data_with_retry(
            url=task.url,
            url_range=task.url_range,
            xorb_hash=task.xorb_hash,
            file_hash=file_hash,
            use_streaming=True,  # 启用低速检测
        )

        # 更新进度
        if self.progress_tracker:
            self.progress_tracker.increment_downloaded(len(data))

        return task.xorb_hash, data

    def _extract_xorb_tasks(
        self, recon: QueryReconstructionResponse
    ) -> List[XorbDownloadTask]:
        """从 reconstruction 提取所有唯一 xorb 下载任务。

        对于 multipart xorb（多个 fetch_info），只取第一个。

        Args:
            recon: Reconstruction 响应

        Returns:
            XorbDownloadTask 列表
        """
        tasks = []
        seen_xorbs = set()

        for xorb_hash, fetch_infos in recon.fetch_info.items():
            if xorb_hash in seen_xorbs:
                continue
            seen_xorbs.add(xorb_hash)

            # 对于 multipart，只取第一个 fetch_info
            # （完整 xorb 下载不需要多个 part）
            if not fetch_infos:
                logger.warning(
                    f"[DownloadScheduler] Xorb {xorb_hash[:16]}... 的 fetch_info 为空"
                )
                continue

            fi = fetch_infos[0]
            tasks.append(
                XorbDownloadTask(
                    xorb_hash=xorb_hash,
                    url=fi.url,
                    url_range=fi.url_range,
                )
            )

        return tasks
