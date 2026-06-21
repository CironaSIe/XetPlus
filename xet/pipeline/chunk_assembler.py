"""数据组装器 - 解压 xorb 并组装最终文件。

负责解压 xorb、按 terms 顺序拼接数据、流式写入目标文件。
基于 ~/xet.py/xet/reconstructor.py 的实现逻辑。

支持两种模式：
1. 批量模式（已弃用）：先下载所有 xorb，再按需解压 - 大文件会 OOM
2. 预取模式（推荐）：按需下载和解压，水位线控制 - 内存占用可控
"""
import logging
import threading
from pathlib import Path
from typing import Dict, Optional, List
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, Future

from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.progress_tracker import ProgressTracker
from xet.pipeline.xorb_disk_cache import XorbDiskCache
from xet.pipeline.completion_rate_estimator import CompletionRateEstimator

logger = logging.getLogger(__name__)


# 导入辅助方法
from xet.pipeline.chunk_assembler_helpers import PrefetchHelpers


class ChunkAssembler(PrefetchHelpers):
    """文件数据组装器（支持预取机制）。

    职责：
    - 按需下载和解压 xorb（预取机制）
    - 按 terms 顺序提取数据片段
    - 流式写入目标文件
    - 水位线控制内存占用

    Attributes:
        temp_dir: 临时目录（用于存储中间文件，如果需要）
        max_memory_mb: 内存限制（MB）
        prefetch_low_mb: 低水位线（MB，默认 48）
        prefetch_high_mb: 高水位线（MB，默认 192）
    """

    def __init__(
        self,
        temp_dir: Optional[Path] = None,
        max_memory_mb: int = 200,
        prefetch_low_mb: int = 48,
        prefetch_high_mb: int = 192,
        prefetch_max: int = 8,
        checkpoint_interval: int = 10,
        max_concurrent_downloads: int = 4,
        buffer_mb: int = 32,
    ):
        """初始化数据组装器。

        Args:
            temp_dir: 临时目录路径
            max_memory_mb: 解压缓冲区内存限制（MB，默认 200）
            prefetch_low_mb: 预取低水位线（MB，默认 48）
            prefetch_high_mb: 预取高水位线（MB，默认 192）
            prefetch_max: 单次最多预取 xorb 数量（默认 8）
            checkpoint_interval: 每 N terms 保存 checkpoint（默认 10）
            max_concurrent_downloads: 最大并发下载数
            buffer_mb: 写入缓冲区大小（MB，默认 32）
        """
        self.temp_dir = temp_dir
        self.max_memory_mb = max_memory_mb
        self.prefetch_low_mb = prefetch_low_mb
        self.prefetch_high_mb = prefetch_high_mb
        self.prefetch_max = prefetch_max
        self.checkpoint_interval = checkpoint_interval
        self.max_concurrent_downloads = max_concurrent_downloads
        self.buffer_mb = buffer_mb

        # 内存缓存：{xorb_hash: XorbBlockData}
        self._xorb_cache: OrderedDict = OrderedDict()
        # 下载中的 futures：{xorb_hash: Future}
        self._download_futures: Dict[str, Future] = {}
        # 下载线程池
        self._download_executor: Optional[ThreadPoolExecutor] = None
        # 停止事件
        self._stop_event = threading.Event()
        # 完成速率估算器（用于自适应预取）
        self._rate_estimator = CompletionRateEstimator(half_life=3)

        if self.temp_dir:
            self.temp_dir.mkdir(parents=True, exist_ok=True)

    def assemble_file(
        self,
        recon: QueryReconstructionResponse,
        xorb_data_map: Dict[str, bytes],
        output_path: Path,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> None:
        """组装最终文件（兼容旧接口，已弃用）。

        此方法保留用于向后兼容，但不推荐使用。
        使用预分配的 xorb_data_map 可能导致大文件内存溢出。

        推荐使用 assemble_file_with_prefetch() 方法。

        Args:
            recon: Reconstruction 响应
            xorb_data_map: {xorb_hash: compressed_xorb_data} 映射
            output_path: 输出文件路径
            progress_tracker: 进度跟踪器（可选）
        """
        logger.warning(
            "[ChunkAssembler] 使用旧的批量模式（已弃用），大文件可能 OOM。"
            "推荐使用 assemble_file_with_prefetch() 方法。"
        )
        self._assemble_file_batched(recon, xorb_data_map, output_path, progress_tracker)

    def assemble_file_with_prefetch(
        self,
        recon: QueryReconstructionResponse,
        cas_client,
        output_path: Path,
        file_hash: str,
        progress_tracker: Optional[ProgressTracker] = None,
        cache_adapter = None,
        stop_event: Optional[threading.Event] = None,
        checkpoint_manager = None,
        parallel_write: bool = False,
    ) -> None:
        """组装最终文件（预取模式，推荐）。

        按 term 顺序处理，按需下载和解压 xorb，水位线控制内存占用。

        Args:
            recon: Reconstruction 响应
            cas_client: CAS 客户端（用于下载 xorb）
            output_path: 输出文件路径
            file_hash: 文件 MerkleHash（用于日志）
            progress_tracker: 进度跟踪器（可选）
            cache_adapter: 缓存适配器（可选）
            stop_event: 停止事件（用于中断）
            checkpoint_manager: Checkpoint 管理器（可选，支持 term 级断点续传）
            parallel_write: 是否启用并行批量写入（默认 False）

        Raises:
            ValueError: 数据缺失或格式错误
            IOError: 文件写入失败
            KeyboardInterrupt: 用户中断
        """
        logger.info(
            f"[ChunkAssembler] 开始组装文件（预取模式）: {output_path}, "
            f"内存限制: {self.max_memory_mb}MB, "
            f"水位线: {self.prefetch_low_mb}-{self.prefetch_high_mb}MB, "
            f"并行写入: {'启用' if parallel_write else '禁用'}"
        )

        if stop_event:
            self._stop_event = stop_event

        try:
            # 初始化下载线程池
            self._download_executor = ThreadPoolExecutor(
                max_workers=self.max_concurrent_downloads,
                thread_name_prefix="xorb-downloader"
            )

            # 按 term 顺序处理
            self._assemble_with_prefetch(
                recon, cas_client, output_path, file_hash,
                progress_tracker, cache_adapter, checkpoint_manager
            )

        finally:
            # 清理资源
            if self._download_executor:
                self._download_executor.shutdown(wait=True)
                self._download_executor = None
            self._xorb_cache.clear()
            self._download_futures.clear()

    def _assemble_file_batched(
        self,
        recon: QueryReconstructionResponse,
        xorb_data_map: Dict[str, bytes],
        output_path: Path,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> None:
        """分批模式：按批次解压 xorb，控制内存占用。"""
        # 1. 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 2. 按 term 顺序构建 xorb 引用顺序
        unique_xorb_hashes = []
        xorb_order = {}  # {xorb_hash: first_term_index}
        for idx, term in enumerate(recon.terms):
            if term.hash not in xorb_order:
                xorb_order[term.hash] = idx
                unique_xorb_hashes.append(term.hash)

        logger.info(
            f"[ChunkAssembler] 分批处理: {len(unique_xorb_hashes)} 个唯一 xorb, "
            f"内存限制 {self.max_memory_mb}MB"
        )

        # 3. 分批解压和写入
        total_written = 0
        max_memory_bytes = self.max_memory_mb * 1024 * 1024

        with open(output_path, 'wb') as f:
            current_batch = {}  # {xorb_hash: XorbBlockData}
            current_memory = 0
            term_idx = 0

            for term in recon.terms:
                # 检查是否需要加载新的 xorb
                if term.hash not in current_batch:
                    # 获取 xorb 的压缩数据
                    if term.hash not in xorb_data_map:
                        raise ValueError(
                            f"[ChunkAssembler] Term #{term_idx} 引用的 xorb 不在数据映射中: {term.hash[:16]}..."
                        )

                    compressed_data = xorb_data_map[term.hash]

                    # 估算解压后大小
                    # 实际测试：压缩比通常 2-3 倍，这里保守估计 2.5 倍
                    estimated_size = len(compressed_data) * 2.5

                    # 如果当前内存 + 新 xorb 超限，清理旧的
                    while current_memory + estimated_size > max_memory_bytes and current_batch:
                        # 找到最早不再需要的 xorb
                        xorb_to_remove = None
                        for xorb_hash in list(current_batch.keys()):
                            # 检查后续 term 是否还需要这个 xorb
                            needed = any(
                                t.hash == xorb_hash
                                for t in recon.terms[term_idx:]
                            )
                            if not needed:
                                xorb_to_remove = xorb_hash
                                break

                        if xorb_to_remove:
                            removed_size = len(current_batch[xorb_to_remove].data)
                            del current_batch[xorb_to_remove]
                            current_memory -= removed_size
                            logger.debug(
                                f"[ChunkAssembler] 释放 xorb {xorb_to_remove[:16]}... "
                                f"({removed_size / 1024 / 1024:.1f}MB), "
                                f"当前内存: {current_memory / 1024 / 1024:.1f}MB"
                            )
                        else:
                            # 没有可释放的，只能继续
                            break

                    # 解压新的 xorb
                    xorb_data = self._decompress_single_xorb(
                        term.hash, compressed_data, recon
                    )
                    current_batch[term.hash] = xorb_data
                    current_memory += len(xorb_data.data)

                    logger.debug(
                        f"[ChunkAssembler] 加载 xorb {term.hash[:16]}... "
                        f"({len(xorb_data.data) / 1024 / 1024:.1f}MB), "
                        f"当前内存: {current_memory / 1024 / 1024:.1f}MB, "
                        f"缓存: {len(current_batch)} 个 xorb"
                    )

                # 从缓存中提取数据并写入
                xorb_data = current_batch[term.hash]
                chunk_offset_dict = dict(xorb_data.chunk_offsets)

                start_chunk_idx = term.range.start
                start_byte = chunk_offset_dict.get(start_chunk_idx)

                if start_byte is None:
                    raise ValueError(
                        f"[ChunkAssembler] Chunk {start_chunk_idx} 未在 xorb {term.hash[:16]}... 中找到"
                    )

                end_byte = start_byte + term.unpacked_length

                if end_byte > len(xorb_data.data):
                    raise ValueError(
                        f"[ChunkAssembler] Term #{term_idx} 数据范围越界: "
                        f"start={start_byte}, end={end_byte}, data_len={len(xorb_data.data)}"
                    )

                segment = xorb_data.data[start_byte:end_byte]

                # 第一个 term 需要跳过 offset_into_first_range
                if term_idx == 0 and recon.offset_into_first_range > 0:
                    offset = recon.offset_into_first_range
                    if offset >= len(segment):
                        raise ValueError(
                            f"[ChunkAssembler] offset_into_first_range ({offset}) >= "
                            f"第一个 term 长度 ({len(segment)})"
                        )
                    segment = segment[offset:]
                    logger.debug(
                        f"[ChunkAssembler] 第一个 term 跳过 offset: {offset} bytes"
                    )

                f.write(segment)
                total_written += len(segment)

                if progress_tracker:
                    progress_tracker.increment_assembled(len(segment))

                term_idx += 1

                if term_idx % 100 == 0:
                    logger.debug(
                        f"[ChunkAssembler] 处理进度: {term_idx}/{len(recon.terms)} terms, "
                        f"内存: {current_memory / 1024 / 1024:.1f}MB"
                    )

        logger.info(
            f"[ChunkAssembler] 文件组装完成: {output_path} "
            f"({total_written} bytes, {len(recon.terms)} terms)"
        )


    def _decompress_single_xorb(
        self,
        xorb_hash: str,
        merged_data: bytes,
        recon: QueryReconstructionResponse,
    ) -> "XorbBlockData":
        """解压单个 xorb（用于分批处理）。

        Args:
            xorb_hash: xorb 哈希值
            merged_data: 压缩的 xorb 数据
            recon: Reconstruction 响应（包含 fetch_info）

        Returns:
            XorbBlockData 对象

        Raises:
            ImportError: lz4 或 blake3 未安装
            RuntimeError: 解压失败
        """
        try:
            from xet.storage.xorb_deserializer import XorbDeserializer, XorbBlockData
        except ImportError as e:
            raise ImportError(
                "[ChunkAssembler] 需要 lz4 和 blake3 库: pip install lz4 blake3"
            ) from e

        # 获取该 xorb 的所有 segments（按 chunk_range.start 排序）
        if xorb_hash not in recon.fetch_info:
            raise ValueError(
                f"[ChunkAssembler] Xorb {xorb_hash[:16]}... 没有 fetch_info"
            )

        fetch_infos = sorted(
            recon.fetch_info[xorb_hash],
            key=lambda fi: fi.chunk_range.start
        )

        # 分别反序列化每个 segment 并合并
        all_chunk_offsets = []
        all_data = bytearray()
        data_offset = 0

        for seg_idx, fi in enumerate(fetch_infos):
            # 提取这个 segment 的数据
            segment_byte_length = fi.url_range.length()
            segment_data = merged_data[data_offset:data_offset + segment_byte_length]
            data_offset += segment_byte_length

            # 反序列化这个 segment
            try:
                segment_xorb = XorbDeserializer.deserialize(segment_data)
            except Exception as e:
                raise RuntimeError(
                    f"[ChunkAssembler] 解压 xorb {xorb_hash[:16]}... "
                    f"segment {seg_idx} 失败: {e}"
                ) from e

            # 合并 chunk_offsets
            base_chunk_idx = fi.chunk_range.start
            base_data_offset = len(all_data)

            for local_chunk_idx, local_byte_offset in segment_xorb.chunk_offsets:
                global_chunk_idx = base_chunk_idx + local_chunk_idx
                global_byte_offset = base_data_offset + local_byte_offset
                all_chunk_offsets.append((global_chunk_idx, global_byte_offset))

            # 追加数据
            all_data.extend(segment_xorb.data)

        # 创建合并后的 XorbBlockData
        return XorbBlockData(
            chunk_offsets=all_chunk_offsets,
            data=bytes(all_data)
        )

    def _assemble_with_prefetch(
        self,
        recon: QueryReconstructionResponse,
        cas_client,
        output_path: Path,
        file_hash: str,
        progress_tracker: Optional[ProgressTracker],
        cache_adapter,
        checkpoint_manager=None,
    ) -> None:
        """预取模式：按需下载和解压，水位线控制内存。"""
        # 1. 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 2. 构建 xorb 引用顺序（按 term 顺序）
        xorb_order = []  # [(xorb_hash, first_term_idx)]
        seen_xorbs = set()
        for idx, term in enumerate(recon.terms):
            if term.hash not in seen_xorbs:
                xorb_order.append((term.hash, idx))
                seen_xorbs.add(term.hash)

        logger.info(
            f"[ChunkAssembler] 预取模式: {len(recon.terms)} terms, "
            f"{len(xorb_order)} 唯一 xorb"
        )

        # 3. 尝试从磁盘缓存加载
        if cache_adapter and cache_adapter.enabled:
            self._load_from_disk_cache(recon, cache_adapter)

        # 4. 检查 checkpoint，确定起始 term
        start_term_idx = 0
        if checkpoint_manager:
            checkpoint = checkpoint_manager._cache
            if checkpoint and checkpoint.file_hash == file_hash:
                start_term_idx = checkpoint.last_term_index + 1
                if start_term_idx > 0:
                    # 计算已写入字节数
                    bytes_written = 0
                    for i in range(start_term_idx):
                        term = recon.terms[i]
                        if i == 0:
                            bytes_written += max(0, term.unpacked_length - recon.offset_into_first_range)
                        else:
                            bytes_written += term.unpacked_length

                    logger.info(
                        f"[ChunkAssembler] 📍 发现有效断点! "
                        f"将从 Term #{start_term_idx} 继续 (共 {len(recon.terms)} terms), "
                        f"已写入: {bytes_written / 1024 / 1024:.1f} MB"
                    )

        # 5. 按 term 顺序处理并写入
        total_written = 0
        max_memory_bytes = self.max_memory_mb * 1024 * 1024
        low_watermark = self.prefetch_low_mb * 1024 * 1024
        high_watermark = self.prefetch_high_mb * 1024 * 1024

        # 记录开始时间（用于完成统计）
        import time
        start_time = time.time()

        # 使用 .part 文件显示真实进度
        part_path = output_path.with_suffix(output_path.suffix + ".part")

        # 并行写入模式
        if parallel_write:
            self._assemble_with_parallel_write(
                recon, cas_client, part_path, output_path, file_hash,
                start_term_idx, progress_tracker, cache_adapter,
                stop_event, checkpoint_manager, start_time
            )
        else:
            # 顺序写入模式（现有逻辑）
            self._assemble_with_sequential_write(
                recon, cas_client, part_path, output_path, file_hash,
                start_term_idx, progress_tracker, cache_adapter,
                stop_event, checkpoint_manager, start_time
            )

    def _assemble_with_sequential_write(
        self,
        recon,
        cas_client,
        part_path,
        output_path,
        file_hash,
        start_term_idx,
        progress_tracker,
        cache_adapter,
        stop_event,
        checkpoint_manager,
        start_time,
    ):
        """顺序写入模式（现有逻辑）。"""
        low_watermark = self.prefetch_low_mb * 1024 * 1024
        high_watermark = self.prefetch_high_mb * 1024 * 1024
        total_written = 0

        try:
            with open(part_path, 'wb') as f:
                for term_idx, term in enumerate(recon.terms):
                    # 跳过已完成的 terms（checkpoint 恢复）
                    if term_idx < start_term_idx:
                        continue

                    # 检查中断
                if self._stop_event.is_set():
                    logger.info("[ChunkAssembler] 检测到中断信号")
                    raise KeyboardInterrupt("用户中断")

                # 确保 xorb 已加载（触发下载/解压）
                self._ensure_xorb_ready(
                    term.hash, recon, cas_client, file_hash, cache_adapter, progress_tracker
                )

                # 检查水位线，预取后续 xorb
                current_cache_bytes = sum(len(x.data) for x in self._xorb_cache.values())
                if current_cache_bytes < low_watermark:
                    self._prefetch_upcoming_xorbs(
                        term_idx, recon, cas_client, file_hash,
                        cache_adapter, high_watermark, progress_tracker
                    )

                # 从 xorb 提取数据
                xorb_data = self._xorb_cache[term.hash]
                chunk_offset_dict = dict(xorb_data.chunk_offsets)

                start_chunk_idx = term.range.start
                start_byte = chunk_offset_dict.get(start_chunk_idx)

                if start_byte is None:
                    raise ValueError(
                        f"[ChunkAssembler] Chunk {start_chunk_idx} 未在 xorb {term.hash[:16]}... 中找到"
                    )

                end_byte = start_byte + term.unpacked_length

                if end_byte > len(xorb_data.data):
                    raise ValueError(
                        f"[ChunkAssembler] Term #{term_idx} 数据范围越界: "
                        f"start={start_byte}, end={end_byte}, data_len={len(xorb_data.data)}"
                    )

                segment = xorb_data.data[start_byte:end_byte]

                # 第一个 term 需要跳过 offset_into_first_range
                if term_idx == 0 and recon.offset_into_first_range > 0:
                    offset = recon.offset_into_first_range
                    if offset >= len(segment):
                        raise ValueError(
                            f"[ChunkAssembler] offset_into_first_range ({offset}) >= "
                            f"第一个 term 长度 ({len(segment)})"
                        )
                    segment = segment[offset:]

                # 写入文件
                f.write(segment)
                total_written += len(segment)

                # 更新完成速率估算器
                self._rate_estimator.update(len(segment))

                if progress_tracker:
                    progress_tracker.increment_assembled(len(segment))
                    progress_tracker.increment_terms(1)

                # Term 级 checkpoint（使用配置的保存间隔）
                if checkpoint_manager:
                    checkpoint_manager.mark_term_completed(
                        file_hash=file_hash,
                        term_idx=term_idx,
                        xorb_hash=term.hash,
                        save_interval=self.checkpoint_interval
                    )

                # 检查是否可以释放 xorb
                if not self._is_xorb_needed_later(term.hash, term_idx, recon):
                    if term.hash in self._xorb_cache:
                        released_size = len(self._xorb_cache[term.hash].data)
                        del self._xorb_cache[term.hash]
                        logger.debug(
                            f"[ChunkAssembler] 释放 xorb {term.hash[:16]}... "
                            f"({released_size / 1024 / 1024:.1f}MB)"
                        )

                # 定期日志
                if (term_idx + 1) % 100 == 0:
                    cache_mb = sum(len(x.data) for x in self._xorb_cache.values()) / 1024 / 1024
                    logger.debug(
                        f"[ChunkAssembler] 进度: {term_idx + 1}/{len(recon.terms)} terms, "
                        f"缓存: {cache_mb:.1f}MB, "
                        f"已写入: {total_written / 1024 / 1024:.1f}MB"
                    )

            # 写入完成后重命名 .part -> 目标文件
            part_path.rename(output_path)

            # 完成统计
            duration = time.time() - start_time
            speed_mbps = (total_written / max(duration, 0.001)) / (1024 * 1024)
            unique_xorbs = len(set(t.hash for t in recon.terms))

            logger.info(
                f"[ChunkAssembler] ✅ 下载完成统计:\n"
                f"  - 文件: {output_path.name}\n"
                f"  - 大小: {total_written / 1024 / 1024:.2f} MB\n"
                f"  - Terms: {len(recon.terms)} 个\n"
                f"  - Xorbs: {unique_xorbs} 个\n"
                f"  - 耗时: {duration:.1f} 秒\n"
                f"  - 速度: {speed_mbps:.2f} MB/s"
            )

        except Exception:
            # 异常时清理 .part 文件
            if part_path.exists():
                try:
                    part_path.unlink()
                    logger.debug(f"[ChunkAssembler] 清理 .part 文件: {part_path}")
                except Exception as e:
                    logger.warning(f"[ChunkAssembler] 清理 .part 文件失败: {e}")
            raise

    def _assemble_with_parallel_write(
        self,
        recon,
        cas_client,
        part_path,
        output_path,
        file_hash,
        start_term_idx,
        progress_tracker,
        cache_adapter,
        stop_event,
        checkpoint_manager,
        start_time,
    ):
        """并行写入模式（使用 GlobalWriter）。"""
        from xet.pipeline.global_writer import GlobalWriter

        low_watermark = self.prefetch_low_mb * 1024 * 1024
        high_watermark = self.prefetch_high_mb * 1024 * 1024

        # 创建 GlobalWriter
        # 根据 buffer_mb 计算 batch_size
        # buffer_mb 越大，可以容纳更多的写入项
        # 假设平均每个写入项约 4-8 MB，batch_size = buffer_mb / 4
        batch_size = max(4, self.buffer_mb // 4)

        writer = GlobalWriter(
            output_path=part_path,
            batch_size=batch_size,
            progress_callback=lambda n: progress_tracker.increment_assembled(n) if progress_tracker else None,
            stop_event=stop_event,
        )
        writer.start()

        try:
            # 计算文件偏移量
            current_offset = 0
            if start_term_idx == 0 and recon.offset_into_first_range > 0:
                # 第一个 term 需要跳过 offset
                current_offset = -recon.offset_into_first_range

            for term_idx, term in enumerate(recon.terms):
                # 跳过已完成的 terms（checkpoint 恢复）
                if term_idx < start_term_idx:
                    # 计算偏移量（即使跳过也要累加）
                    if term_idx == 0 and recon.offset_into_first_range > 0:
                        current_offset += max(0, term.unpacked_length - recon.offset_into_first_range)
                    else:
                        current_offset += term.unpacked_length
                    continue

                # 检查中断
                if self._stop_event.is_set():
                    logger.info("[ChunkAssembler] 检测到中断信号")
                    raise KeyboardInterrupt("用户中断")

                # 确保 xorb 已加载（触发下载/解压）
                self._ensure_xorb_ready(
                    term.hash, recon, cas_client, file_hash, cache_adapter, progress_tracker
                )

                # 检查水位线，预取后续 xorb
                current_cache_bytes = sum(len(x.data) for x in self._xorb_cache.values())
                if current_cache_bytes < low_watermark:
                    self._prefetch_upcoming_xorbs(
                        term_idx, recon, cas_client, file_hash,
                        cache_adapter, high_watermark, progress_tracker
                    )

                # 从 xorb 提取数据
                xorb_data = self._xorb_cache[term.hash]
                chunk_offset_dict = dict(xorb_data.chunk_offsets)

                start_chunk_idx = term.range.start
                start_byte = chunk_offset_dict.get(start_chunk_idx)

                if start_byte is None:
                    raise ValueError(
                        f"[ChunkAssembler] Chunk {start_chunk_idx} 未在 xorb {term.hash[:16]}... 中找到"
                    )

                end_byte = start_byte + term.unpacked_length

                if end_byte > len(xorb_data.data):
                    raise ValueError(
                        f"[ChunkAssembler] Term #{term_idx} 数据范围越界: "
                        f"start={start_byte}, end={end_byte}, data_len={len(xorb_data.data)}"
                    )

                segment = xorb_data.data[start_byte:end_byte]

                # 第一个 term 需要跳过 offset_into_first_range
                if term_idx == 0 and recon.offset_into_first_range > 0:
                    offset = recon.offset_into_first_range
                    if offset >= len(segment):
                        raise ValueError(
                            f"[ChunkAssembler] offset_into_first_range ({offset}) >= "
                            f"第一个 term 长度 ({len(segment)})"
                        )
                    segment = segment[offset:]

                # 计算写入偏移量
                write_offset = max(0, current_offset)

                # 放入写队列（异步）
                writer.put(write_offset, segment)

                # 更新偏移量
                current_offset += len(segment)

                # 更新完成速率估算器
                self._rate_estimator.update(len(segment))

                # Term 计数（进度由 GlobalWriter 回调更新）
                if progress_tracker:
                    progress_tracker.increment_terms(1)

                # Term 级 checkpoint
                if checkpoint_manager:
                    checkpoint_manager.mark_term_completed(
                        file_hash=file_hash,
                        term_idx=term_idx,
                        xorb_hash=term.hash,
                        save_interval=self.checkpoint_interval
                    )

                # 检查是否可以释放 xorb
                if not self._is_xorb_needed_later(term.hash, term_idx, recon):
                    if term.hash in self._xorb_cache:
                        released_size = len(self._xorb_cache[term.hash].data)
                        del self._xorb_cache[term.hash]
                        logger.debug(
                            f"[ChunkAssembler] 释放 xorb {term.hash[:16]}... "
                            f"({released_size / 1024 / 1024:.1f}MB)"
                        )

                # 定期日志
                if (term_idx + 1) % 100 == 0:
                    cache_mb = sum(len(x.data) for x in self._xorb_cache.values()) / 1024 / 1024
                    logger.debug(
                        f"[ChunkAssembler] 进度: {term_idx + 1}/{len(recon.terms)} terms, "
                        f"缓存: {cache_mb:.1f}MB"
                    )

            # 完成写入，等待 writer 线程
            total_written = writer.finish()

            # 重命名 .part -> 目标文件
            part_path.rename(output_path)

            # 完成统计
            duration = time.time() - start_time
            speed_mbps = (total_written / max(duration, 0.001)) / (1024 * 1024)
            unique_xorbs = len(set(t.hash for t in recon.terms))

            logger.info(
                f"[ChunkAssembler] ✅ 下载完成统计 (并行写入):\n"
                f"  - 文件: {output_path.name}\n"
                f"  - 大小: {total_written / 1024 / 1024:.2f} MB\n"
                f"  - Terms: {len(recon.terms)} 个\n"
                f"  - Xorbs: {unique_xorbs} 个\n"
                f"  - 耗时: {duration:.1f} 秒\n"
                f"  - 速度: {speed_mbps:.2f} MB/s"
            )

        except Exception:
            # 异常时清理 .part 文件
            if part_path.exists():
                try:
                    part_path.unlink()
                    logger.debug(f"[ChunkAssembler] 清理 .part 文件: {part_path}")
                except Exception as e:
                    logger.warning(f"[ChunkAssembler] 清理 .part 文件失败: {e}")
            raise

