"""文件重建协调器 - Pipeline Layer 核心组件。

整合所有子组件，提供端到端的文件重建流程。
"""
import logging
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any

from xet.network.cas_client import CASClient
from xet.pipeline.download_scheduler import DownloadScheduler
from xet.pipeline.chunk_assembler import ChunkAssembler
from xet.pipeline.checkpoint_manager import CheckpointManager
from xet.pipeline.progress_tracker import ProgressTracker

logger = logging.getLogger(__name__)


class ReconstructionError(Exception):
    """文件重建失败异常。"""
    pass


class FileReconstructor:
    """文件重建协调器 - Phase 4 核心组件。

    职责：
    - 整合所有 Pipeline 子组件
    - 执行完整的文件重建流程
    - 统一的错误处理和资源清理

    组件架构：
    - DownloadScheduler: 并行下载 xorb
    - ChunkAssembler: 解压和组装文件
    - CheckpointManager: 断点续传支持
    - ProgressTracker: 实时进度跟踪

    Attributes:
        cas_client: CAS API 客户端
        output_path: 输出文件路径
        temp_dir: 临时目录
        checkpoint_manager: Checkpoint 管理器
        progress_tracker: 进度跟踪器
        scheduler: 下载调度器
        assembler: 数据组装器
    """

    def __init__(
        self,
        cas_client: CASClient,
        output_path: Path,
        temp_dir: Optional[Path] = None,
        checkpoint_path: Optional[Path] = None,
        max_workers: int = 4,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        """初始化文件重建协调器。

        Args:
            cas_client: CAS API 客户端
            output_path: 输出文件路径
            temp_dir: 临时目录（用于中间文件）
            checkpoint_path: Checkpoint 文件路径（None 表示禁用）
            max_workers: 最大并发下载数
            progress_callback: 进度更新回调函数
            stop_event: 中断信号（用于 Ctrl+C）
        """
        self.cas_client = cas_client
        self.output_path = output_path
        self.temp_dir = temp_dir or Path.cwd() / ".xet_temp"
        self._stop_event = stop_event or threading.Event()

        # 初始化子组件
        self.checkpoint_manager = CheckpointManager(checkpoint_path) if checkpoint_path else None
        self.progress_tracker = ProgressTracker(callback=progress_callback)
        self.scheduler = DownloadScheduler(
            cas_client=cas_client,
            max_workers=max_workers,
            progress_tracker=self.progress_tracker,
            checkpoint_manager=self.checkpoint_manager,
            stop_event=self._stop_event,
        )
        self.assembler = ChunkAssembler(temp_dir=self.temp_dir)

        logger.info(
            f"[FileReconstructor] 初始化完成: "
            f"output={output_path}, max_workers={max_workers}, "
            f"checkpoint={'enabled' if checkpoint_path else 'disabled'}"
        )

    def reconstruct_file(
        self,
        file_hash: str,
        expected_size: int = 0,
        resume: bool = True,
    ) -> Path:
        """重建文件（端到端流程）。

        完整流程：
        1. 获取 reconstruction 信息
        2. 检查并加载 checkpoint（可选）
        3. 并行下载所有 xorb
        4. 解压和组装文件
        5. 清理 checkpoint

        Args:
            file_hash: 文件的 MerkleHash
            expected_size: 预期文件大小（用于进度计算，0 表示未知）
            resume: 是否尝试从 checkpoint 恢复

        Returns:
            输出文件路径

        Raises:
            ReconstructionError: 重建失败
            KeyboardInterrupt: 用户中断
        """
        logger.info(
            f"[FileReconstructor] 开始重建文件: {file_hash[:16]}... "
            f"(size={expected_size}, resume={resume})"
        )

        try:
            # 1. 获取 reconstruction 信息
            logger.info("[FileReconstructor] 获取 reconstruction 信息...")
            recon = self.cas_client.get_reconstruction(file_hash)
            logger.info(
                f"[FileReconstructor] Reconstruction 获取成功: "
                f"{len(recon.terms)} terms, "
                f"{len(recon.fetch_info)} 唯一 xorb"
            )

            # 2. 设置进度跟踪器总大小
            if expected_size > 0:
                self.progress_tracker.set_total_bytes(expected_size)
            else:
                # 从 terms 计算总大小
                total_size = sum(term.unpacked_length for term in recon.terms)
                self.progress_tracker.set_total_bytes(total_size)
                logger.info(f"[FileReconstructor] 计算文件大小: {total_size} bytes")

            # 3. 检查并加载 checkpoint（可选）
            checkpoint = None
            if resume and self.checkpoint_manager:
                logger.info("[FileReconstructor] 尝试加载 checkpoint...")
                checkpoint = self.checkpoint_manager.load(file_hash)
                if checkpoint:
                    logger.info(
                        f"[FileReconstructor] Checkpoint 加载成功: "
                        f"{checkpoint.completion_count()} 个 xorb 已完成"
                    )

            # 4. 下载所有 xorb
            logger.info("[FileReconstructor] 开始下载 xorb...")
            xorb_data_map = self.scheduler.download_all_xorbs(
                recon=recon,
                file_hash=file_hash,
                checkpoint=checkpoint,
            )
            logger.info(
                f"[FileReconstructor] Xorb 下载完成: {len(xorb_data_map)} 个"
            )

            # 5. 组装文件
            logger.info("[FileReconstructor] 开始组装文件...")
            self.assembler.assemble_file(
                recon=recon,
                xorb_data_map=xorb_data_map,
                output_path=self.output_path,
                progress_tracker=self.progress_tracker,
            )
            logger.info(f"[FileReconstructor] 文件组装完成: {self.output_path}")

            # 6. 清理 checkpoint
            if self.checkpoint_manager:
                logger.info("[FileReconstructor] 清理 checkpoint...")
                self.checkpoint_manager.clear(file_hash)

            # 7. 验证文件大小
            actual_size = self.output_path.stat().st_size
            if expected_size > 0 and actual_size != expected_size:
                raise ReconstructionError(
                    f"文件大小不匹配: 期望 {expected_size}, 实际 {actual_size}"
                )

            logger.info(
                f"[FileReconstructor] 文件重建成功: {self.output_path} "
                f"({actual_size} bytes)"
            )

            return self.output_path

        except KeyboardInterrupt:
            logger.warning("[FileReconstructor] 用户中断")
            raise

        except Exception as e:
            logger.error(f"[FileReconstructor] 文件重建失败: {e}")
            raise ReconstructionError(f"文件重建失败: {e}") from e

    def get_progress(self) -> Dict[str, Any]:
        """获取当前进度信息。

        Returns:
            进度统计字典
        """
        return self.progress_tracker.get_stats()

    def format_progress(self) -> str:
        """格式化进度为人类可读字符串。

        Returns:
            格式化的进度字符串
        """
        return self.progress_tracker.format_stats()

    def stop(self) -> None:
        """停止文件重建（触发中断）。"""
        logger.warning("[FileReconstructor] 触发停止信号")
        self._stop_event.set()

    def cleanup(self) -> None:
        """清理临时文件和资源。"""
        try:
            if self.temp_dir and self.temp_dir.exists():
                # 清理临时目录（如果为空）
                if not any(self.temp_dir.iterdir()):
                    self.temp_dir.rmdir()
                    logger.info(f"[FileReconstructor] 清理临时目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"[FileReconstructor] 清理失败: {e}")
