"""分段文件重建器 - 支持超大文件下载。

参考 xet.py 的分段机制：
1. 将大文件按大小分段（默认256MB）
2. 每段独立请求 reconstruction
3. 段级 checkpoint（segments.json）
4. 支持断点续传（跳过已完成段）
5. 内存占用受 segment_size 控制
6. 支持并行段下载（多线程）

适用场景：
- 超大文件 (>1GB)
- 内存受限环境
- 需要更细粒度的断点续传
- 需要加速下载（并行段）
"""
import json
import logging
import threading
import time
import queue
import shutil
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple, Set
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from xet.network.cas_client import CASClient
from xet.pipeline.file_reconstructor import FileReconstructor
from xet.pipeline.types import ReconstructionCheckpoint
from xet.pipeline.chunk_assembler import ChunkAssembler
from xet.pipeline.chunk_cache_adapter import ChunkCacheAdapter
from xet.pipeline.checkpoint_manager import CheckpointManager
from xet.pipeline.progress_tracker import ProgressTracker

logger = logging.getLogger(__name__)


@dataclass
class SegmentInfo:
    """分段信息。"""
    index: int          # 段索引（从0开始）
    start: int          # 文件起始位置（字节）
    end: int            # 文件结束位置（字节，不含）
    size: int           # 段大小（字节）
    completed: bool     # 是否已完成


class SegmentCheckpointManager:
    """段级 checkpoint 管理器。

    负责：
    - 保存/加载已完成的段列表
    - 线程安全的文件 I/O

    文件格式（segments.json）：
    {
        "file_hash": "...",
        "completed": [
            {"index": 0, "start": 0, "end": 268435456, "size": 268435456},
            {"index": 1, "start": 268435456, "end": 536870912, "size": 268435456}
        ],
        "timestamp": 1234567890
    }
    """

    def __init__(self, checkpoint_path: Path):
        """初始化段级 checkpoint 管理器。

        Args:
            checkpoint_path: checkpoint 文件路径（通常是 target.parent / f"{target.name}.segments.json"）
        """
        self.checkpoint_path = checkpoint_path
        self._lock = threading.Lock()

    def load(self, file_hash: str) -> Set[Tuple[int, int]]:
        """加载已完成的段集合。

        Args:
            file_hash: 文件的 MerkleHash

        Returns:
            已完成段的 (start, end) 集合
        """
        if not self.checkpoint_path.exists():
            return set()

        with self._lock:
            try:
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 检查文件 hash 是否匹配
                if data.get('file_hash') != file_hash:
                    logger.warning(
                        f"[SegmentCheckpoint] hash 不匹配: "
                        f"期望 {file_hash[:16]}..., 实际 {data.get('file_hash', '')[:16]}..."
                    )
                    return set()

                # 提取已完成段
                completed_set = set()
                for seg in data.get('completed', []):
                    completed_set.add((seg['start'], seg['end']))

                logger.info(
                    f"[SegmentCheckpoint] 加载成功: {len(completed_set)} 个段已完成"
                )

                return completed_set

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"[SegmentCheckpoint] 加载失败: {e}")
                return set()

    def save(self, file_hash: str, completed_segments: List[Dict[str, int]]) -> None:
        """保存已完成的段列表。

        Args:
            file_hash: 文件的 MerkleHash
            completed_segments: 已完成段的列表，每项包含 index/start/end/size
        """
        with self._lock:
            try:
                # 确保目录存在
                self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

                # 写入临时文件，然后原子替换
                tmp_path = self.checkpoint_path.with_suffix('.tmp')
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        {
                            'file_hash': file_hash,
                            'completed': completed_segments,
                            'timestamp': int(time.time()),
                        },
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                tmp_path.replace(self.checkpoint_path)

                logger.debug(
                    f"[SegmentCheckpoint] 保存成功: {len(completed_segments)} 个段"
                )

            except (IOError, OSError) as e:
                logger.error(f"[SegmentCheckpoint] 保存失败: {e}")

    def clear(self) -> None:
        """清理 checkpoint 文件。"""
        with self._lock:
            try:
                if self.checkpoint_path.exists():
                    self.checkpoint_path.unlink()
                    logger.info(f"[SegmentCheckpoint] 清理完成: {self.checkpoint_path}")
            except Exception as e:
                logger.warning(f"[SegmentCheckpoint] 清理失败: {e}")


