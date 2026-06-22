"""Chunk 缓存适配器 - 渐进式集成到现有流程。

提供 xorb-level 缓存到 chunk-level 缓存的过渡方案。
允许两种缓存并存，逐步迁移。
"""
import logging
from pathlib import Path
from typing import Optional, List, Tuple, TYPE_CHECKING

from xet.pipeline.chunk_disk_cache import ChunkDiskCache, ChunkRange, CacheRange
from xet.pipeline.xorb_disk_cache import XorbDiskCache

if TYPE_CHECKING:
    from xet.protocol.types import CASReconstructionFetchInfo

logger = logging.getLogger(__name__)


class ChunkCacheAdapter:
    """Chunk 缓存适配器。

    提供统一的缓存接口，支持：
    1. 尝试从 chunk 缓存读取（新）
    2. 回退到 xorb 缓存（旧）
    3. 写入到 chunk 缓存（新）

    Attributes:
        chunk_cache: Chunk-level 缓存实例
        xorb_cache: Xorb-level 缓存实例（用于回退）
    """

    def __init__(
        self,
        chunk_cache: Optional[ChunkDiskCache] = None,
        xorb_cache: Optional[XorbDiskCache] = None,
    ):
        """初始化适配器。

        Args:
            chunk_cache: Chunk-level 缓存（可选）
            xorb_cache: Xorb-level 缓存（可选）
        """
        self.chunk_cache = chunk_cache
        self.xorb_cache = xorb_cache
        self.enabled = (chunk_cache and chunk_cache.enabled) or (xorb_cache and xorb_cache.enabled)

        if chunk_cache and chunk_cache.enabled:
            logger.info("[CacheAdapter] Chunk-level 缓存已启用")
        elif xorb_cache and xorb_cache.enabled:
            logger.info("[CacheAdapter] Xorb-level 缓存已启用（回退模式）")
        else:
            logger.info("[CacheAdapter] 缓存已禁用")

    def get_xorb_compressed(
        self,
        xorb_hash: str,
        expected_size: int,
    ) -> Optional[bytes]:
        """获取压缩的 xorb 数据（仅从 xorb 缓存）。

        Args:
            xorb_hash: Xorb 哈希
            expected_size: 期望的压缩数据大小

        Returns:
            压缩的 xorb 数据，或 None（未命中）
        """
        if self.xorb_cache and self.xorb_cache.enabled:
            return self.xorb_cache.get(xorb_hash, expected_size)
        return None

    def get_xorb_decompressed(
        self,
        xorb_hash: str,
        fetch_infos: List["CASReconstructionFetchInfo"],
    ) -> Optional[Tuple[bytes, List[int]]]:
        """获取解压后的 xorb 数据（尝试 chunk 缓存）。

        支持从多个分段缓存中读取并重组。

        Args:
            xorb_hash: Xorb 哈希
            fetch_infos: Fetch info 列表（用于确定需要的 chunk 范围）

        Returns:
            (解压数据, chunk_byte_indices) 或 None（未完全命中）
        """
        if not self.chunk_cache or not self.chunk_cache.enabled:
            return None

        # 获取所有 chunk ranges 并排序
        chunk_ranges = sorted([fi.chunk_range for fi in fetch_infos], key=lambda cr: cr.start)
        if not chunk_ranges:
            return None

        # 尝试从缓存中读取每个 chunk range
        cached_segments = []
        for chunk_range in chunk_ranges:
            cache_hit = self.chunk_cache.get(xorb_hash, chunk_range)
            if not cache_hit:
                # 任何一个 range 未命中，整体未命中
                logger.debug(
                    f"[CacheAdapter] Chunk 缓存部分未命中: {xorb_hash[:16]}... "
                    f"范围 {chunk_range} 不在缓存中"
                )
                return None
            cached_segments.append(cache_hit)

        # 所有 ranges 都命中，重组数据
        logger.debug(
            f"[CacheAdapter] Chunk 缓存完全命中: {xorb_hash[:16]}... "
            f"{len(chunk_ranges)} 个 ranges"
        )

        # 合并数据和偏移
        merged_data = b""
        merged_indices = [0]  # 起始偏移总是 0
        current_offset = 0

        for segment in cached_segments:
            # 添加这段数据
            merged_data += segment.data

            # 添加这段的偏移（除了第一个 0，因为已经有了）
            # segment.offsets[1:] 是这段内部的相对偏移
            # 需要加上 current_offset 转换为绝对偏移
            for offset in segment.offsets[1:]:
                merged_indices.append(current_offset + offset)

            # 更新当前偏移
            current_offset += len(segment.data)

        return (merged_data, merged_indices)

    def put_xorb_compressed(
        self,
        xorb_hash: str,
        compressed_data: bytes,
    ) -> None:
        """保存压缩的 xorb 数据（仅到 xorb 缓存）。

        Args:
            xorb_hash: Xorb 哈希
            compressed_data: 压缩的 xorb 数据
        """
        if self.xorb_cache and self.xorb_cache.enabled:
            self.xorb_cache.put(xorb_hash, compressed_data)

    def put_xorb_decompressed(
        self,
        xorb_hash: str,
        fetch_infos: List["CASReconstructionFetchInfo"],
        chunk_byte_indices: List[int],
        decompressed_data: bytes,
    ) -> None:
        """保存解压后的 xorb 数据（到 chunk 缓存）。

        支持不连续的 chunk ranges：为每个连续的 range 分别缓存。

        Args:
            xorb_hash: Xorb 哈希
            fetch_infos: Fetch info 列表（用于确定 chunk 范围）
            chunk_byte_indices: Chunk → byte 偏移映射（xorb 内部编号，连续）
            decompressed_data: 解压后的数据
        """
        if not self.chunk_cache or not self.chunk_cache.enabled:
            return

        # 获取所有 chunk ranges 并排序
        chunk_ranges = sorted([fi.chunk_range for fi in fetch_infos], key=lambda cr: cr.start)
        if not chunk_ranges:
            return

        # 验证总 chunks 数量
        total_chunks = sum(cr.length() for cr in chunk_ranges)
        expected_len = total_chunks + 1
        if len(chunk_byte_indices) != expected_len:
            logger.warning(
                f"[CacheAdapter] ⚠️  Chunk 缓存数据异常: xorb_hash={xorb_hash[:16]}..., "
                f"期望 {expected_len} 个 indices, 实际 {len(chunk_byte_indices)}"
            )
            return

        # 为每个连续的 chunk range 分别缓存
        # 维护全局 chunk 编号到 xorb 内部索引的映射
        xorb_internal_idx = 0  # xorb 内部 chunk 索引（从 0 开始连续）

        for chunk_range in chunk_ranges:
            num_chunks = chunk_range.length()

            # 提取这个 range 对应的 chunk_byte_indices 子集
            # xorb_internal_idx 是起始 chunk 在 xorb 内部的索引
            # 需要 num_chunks + 1 个偏移（包括结束偏移）
            start_idx = xorb_internal_idx
            end_idx = xorb_internal_idx + num_chunks + 1

            sub_indices = chunk_byte_indices[start_idx:end_idx]

            # 提取对应的数据
            # sub_indices[0] 是这段数据的起始偏移
            # sub_indices[-1] 是这段数据的结束偏移
            data_start = sub_indices[0]
            data_end = sub_indices[-1]
            sub_data = decompressed_data[data_start:data_end]

            # 调整 sub_indices 使其从 0 开始
            adjusted_indices = [offset - data_start for offset in sub_indices]

            try:
                self.chunk_cache.put(
                    xorb_hash,
                    chunk_range,
                    adjusted_indices,
                    sub_data
                )
                logger.debug(
                    f"[CacheAdapter] ✅ 写入 chunk 缓存: {xorb_hash[:16]}... "
                    f"范围 {chunk_range}, {len(sub_data) / 1024 / 1024:.2f}MB"
                )
            except Exception as e:
                # 缓存写入失败不是致命错误，降级为 DEBUG
                # 常见原因：磁盘满、只读文件系统、权限问题
                logger.debug(
                    f"[CacheAdapter] 写入 chunk 缓存失败（忽略）: {xorb_hash[:16]}... "
                    f"范围 {chunk_range}, 错误: {e}"
                )

            # 更新 xorb 内部索引
            xorb_internal_idx += num_chunks
