"""数据组装器 - 解压 xorb 并组装最终文件。

负责解压 xorb、按 terms 顺序拼接数据、流式写入目标文件。
基于 ~/xet.py/xet/reconstructor.py 的实现逻辑。

支持两种模式：
1. 批量模式（已弃用）：先下载所有 xorb，再按需解压 - 大文件会 OOM
2. 预取模式（推荐）：按需下载和解压，水位线控制 - 内存占用可控
"""
import hashlib
import logging
import os
import threading
import time
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
        # 文件系统同步：每 N term 做一次 fsync（默认 5 term ≈ 几百 KB 粒度）
        self.fsync_interval: int = 5
        self._term_write_count: int = 0

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
        output_offset: int = 0,
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
                progress_tracker, cache_adapter, checkpoint_manager,
                stop_event, parallel_write, output_offset
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
        """分批模式：按批次解压 xorb，控制内存占用——已弃用。

        此方法接收全量 xorb_data_map，大文件时可能导致 OOM。
        推荐使用 assemble_file_with_prefetch() 流式方案。
        """
        logger.warning(
            "[ChunkAssembler] _assemble_file_batched 已弃用，"
            "大文件可能 OOM。请使用 assemble_file_with_prefetch()。"
        )
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
                            removed_size = current_batch[xorb_to_remove].memory_footprint()
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
                    current_memory += xorb_data.memory_footprint()

                    logger.debug(
                        f"[ChunkAssembler] 加载 xorb {term.hash[:16]}... "
                        f"({xorb_data.memory_footprint() / 1024 / 1024:.1f}MB), "
                        f"当前内存: {current_memory / 1024 / 1024:.1f}MB, "
                        f"缓存: {len(current_batch)} 个 xorb"
                    )

                # 从缓存中提取数据并写入
                xorb_data = current_batch[term.hash]

                # xorb_data.chunk_offsets 存储的是 (全局chunk_id, byte_offset)
                # term.range 也使用全局 chunk ID，可以直接查询
                chunk_offsets_dict = dict(xorb_data.chunk_offsets)

                start_chunk = term.range.start
                end_chunk = term.range.end

                if start_chunk not in chunk_offsets_dict:
                    raise ValueError(
                        f"[ChunkAssembler] Term #{term_idx} start chunk {start_chunk} "
                        f"不在 chunk_offsets 中"
                    )

                start_byte = chunk_offsets_dict[start_chunk]
                end_byte = 0

                # end_chunk 可能不在 chunk_offsets 中（表示最后一个 chunk 之后）
                if end_chunk not in chunk_offsets_dict:
                    # 查找 end_chunk 之后的第一个 offset，或使用数据末尾
                    # chunk_offsets 是按全局 chunk ID 顺序的
                    sorted_chunks = sorted(chunk_offsets_dict.items())
                    found = False
                    for chunk_id, offset in sorted_chunks:
                        if chunk_id >= end_chunk:
                            end_byte = offset
                            found = True
                            break
                    if not found:
                        # end_chunk 超过所有已知 chunk，使用数据末尾
                        end_byte = xorb_data.data_size()
                else:
                    end_byte = chunk_offsets_dict[end_chunk]

                if end_byte > xorb_data.data_size():
                    raise ValueError(
                        f"[ChunkAssembler] Term #{term_idx} 数据范围越界: "
                        f"start={start_byte}, end={end_byte}, data_len={xorb_data.data_size()}"
                    )

                segment = xorb_data.extract_range(start_byte, end_byte)

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
    ):
        """解压单个 xorb（返回 StreamingXorbAccessor，不一次性全量解压）。

        Args:
            xorb_hash: xorb 哈希值
            merged_data: 压缩的 xorb 数据
            recon: Reconstruction 响应（包含 fetch_info）

        Returns:
            StreamingXorbAccessor 对象（按需解压）

        Raises:
            ImportError: lz4 或 blake3 库未安装
            RuntimeError: 解压失败
        """
        try:
            from xet.storage.xorb_deserializer import (
                XorbDeserializer, StreamingXorbAccessor,
            )
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

        # 根据段数量选择构造策略
        if len(fetch_infos) == 1:
            # 单段：扫描 header 获取索引，但保留全局 chunk ID 映射
            fi = fetch_infos[0]
            seg_data = merged_data  # 单段时 merged_data 就是整个 segment
            seg_xorb = XorbDeserializer.deserialize(seg_data)

            base_cid = fi.chunk_range.start
            chunk_offsets = [
                (base_cid + lcidx, lboff)
                for lcidx, lboff in seg_xorb.chunk_offsets
            ]
            return StreamingXorbAccessor(
                raw_bytes=merged_data,
                chunk_offsets=chunk_offsets,
            )
        else:
            # 多段：需要先全量解压以获取正确的全局 offsets
            # （多段合并场景下无法避免一次全量解压来建立全局映射）
            # 但这只影响 offset 映射，数据仍按需解压
            all_data_rebased = bytearray()
            rebased_offsets = []
            running_offset = 0

            fetch_infos_sorted = sorted(
                recon.fetch_info[xorb_hash],
                key=lambda fi: fi.chunk_range.start
            )
            pos = 0
            for fi in fetch_infos_sorted:
                seg_len = fi.url_range.length()
                seg_data = merged_data[pos:pos + seg_len]
                pos += seg_len
                seg_xorb = XorbDeserializer.deserialize(seg_data)

                base_cid = fi.chunk_range.start
                for lcidx, lboff in seg_xorb.chunk_offsets:
                    rebased_offsets.append((base_cid + lcidx, running_offset + lboff))
                all_data_rebased.extend(seg_xorb.data)
                running_offset += len(seg_xorb.data)

            # 多段模式下使用预解压构造（因为已经解压了）
            return StreamingXorbAccessor(
                raw_bytes=bytes(all_data_rebased),
                chunk_offsets=rebased_offsets,
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
        stop_event: Optional[threading.Event] = None,
        parallel_write: bool = False,
        output_offset: int = 0,
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
            # 防御性加载：如果调用方未显式 load()，此处尝试从文件恢复
            if checkpoint_manager._cache is None:
                checkpoint_manager.load(file_hash)

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
                    print(
                        f"\n  🔄 断点续传: 从 Term #{start_term_idx}/{len(recon.terms)} 继续"
                        f" ({bytes_written / 1024 / 1024:.1f} MB 已写入)"
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
            # 顺序写入模式
            if output_offset > 0:
                # 直写模式（模式②）：写入 output_path 的指定偏移，无 .part
                write_path = output_path
            else:
                # 标准模式：写入 .part 文件，完成后 rename
                write_path = part_path
            self._assemble_with_sequential_write(
                recon, cas_client, write_path, output_path, file_hash,
                start_term_idx, progress_tracker, cache_adapter,
                stop_event, checkpoint_manager, start_time,
                output_offset=output_offset,
            )

    @staticmethod
    def _verify_resume_terms(part_path, recon, offset_into_first,
                             per_term_hashes, expected_start_term_idx,
                             logger) -> int:
        """续传时校验已写入文件中的 term 数据完整性。

        从最后一个已完成的 term 开始，验证其 SHA256 与 checkpoint 记录一致。
        如果最后 term 损坏，向前回溯找到第一个完好的 term 作为续传起点。

        Args:
            part_path: .part 文件路径
            recon: reconstruction 数据（含 terms 列表）
            offset_into_first: 第一个 term 的偏移量
            per_term_hashes: checkpoint 中存储的 {term_idx: TermHashRecord}
            expected_start_term_idx: checkpoint 记录的起始 term
            logger: logging 实例

        Returns:
            调整后的起始 term 索引（校验通过则不变，失败则回退）
        """
        if not part_path.exists() or not per_term_hashes:
            return expected_start_term_idx

        completed_indices = sorted(per_term_hashes.keys())
        if not completed_indices:
            return expected_start_term_idx

        logger.info(
            f"[ChunkAssembler] 续传校验: 检查全部 {len(completed_indices)} 个已完成 term "
            f"(#{completed_indices[0]}~#{completed_indices[-1]}), "
            f"目标起点 Term #{expected_start_term_idx}"
        )
        terms_to_check = completed_indices

        with open(part_path, 'rb') as f:
            for term_idx in reversed(terms_to_check):
                if term_idx >= expected_start_term_idx:
                    logger.info(
                        f"[ChunkAssembler] 续传校验: Term #{term_idx} >= "
                        f"目标起点 #{expected_start_term_idx}, 跳过"
                    )
                    continue
                record = per_term_hashes.get(term_idx)
                if not record:
                    logger.info(
                        f"[ChunkAssembler] 续传校验: Term #{term_idx} 无 hash 记录, 跳过"
                    )
                    continue

                try:
                    f.seek(record.file_offset)
                    data = f.read(record.unpacked_length)
                    if len(data) != record.unpacked_length:
                        logger.warning(
                            f"[ChunkAssembler] 续传校验: Term #{term_idx} 文件不完整: "
                            f"期望 {record.unpacked_length} bytes, "
                            f"实际 {len(data)} bytes, 跳过继续检查"
                        )
                        continue

                    actual_hash = hashlib.sha256(data).hexdigest()
                    if actual_hash == record.sha256:
                        good_start = term_idx + 1
                        logger.warning(
                            f"[ChunkAssembler] 续传校验: Term #{term_idx} ✅ "
                            f"(offset={record.file_offset}, "
                            f"len={record.unpacked_length}) "
                            f"SHA256 匹配, 从 Term #{good_start} 继续"
                        )
                        return good_start
                    else:
                        logger.warning(
                            f"[ChunkAssembler] 续传校验: Term #{term_idx} ❌ "
                            f"(offset={record.file_offset}, "
                            f"len={record.unpacked_length}) "
                            f"SHA256 不匹配, 继续向前检查"
                        )

                except (OSError, IOError) as e:
                    logger.warning(
                        f"[ChunkAssembler] 续传校验: Term #{term_idx} 读取失败: {e}, "
                        f"跳过继续检查"
                    )
                    continue

        # 所有检查的 term 都损坏了，从第一个检查的 term 开始续传
        first_checked = min(terms_to_check)
        if first_checked < expected_start_term_idx:
            logger.warning(
                f"[ChunkAssembler] 续传校验: 已完成的 term 全部损坏, "
                f"回退到 Term #{first_checked}"
            )
            return first_checked
        logger.info(
            f"[ChunkAssembler] 续传校验: 所有检查项均无有效回退, "
            f"保持原起点 Term #{expected_start_term_idx}"
        )
        return expected_start_term_idx

    @staticmethod
    def _estimate_restart_term(recon, actual_file_size: int) -> int:
        """根据实际文件大小估算应从哪个 term 重新开始。

        当 .part 文件小于 checkpoint 记录的期望大小时（通常因为 OS 未 flush），
        遍历 term 累积大小，找到最后一个可能完整写入的 term。

        Args:
            recon: reconstruction 响应（含 terms 列表）
            actual_file_size: .part 文件的实际字节大小

        Returns:
            建议的起始 term 索引
        """
        accumulated = 0
        for i, term in enumerate(recon.terms):
            if i == 0:
                term_size = max(0, term.unpacked_length - recon.offset_into_first_range)
            else:
                term_size = term.unpacked_length

            if accumulated + term_size > actual_file_size:
                # 当前 term 无法完整放入已有文件，从前一个 term 开始
                return max(0, i)
            accumulated += term_size

        # 所有 term 都能放下（文件实际上足够大）
        return len(recon.terms)

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
        output_offset: int = 0,
    ):
        """顺序写入模式。"""
        low_watermark = self.prefetch_low_mb * 1024 * 1024
        high_watermark = self.prefetch_high_mb * 1024 * 1024
        total_written = 0

        # 计算从 checkpoint 恢复时已写入的字节数
        # 优先使用 checkpoint.confirmed_bytes（续传时直接记录的实际写入量）
        # 回退到从 terms 累加计算（兼容旧版 checkpoint）
        confirmed_bytes = 0
        bytes_already_written = 0
        if start_term_idx > 0 and checkpoint_manager and checkpoint_manager._cache:
            confirmed_bytes = checkpoint_manager._cache.confirmed_bytes

        if confirmed_bytes > 0:
            bytes_already_written = confirmed_bytes
            logger.debug(
                f"[ChunkAssembler] Checkpoint 恢复: 已确认写入 {confirmed_bytes} bytes "
                f"(从 confirmed_bytes), 将从 term {start_term_idx} 继续"
            )
        elif start_term_idx > 0:
            for i in range(start_term_idx):
                term = recon.terms[i]
                if i == 0:
                    bytes_already_written += max(0, term.unpacked_length - recon.offset_into_first_range)
                else:
                    bytes_already_written += term.unpacked_length
            logger.debug(
                f"[ChunkAssembler] Checkpoint 恢复: 已写入 {bytes_already_written} bytes "
                f"(从 terms 累加), 将从 term {start_term_idx} 继续"
            )

        need_truncate = False

        # === 续传 term 数据完整性校验 ===
        # 用 checkpoint 记录的 per-term SHA256 验证 .part 文件中已完成 term 的数据
        # 只对顺序写入模式生效（并行模式写入顺序不确定）
        if start_term_idx > 0 and part_path.exists() and checkpoint_manager:
            checkpoint = checkpoint_manager._cache
            if checkpoint and checkpoint.per_term_hashes:
                adjusted = self._verify_resume_terms(
                    part_path, recon, recon.offset_into_first_range,
                    checkpoint.per_term_hashes, start_term_idx, logger,
                )
                if adjusted < start_term_idx:
                    old_start = start_term_idx
                    start_term_idx = adjusted
                    # 重新计算 bytes_already_written
                    bytes_already_written = 0
                    for i in range(start_term_idx):
                        term = recon.terms[i]
                        if i == 0:
                            bytes_already_written += max(0, term.unpacked_length - recon.offset_into_first_range)
                        else:
                            bytes_already_written += term.unpacked_length
                    logger.info(
                        f"[ChunkAssembler] 续传校验后调整: "
                        f"Term #{old_start} → Term #{start_term_idx}, "
                        f"保留 {bytes_already_written / 1024 / 1024:.1f} MB, "
                        f"稍后截断文件清除损坏数据"
                    )
                    need_truncate = True

        try:
            # 根据 output_offset 和 checkpoint 选择文件打开模式
            existing_size = 0
            if output_offset > 0:
                # 直写模式（模式②）：写入 output_path 的指定偏移，无 .part 文件
                file_mode = 'r+b' if output_path.exists() else 'wb'
                # 续传时 seek 到 confirmed_bytes（在 line 850+ 处理）
            elif start_term_idx > 0 and part_path.exists():
                # 从 checkpoint 恢复：使用 r+b 模式追加，并验证现有文件大小
                file_mode = 'r+b'
                existing_size = part_path.stat().st_size
                # 容差：term 级大小计算与实际文件大小可能存在微小差异
                # （OS 块对齐、文件系统元数据等），差异 < 1MB 时视为一致
                if need_truncate:
                    # 校验已判定文件尾部数据损坏，直接截断，不进入大小比对
                    pass
                elif abs(existing_size - bytes_already_written) > 1024 * 1024:  # 差异超过 1MB 才触发恢复调整
                    if existing_size > bytes_already_written:
                        # 文件比预期大：说明上次运行写入了数据但 checkpoint 未保存
                        # （这是有效数据，不应截断！用实际文件大小作为恢复基准）
                        logger.info(
                            f"[ChunkAssembler] 文件比 Checkpoint 记录更大 "
                            f"(实际 {existing_size / 1024 / 1024:.1f} MB > "
                            f"期望 {bytes_already_written / 1024 / 1024:.1f} MB)，"
                            f"保留已有数据，从实际位置恢复"
                        )
                        bytes_already_written = existing_size
                        # 根据实际文件大小估算应从哪个 term 继续
                        estimated_restart = self._estimate_restart_term(
                            recon, existing_size
                        )
                        if estimated_restart < start_term_idx:
                            logger.info(
                                f"[ChunkAssembler] 根据实际文件大小调整: "
                                f"Term #{start_term_idx} → Term #{estimated_restart}"
                            )
                            start_term_idx = estimated_restart
                    else:
                        # 文件比预期小：部分数据未 flush 到磁盘或数据丢失。
                        # 使用 confirmed_bytes（如果有）作为更准确的基准。
                        if confirmed_bytes > 0 and existing_size >= confirmed_bytes:
                            # confirmed_bytes 是上次保存时确实在磁盘上的量，
                            # 只要文件大小 >= confirmed_bytes，数据就没丢。
                            # 但 bytes_already_written 可能高估（因 OS 缓存延迟）。
                            # 用实际文件大小重新估算起始 term。
                            logger.warning(
                                f"[ChunkAssembler] 文件大小 {existing_size / 1024 / 1024:.1f} MB "
                                f"介于 checkpoint 确认 {confirmed_bytes / 1024 / 1024:.1f} MB "
                                f"与期望 {bytes_already_written / 1024 / 1024:.1f} MB 之间，"
                                f"按实际大小估算续传位置"
                            )
                            estimated_restart = self._estimate_restart_term(
                                recon, existing_size
                            )
                            if estimated_restart < start_term_idx:
                                start_term_idx = estimated_restart
                                bytes_already_written = existing_size
                        else:
                            # 无 confirmed_bytes 或文件比 confirmed 还小：数据丢失
                            estimated_restart = self._estimate_restart_term(
                                recon, existing_size
                            )
                            if estimated_restart < start_term_idx:
                                old_start = start_term_idx
                                start_term_idx = estimated_restart
                                bytes_already_written = existing_size
                                if confirmed_bytes > 0:
                                    logger.warning(
                                        f"[ChunkAssembler] 数据丢失: "
                                        f"checkpoint 确认 {confirmed_bytes / 1024 / 1024:.1f} MB, "
                                        f"但文件只有 {existing_size / 1024 / 1024:.1f} MB. "
                                        f"回退到 Term #{start_term_idx}（原计划 #{old_start}）"
                                    )
                                else:
                                    logger.warning(
                                        f"[ChunkAssembler] 文件不完整: "
                                        f"期望 {bytes_already_written / 1024 / 1024:.1f} MB, "
                                        f"实际 {existing_size / 1024 / 1024:.1f} MB. "
                                        f"回退到 Term #{start_term_idx}（原计划 #{old_start}），"
                                        f"保留 {existing_size / 1024 / 1024:.1f} MB 已有数据"
                                    )
                else:
                    # 文件虽小但差距不大，可能是 OS 缓存延迟，仍尝试继续
                    logger.info(
                        f"[ChunkAssembler] 文件略小于预期 "
                        f"({existing_size}/{bytes_already_written})，"
                        f"尝试从 Term #{start_term_idx} 继续写入"
                    )
            else:
                # 全新下载：使用 wb 模式
                file_mode = 'wb'

            # 直写模式使用 output_path，.part 模式使用 part_path
            open_path = output_path if output_offset > 0 else part_path
            with open(open_path, file_mode) as f:
                if output_offset > 0:
                    # 直写模式：跳到目标偏移（续传时优先用 confirmed_bytes）
                    seek_pos = output_offset
                    if start_term_idx > 0:
                        if confirmed_bytes > 0:
                            seek_pos = confirmed_bytes
                        else:
                            for i in range(start_term_idx):
                                term = recon.terms[i]
                                if i == 0:
                                    seek_pos += max(0, term.unpacked_length - recon.offset_into_first_range)
                                else:
                                    seek_pos += term.unpacked_length
                    f.seek(seek_pos)
                    logger.debug(f"[ChunkAssembler] 直写模式: offset={output_offset}, seek_pos={seek_pos}")
                elif file_mode == 'r+b':
                    if need_truncate:
                        # 修正进度基线：baseline 之前包含了整个 .part 文件大小，
                        # truncate 后实际已确认数据变少，需同步调低
                        orig_baseline = progress_tracker.get_assembled_bytes() if progress_tracker else 0
                        logger.info(
                            f"[ChunkAssembler] 截断文件到 {bytes_already_written / 1024 / 1024:.1f} MB, "
                            f"清除损坏数据"
                        )
                        # 顺序写入不变量：若 term N 损坏，则 N 之后的数据不可信
                        assert bytes_already_written <= existing_size, (
                            f"[ChunkAssembler] truncate 将丢数据: {bytes_already_written} > {existing_size}"
                        )
                        f.truncate(bytes_already_written)
                        f.seek(bytes_already_written)
                        if progress_tracker:
                            baseline_correction = bytes_already_written - existing_size
                            progress_tracker.adjust_assembled(baseline_correction)
                            logger.debug(
                                f"[ChunkAssembler] 进度基线修正: "
                                f"{orig_baseline / 1024 / 1024:.1f} MB → "
                                f"{progress_tracker.get_assembled_bytes() / 1024 / 1024:.1f} MB"
                            )
                    else:
                        f.seek(0, 2)  # SEEK_END
                    current_pos = f.tell()
                    logger.debug(f"[ChunkAssembler] 文件指针位置: {current_pos}")

                for term_idx, term in enumerate(recon.terms):
                    # 跳过已完成的 terms（checkpoint 恢复）
                    if term_idx < start_term_idx:
                        continue

                    # 检查中断
                    if self._stop_event.is_set():
                        logger.info("[ChunkAssembler] 检测到中断信号")
                        raise KeyboardInterrupt("用户中断")

                    # 先检查水位线、预取后续 xorb（在同步下载前触发，给预取更多时间）
                    current_cache_bytes = sum(x.memory_footprint() for x in self._xorb_cache.values())
                    if current_cache_bytes < low_watermark:
                        self._prefetch_upcoming_xorbs(
                            term_idx, recon, cas_client, file_hash,
                            cache_adapter, high_watermark, progress_tracker
                        )

                    # 再确保 xorb 已加载（可能触发同步下载）
                    self._ensure_xorb_ready(
                        term.hash, recon, cas_client, file_hash, cache_adapter, progress_tracker
                    )

                    # 从 xorb 提取数据
                    xorb_data = self._xorb_cache[term.hash]

                    # xorb_data.chunk_offsets 存储的是 (全局chunk_id, byte_offset)
                    # term.range 也使用全局 chunk ID，可以直接查询
                    chunk_offsets_dict = dict(xorb_data.chunk_offsets)

                    start_chunk = term.range.start
                    end_chunk = term.range.end

                    if start_chunk not in chunk_offsets_dict:
                        raise ValueError(
                            f"[ChunkAssembler] Term #{term_idx} start chunk {start_chunk} "
                            f"不在 chunk_offsets 中"
                        )

                    start_byte = chunk_offsets_dict[start_chunk]
                    end_byte = 0

                    # end_chunk 可能不在 chunk_offsets 中（表示最后一个 chunk 之后）
                    if end_chunk not in chunk_offsets_dict:
                        # 查找 end_chunk 之后的第一个 offset，或使用数据末尾
                        sorted_chunks = sorted(chunk_offsets_dict.items())
                        found = False
                        for chunk_id, offset in sorted_chunks:
                            if chunk_id >= end_chunk:
                                end_byte = offset
                                found = True
                                break
                        if not found:
                            # end_chunk 超过所有已知 chunk，使用数据末尾
                            end_byte = xorb_data.data_size()
                    else:
                        end_byte = chunk_offsets_dict[end_chunk]

                    if end_byte > xorb_data.data_size():
                        raise ValueError(
                            f"[ChunkAssembler] Term #{term_idx} 数据范围越界: "
                            f"start={start_byte}, end={end_byte}, data_len={xorb_data.data_size()}"
                        )

                    segment = xorb_data.extract_range(start_byte, end_byte)

                    # 第一个 term 需要跳过 offset_into_first_range
                    if term_idx == 0 and recon.offset_into_first_range > 0:
                        offset = recon.offset_into_first_range
                        if offset >= len(segment):
                            raise ValueError(
                                f"[ChunkAssembler] offset_into_first_range ({offset}) >= "
                                f"第一个 term 长度 ({len(segment)})"
                            )
                        segment = segment[offset:]

                    # ★ 计算 per-term SHA256（segment 已调整完毕）
                    segment_hash = hashlib.sha256(segment).hexdigest()
                    file_offset = f.tell()  # 写入前的文件绝对偏移

                    # 写入文件
                    f.write(segment)
                    total_written += len(segment)

                    # 周期性 fsync：防止崩溃时 .part 文件在 confirmed_bytes 之后不完整
                    self._term_write_count += 1
                    if self._term_write_count % self.fsync_interval == 0:
                        f.flush()
                        os.fsync(f.fileno())

                    # 更新完成速率估算器
                    self._rate_estimator.update(len(segment))

                    if progress_tracker:
                        progress_tracker.increment_assembled(len(segment))
                        progress_tracker.increment_terms(1)

                    # Term 级 checkpoint + per-term SHA256
                    if checkpoint_manager:
                        checkpoint_manager.mark_term_completed(
                            file_hash=file_hash,
                            term_idx=term_idx,
                            xorb_hash=term.hash,
                            save_interval=self.checkpoint_interval,
                            confirmed_bytes=f.tell(),
                        )
                        checkpoint_manager.record_term_hash(
                            file_hash=file_hash,
                            term_index=term_idx,
                            sha256=segment_hash,
                            file_offset=file_offset,
                            unpacked_length=len(segment),
                            xorb_hash=term.hash,
                            save_interval=self.checkpoint_interval,
                        )

                    # 检查是否可以释放 xorb
                    if not self._is_xorb_needed_later(term.hash, term_idx, recon):
                        if term.hash in self._xorb_cache:
                            released_size = self._xorb_cache[term.hash].memory_footprint()
                            del self._xorb_cache[term.hash]
                            logger.debug(
                                f"[ChunkAssembler] 释放 xorb {term.hash[:16]}... "
                                f"({released_size / 1024 / 1024:.1f}MB)"
                            )

                    # 定期日志
                    if (term_idx + 1) % 100 == 0:
                        cache_mb = sum(x.memory_footprint() for x in self._xorb_cache.values()) / 1024 / 1024
                        logger.debug(
                            f"[ChunkAssembler] 进度: {term_idx + 1}/{len(recon.terms)} terms, "
                            f"缓存: {cache_mb:.1f}MB, "
                            f"已写入: {total_written / 1024 / 1024:.1f}MB"
                        )

                # final fsync：确保最后一个 fsync_interval 不足的 term 也落盘
                if file_mode != 'wb' or total_written > 0:
                    f.flush()
                    os.fsync(f.fileno())

            # 写入完成后重命名 .part -> 目标文件（直写模式跳过）
            if output_offset == 0:
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
            if output_offset > 0:
                logger.error(f"[ChunkAssembler] 直写模式写入失败: output={output_path}, offset={output_offset}")
                raise
            if not checkpoint_manager and part_path.exists():
                try:
                    part_path.unlink()
                    logger.debug(f"[ChunkAssembler] 清理 .part 文件: {part_path}")
                except Exception as e:
                    logger.warning(f"[ChunkAssembler] 清理 .part 文件失败: {e}")
            elif checkpoint_manager and part_path.exists():
                logger.info(
                    f"[ChunkAssembler] 保留 .part 文件以支持断点续传: {part_path.name}"
                )
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

        writer = None
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
                # 第一个 term 需要跳过 offset（使用负数初始化）
                current_offset = -recon.offset_into_first_range

            for term_idx, term in enumerate(recon.terms):
                # 跳过已完成的 terms（checkpoint 恢复）
                if term_idx < start_term_idx:
                    # 计算偏移量（即使跳过也要累加）
                    if term_idx == 0 and recon.offset_into_first_range > 0:
                        # 第一个 term：只累加实际写入的部分（与 segment[offset:] 一致）
                        current_offset += term.unpacked_length - recon.offset_into_first_range
                    else:
                        current_offset += term.unpacked_length
                    continue

                # 检查中断
                if self._stop_event.is_set():
                    logger.info("[ChunkAssembler] 检测到中断信号")
                    raise KeyboardInterrupt("用户中断")

                # 先检查水位线、预取后续 xorb（在同步下载前触发，给预取更多时间）
                current_cache_bytes = sum(x.memory_footprint() for x in self._xorb_cache.values())
                if current_cache_bytes < low_watermark:
                    self._prefetch_upcoming_xorbs(
                        term_idx, recon, cas_client, file_hash,
                        cache_adapter, high_watermark, progress_tracker
                    )

                # 再确保 xorb 已加载（可能触发同步下载）
                self._ensure_xorb_ready(
                    term.hash, recon, cas_client, file_hash, cache_adapter, progress_tracker
                )

                # 从 xorb 提取数据
                xorb_data = self._xorb_cache[term.hash]
                chunk_offset_dict = dict(xorb_data.chunk_offsets)

                start_chunk_idx = term.range.start
                end_chunk_idx = term.range.end

                # 根据 chunk range 计算 byte range
                # start_chunk_idx 的偏移量
                if start_chunk_idx == 0:
                    start_byte = 0
                else:
                    start_byte = chunk_offset_dict.get(start_chunk_idx)
                    if start_byte is None:
                        raise ValueError(
                            f"[ChunkAssembler] Chunk {start_chunk_idx} 未在 xorb {term.hash[:16]}... 中找到"
                        )

                # end_chunk_idx 的结束偏移量（使用 end-1 的下一个位置，或数据末尾）
                if end_chunk_idx == 0:
                    end_byte = 0
                else:
                    # end_chunk_idx-1 是最后一个包含的 chunk
                    # 我们需要找到 end_chunk_idx 的起始位置（即 end_chunk_idx-1 的结束位置）
                    end_byte = chunk_offset_dict.get(end_chunk_idx)
                    if end_byte is None:
                        # 如果 end_chunk_idx 超出范围，使用数据末尾
                        end_byte = xorb_data.data_size()

                if end_byte > xorb_data.data_size():
                    raise ValueError(
                        f"[ChunkAssembler] Term #{term_idx} 数据范围越界: "
                        f"start={start_byte}, end={end_byte}, data_len={xorb_data.data_size()}"
                    )

                segment = xorb_data.extract_range(start_byte, end_byte)

                # 第一个 term 需要跳过 offset_into_first_range
                if term_idx == 0 and recon.offset_into_first_range > 0:
                    offset = recon.offset_into_first_range
                    if offset >= len(segment):
                        raise ValueError(
                            f"[ChunkAssembler] offset_into_first_range ({offset}) >= "
                            f"第一个 term 长度 ({len(segment)})"
                        )
                    segment = segment[offset:]

                # ★ 计算 per-term SHA256（segment 已调整完毕）
                segment_hash = hashlib.sha256(segment).hexdigest()
                file_offset = max(0, current_offset)

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

                # Term 级 checkpoint + per-term SHA256
                if checkpoint_manager:
                    checkpoint_manager.mark_term_completed(
                        file_hash=file_hash,
                        term_idx=term_idx,
                        xorb_hash=term.hash,
                        save_interval=self.checkpoint_interval,
                        confirmed_bytes=current_offset,
                    )
                    checkpoint_manager.record_term_hash(
                        file_hash=file_hash,
                        term_index=term_idx,
                        sha256=segment_hash,
                        file_offset=file_offset,
                        unpacked_length=len(segment),
                        xorb_hash=term.hash,
                        save_interval=self.checkpoint_interval,
                    )

                # 检查是否可以释放 xorb
                if not self._is_xorb_needed_later(term.hash, term_idx, recon):
                    if term.hash in self._xorb_cache:
                        released_size = self._xorb_cache[term.hash].memory_footprint()
                        del self._xorb_cache[term.hash]
                        logger.debug(
                            f"[ChunkAssembler] 释放 xorb {term.hash[:16]}... "
                            f"({released_size / 1024 / 1024:.1f}MB)"
                        )

                # 定期日志
                if (term_idx + 1) % 100 == 0:
                    cache_mb = sum(x.memory_footprint() for x in self._xorb_cache.values()) / 1024 / 1024
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
            # 异常时：仅在无 checkpoint 的情况下清理 .part 文件
            # 有 checkpoint 时保留 .part，下次可从断点恢复（追加模式）
            if not checkpoint_manager and part_path.exists():
                try:
                    part_path.unlink()
                    logger.debug(f"[ChunkAssembler] 清理 .part 文件: {part_path}")
                except Exception as e:
                    logger.warning(f"[ChunkAssembler] 清理 .part 文件失败: {e}")
            elif checkpoint_manager and part_path.exists():
                logger.info(
                    f"[ChunkAssembler] 保留 .part 文件以支持断点续传: {part_path.name}"
                )
            raise

        finally:
            # 确保 writer 线程被正确关闭
            try:
                if writer and writer._started:
                    # 发送停止信号
                    writer.stop_event.set()
                    # 尝试等待线程结束（短超时）
                    if writer._writer_thread and writer._writer_thread.is_alive():
                        writer._writer_thread.join(timeout=5)
            except Exception as e:
                logger.warning(f"[ChunkAssembler] 关闭 GlobalWriter 失败: {e}")