class SegmentedReconstructor:
    """分段文件重建器。

    核心设计：
    - 将大文件分成固定大小的 segment（默认 256MB）
    - 每个 segment 独立请求 reconstruction（降低单次请求内存）
    - 每个 segment 完成后立即保存 checkpoint
    - 断点续传时跳过已完成的 segment

    与 FileReconstructor 的区别：
    - FileReconstructor: 一次性获取整个文件的 reconstruction
    - SegmentedReconstructor: 分段获取 reconstruction，降低内存占用

    适用场景：
    - 文件 > 1GB
    - 内存受限（每次只处理一个 segment）
    - 需要更细粒度的断点续传
    """

    # 默认分段大小（256MB）
    DEFAULT_SEGMENT_SIZE = 256 * 1024 * 1024

    # 最大分段大小（避免单段过大）
    MAX_SEGMENT_SIZE = 512 * 1024 * 1024

    def __init__(
        self,
        cas_client: CASClient,
        output_path: Path,
        file_hash: str,
        file_size: int,
        segment_size: Optional[int] = None,
        temp_dir: Optional[Path] = None,
        max_workers: int = 4,
        parallel_segments: int = 1,
        parallel_write: bool = False,
        chunk_cache=None,
        xorb_cache=None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        """初始化分段文件重建器。

        Args:
            cas_client: CAS API 客户端
            output_path: 输出文件路径
            file_hash: 文件的 MerkleHash
            file_size: 文件总大小（字节）
            segment_size: 分段大小（字节），None 表示自动选择
            temp_dir: 临时目录
            max_workers: 每段的最大并发下载数
            parallel_segments: 并行段数（默认1表示顺序下载）
            parallel_write: 是否启用并行写入（需要预分配文件）
            chunk_cache: Chunk 级磁盘缓存（可选）
            xorb_cache: Xorb 级磁盘缓存（可选）
            progress_callback: 进度更新回调
            stop_event: 中断信号
        """
        self.cas_client = cas_client
        self.output_path = output_path
        self.file_hash = file_hash
        self.file_size = file_size
        self.temp_dir = temp_dir or Path.cwd() / ".xet_temp"
        self.max_workers = max_workers
        self.parallel_segments = max(1, parallel_segments)
        self.parallel_write = parallel_write
        self.chunk_cache = chunk_cache
        self.xorb_cache = xorb_cache
        self.progress_callback = progress_callback
        self._stop_event = stop_event or threading.Event()

        # 确定分段大小
        self.segment_size = self._determine_segment_size(segment_size, file_size)

        # 计算分段列表
        self.segments = self._calculate_segments(file_size, self.segment_size)

        # 段级 checkpoint
        checkpoint_path = output_path.parent / f"{output_path.name}.segments.json"
        self.segment_checkpoint = SegmentCheckpointManager(checkpoint_path)

        # 已完成段集合
        self.completed_segments: List[Dict[str, int]] = []
        self.completed_set: Set[Tuple[int, int]] = set()

        # 线程安全锁
        self._lock = threading.Lock()

        # 全局写队列（并行模式使用）
        self._write_queue: Optional[queue.Queue] = None
        self._writer_thread: Optional[threading.Thread] = None

        logger.info(
            f"[SegmentedReconstructor] 初始化完成: "
            f"file_size={file_size}, segment_size={self.segment_size}, "
            f"segments={len(self.segments)}, parallel_segments={self.parallel_segments}"
        )

    def _determine_segment_size(self, segment_size: Optional[int], file_size: int) -> int:
        """确定分段大小。

        Args:
            segment_size: 用户指定的分段大小（None 表示自动）
            file_size: 文件总大小

        Returns:
            实际使用的分段大小（字节）
        """
        if segment_size is not None:
            # 用户指定，但不能超过最大值
            actual = min(segment_size, self.MAX_SEGMENT_SIZE)
            if actual < segment_size:
                logger.warning(
                    f"[SegmentedReconstructor] 分段大小超过上限 {self.MAX_SEGMENT_SIZE}, "
                    f"调整为 {actual}"
                )
            return actual

        # 自动选择（参考 xet.py 的策略）
        GiB = 1024 ** 3
        MiB = 1024 ** 2

        if file_size > 10 * GiB:
            return 256 * MiB  # >10GB → 256MB
        elif file_size > 1 * GiB:
            return 64 * MiB   # 1-10GB → 64MB
        else:
            return 4 * MiB    # <1GB → 4MB

    def _calculate_segments(self, file_size: int, segment_size: int) -> List[SegmentInfo]:
        """计算分段列表。

        Args:
            file_size: 文件总大小
            segment_size: 分段大小

        Returns:
            分段信息列表
        """
        segments = []
        offset = 0
        index = 0

        while offset < file_size:
            end = min(offset + segment_size, file_size)
            seg_size = end - offset

            segments.append(SegmentInfo(
                index=index,
                start=offset,
                end=end,
                size=seg_size,
                completed=False,
            ))

            offset = end
            index += 1

        return segments

    def reconstruct_file(self, resume: bool = True) -> Path:
        """分段重建文件。

        完整流程：
        1. 加载段级 checkpoint
        2. 预分配文件空间
        3. 根据并行度选择模式：
           - parallel_segments = 1: 顺序下载
           - parallel_segments > 1: 并行下载（全局单writer模式）
        4. 清理 checkpoint

        Args:
            resume: 是否从 checkpoint 恢复

        Returns:
            输出文件路径

        Raises:
            Exception: 重建失败
        """
        logger.info(
            f"[SegmentedReconstructor] 开始分段重建: "
            f"{self.file_hash[:16]}..., {len(self.segments)} 个段, "
            f"并行度={self.parallel_segments}"
        )

        try:
            # 1. 加载 checkpoint
            if resume:
                self.completed_set = self.segment_checkpoint.load(self.file_hash)
                # 重建 completed_segments 列表
                for seg in self.segments:
                    if (seg.start, seg.end) in self.completed_set:
                        seg.completed = True
                        self.completed_segments.append({
                            'index': seg.index,
                            'start': seg.start,
                            'end': seg.end,
                            'size': seg.size,
                        })

                if self.completed_segments:
                    logger.info(
                        f"[SegmentedReconstructor] 发现 {len(self.completed_segments)} 个已完成段，跳过"
                    )

            # 2. 预分配文件空间
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            if self.parallel_write:
                # 并行写入模式：预分配以支持随机偏移写入
                if not self.output_path.exists() or self.output_path.stat().st_size != self.file_size:
                    logger.info(f"[SegmentedReconstructor] 预分配文件空间: {self.file_size} bytes")
                    with open(self.output_path, 'wb') as f:
                        f.seek(self.file_size - 1)
                        f.write(b'\0')
            else:
                # 顺序写入模式：只需创建空文件，随写入自然增长
                if not self.output_path.exists():
                    logger.info(f"[SegmentedReconstructor] 创建空文件: {self.file_size} bytes")
                    self.output_path.touch()

            # 3. 选择下载模式
            if self.parallel_segments > 1:
                self._reconstruct_parallel()
            else:
                self._reconstruct_sequential()

            # 4. 清理 checkpoint
            self.segment_checkpoint.clear()

            logger.info(
                f"[SegmentedReconstructor] 分段重建完成: {self.output_path}"
            )

            return self.output_path

        except KeyboardInterrupt:
            completed = len(self.completed_segments)
            done_bytes = sum(s.get('size', 0) for s in self.completed_segments)
            total_seg = len(self.segments)
            logger.info(
                f"[SegmentedReconstructor] 用户中断，断点已保存: "
                f"{completed}/{total_seg}段, {done_bytes}/{self.file_size}字节"
            )
            raise

        except Exception as e:
            logger.error(f"[SegmentedReconstructor] 分段重建失败: {e}")
            raise

    def _reconstruct_sequential(self) -> None:
        """顺序重建（逐段处理）。"""
        for seg in self.segments:
            # 检查中断信号
            if self._stop_event.is_set():
                completed = len(self.completed_segments)
                done_bytes = sum(s.get('size', 0) for s in self.completed_segments)
                total_seg = len(self.segments)
                logger.info(
                    f"[SegmentedReconstructor] 用户中断，断点已保存: "
                    f"{completed}/{total_seg}段, {done_bytes}/{self.file_size}字节"
                )
                raise KeyboardInterrupt()

            # 跳过已完成的段
            if seg.completed:
                logger.debug(f"[SegmentedReconstructor] 跳过已完成段 {seg.index}")
                continue

            # 处理该段
            self._process_segment(seg)

            # 标记完成并保存 checkpoint
            self._mark_segment_completed(seg)

    def _reconstruct_parallel(self) -> None:
        """并行重建（多段同时处理）。

        采用全局单writer模式：
        - 所有worker共享一个write queue
        - 单独的writer线程负责写入文件
        - worker只负责下载和解压
        """
        logger.info(
            f"[SegmentedReconstructor] 启动并行模式: {self.parallel_segments} 个worker"
        )

        # 1. 启动全局writer线程
        self._write_queue = queue.Queue(maxsize=self.parallel_segments * 2)
        self._writer_thread = threading.Thread(
            target=self._writer_worker,
            name="SegmentWriter",
            daemon=True,
        )
        self._writer_thread.start()

        # 2. 准备待处理的段
        pending_segments = [seg for seg in self.segments if not seg.completed]

        if not pending_segments:
            logger.info("[SegmentedReconstructor] 所有段已完成")
            self._write_queue.put(None)  # 停止writer
            self._writer_thread.join()
            return

        # 3. 使用线程池并行处理
        success_count = 0
        failed_segments = []

        with ThreadPoolExecutor(max_workers=self.parallel_segments) as executor:
            # 提交所有待处理段
            future_to_seg = {
                executor.submit(self._process_segment_parallel, seg): seg
                for seg in pending_segments
            }

            # 等待完成
            for future in as_completed(future_to_seg):
                seg = future_to_seg[future]

                # 检查中断信号
                if self._stop_event.is_set():
                    logger.warning("[SegmentedReconstructor] 用户中断，取消所有段")
                    for f in future_to_seg:
                        f.cancel()
                    raise KeyboardInterrupt()

                try:
                    future.result()
                    success_count += 1
                    logger.debug(f"[SegmentedReconstructor] 段 {seg.index} 完成")
                except Exception as e:
                    logger.error(f"[SegmentedReconstructor] 段 {seg.index} 失败: {e}")
                    failed_segments.append((seg, e))

        # 4. 停止writer线程
        self._write_queue.put(None)
        self._writer_thread.join()

        # 5. 检查是否有失败的段
        if failed_segments:
            logger.error(
                f"[SegmentedReconstructor] {len(failed_segments)} 个段失败"
            )
            # 抛出第一个错误
            seg, err = failed_segments[0]
            raise RuntimeError(f"段 {seg.index} 失败: {err}") from err

        logger.info(
            f"[SegmentedReconstructor] 并行重建完成: {success_count}/{len(pending_segments)} 段"
        )

    def _writer_worker(self) -> None:
        """全局writer线程（接收写入任务并执行）。

        从write_queue接收 (offset, data) 元组，写入文件。
        收到 None 时退出。
        """
        logger.debug("[SegmentWriter] 启动")

        try:
            # 打开文件（r+b模式）
            with open(self.output_path, 'r+b') as f:
                while True:
                    # 从队列获取任务
                    item = self._write_queue.get()

                    # None 表示结束
                    if item is None:
                        logger.debug("[SegmentWriter] 收到停止信号")
                        break

                    offset, data = item

                    # 写入文件
                    f.seek(offset)
                    f.write(data)
                    f.flush()

                    logger.debug(
                        f"[SegmentWriter] 写入完成: offset={offset}, size={len(data)}"
                    )

        except Exception as e:
            logger.error(f"[SegmentWriter] 写入失败: {e}")
            raise

        logger.debug("[SegmentWriter] 退出")

    def _process_segment_parallel(self, seg: SegmentInfo) -> None:
        """处理单个分段（并行模式）。

        下载和解压数据，然后发送到write_queue。

        Args:
            seg: 分段信息
        """
        logger.info(
            f"[SegmentedReconstructor] [并行] 处理段 {seg.index + 1}/{len(self.segments)}: "
            f"offset={seg.start}, size={seg.size}"
        )

        # 1. 请求 segment reconstruction
        recon = self.cas_client.get_segment_reconstruction(
            file_hash=self.file_hash,
            start=seg.start,
            end=seg.end,
        )

        logger.debug(
            f"[SegmentedReconstructor] 段 {seg.index} reconstruction: "
            f"{len(recon.terms)} terms, {len(recon.fetch_info)} xorbs"
        )

        # 2. 下载和重建数据到内存
        segment_data = self._download_and_assemble_segment(seg, recon)

        # 3. 发送到write_queue
        self._write_queue.put((seg.start, segment_data))

        # 4. 标记完成并保存 checkpoint
        self._mark_segment_completed(seg)

        logger.info(f"[SegmentedReconstructor] [并行] 段 {seg.index} 完成: {len(segment_data)} bytes")

    def _stream_assembly_to_temp(self, seg: SegmentInfo, recon, seg_temp: Path) -> None:
        """用 ChunkAssembler 流式组装段数据到临时文件。

        Args:
            seg: 分段信息
            recon: segment 的 reconstruction 响应
            seg_temp: 临时文件路径
        """
        progress_tracker = ProgressTracker(callback=self.progress_callback)
        # 使用文件总大小（而非段大小）作为进度条总量，这样进度百分比是文件级别的
        progress_tracker.set_total_bytes(self.file_size)
        # 已完成段的偏移量作为初始已组装字节数
        progress_tracker.increment_assembled(seg.offset)

        assembler = ChunkAssembler(
            temp_dir=self.temp_dir,
            max_memory_mb=200,
            prefetch_low_mb=48,
            prefetch_high_mb=192,
            max_concurrent_downloads=self.max_workers,
        )
        cache_adapter = ChunkCacheAdapter(
            chunk_cache=self.chunk_cache,
            xorb_cache=self.xorb_cache,
        )

        # 创建 term 级 checkpoint manager（支持段内断点续传）
        ckpt_path = self.temp_dir / f"seg_{seg.index}.term_ckpt.json"
        checkpoint_manager = CheckpointManager(ckpt_path)

        assembler.assemble_file_with_prefetch(
            recon=recon,
            cas_client=self.cas_client,
            output_path=seg_temp,
            file_hash=self.file_hash,
            progress_tracker=progress_tracker,
            cache_adapter=cache_adapter,
            stop_event=self._stop_event,
            checkpoint_manager=checkpoint_manager,
        )

    def _process_segment(self, seg: SegmentInfo) -> None:
        """处理单个分段（顺序模式，流式写入，无全量内存中转）。

        Args:
            seg: 分段信息
        """
        logger.info(
            f"[SegmentedReconstructor] 处理段 {seg.index + 1}/{len(self.segments)}: "
            f"offset={seg.start}, size={seg.size}"
        )

        recon = self.cas_client.get_segment_reconstruction(
            file_hash=self.file_hash,
            start=seg.start,
            end=seg.end,
        )

        logger.debug(
            f"[SegmentedReconstructor] 段 {seg.index} reconstruction: "
            f"{len(recon.terms)} terms, {len(recon.fetch_info)} xorbs"
        )

        # 流式组装到临时文件（水位线控制内存，不加载全量 xorb）
        seg_temp = self.temp_dir / f"seg_{seg.index}.tmp"
        try:
            self._stream_assembly_to_temp(seg, recon, seg_temp)

            # 流式复制到最终文件（不加载整个 segment 到内存）
            with open(self.output_path, 'r+b') as f:
                f.seek(seg.start)
                with open(seg_temp, 'rb') as src:
                    shutil.copyfileobj(src, f)

        finally:
            if seg_temp.exists():
                seg_temp.unlink()

        logger.info(f"[SegmentedReconstructor] 段 {seg.index} 完成: {seg.size} bytes")

    def _download_and_assemble_segment(self, seg: SegmentInfo, recon) -> bytes:
        """下载并组装segment数据（并行模式用，返回 bytes 用于 write queue）。

        使用 ChunkAssembler 的预取水位线机制流式处理，
        避免将所有 xorb 同时加载到内存。

        Args:
            seg: 分段信息
            recon: segment的reconstruction响应

        Returns:
            组装后的segment数据（bytes）
        """
        seg_temp = self.temp_dir / f"seg_{seg.index}.tmp"

        try:
            self._stream_assembly_to_temp(seg, recon, seg_temp)
            return seg_temp.read_bytes()

        finally:
            if seg_temp.exists():
                seg_temp.unlink()
                logger.debug(f"[SegmentedReconstructor] 清理临时文件: {seg_temp}")

    def _mark_segment_completed(self, seg: SegmentInfo) -> None:
        """标记段为已完成并保存 checkpoint。

        Args:
            seg: 分段信息
        """
        with self._lock:
            seg.completed = True
            self.completed_segments.append({
                'index': seg.index,
                'start': seg.start,
                'end': seg.end,
                'size': seg.size,
            })
            self.completed_set.add((seg.start, seg.end))

            # 保存 checkpoint
            self.segment_checkpoint.save(
                file_hash=self.file_hash,
                completed_segments=self.completed_segments,
            )

    def stop(self) -> None:
        """停止重建（触发中断）。"""
        logger.warning("[SegmentedReconstructor] 触发停止信号")
        self._stop_event.set()

    def cleanup(self) -> None:
        """清理临时文件和资源。"""
        try:
            # 清理临时目录
            if self.temp_dir and self.temp_dir.exists():
                for seg_checkpoint in self.temp_dir.glob(f"{self.output_path.name}.seg*.json"):
                    seg_checkpoint.unlink()

                if not any(self.temp_dir.iterdir()):
                    self.temp_dir.rmdir()
                    logger.info(f"[SegmentedReconstructor] 清理临时目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"[SegmentedReconstructor] 清理失败: {e}")
