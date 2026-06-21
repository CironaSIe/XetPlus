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

        Args:
            xorb_hash: Xorb 哈希
            fetch_infos: Fetch info 列表（用于确定需要的 chunk 范围）

        Returns:
            (解压数据, chunk_byte_indices) 或 None（未命中）
        """
        if not self.chunk_cache or not self.chunk_cache.enabled:
            return None

        # 计算需要的 chunk 范围
        chunk_ranges = [fi.chunk_range for fi in fetch_infos]
        if not chunk_ranges:
            return None

        merged_range = ChunkRange(
            start=min(cr.start for cr in chunk_ranges),
            end=max(cr.end for cr in chunk_ranges)
        )

        # 尝试从 chunk 缓存读取
        cache_hit = self.chunk_cache.get(xorb_hash, merged_range)
        if cache_hit:
            logger.debug(
                f"[CacheAdapter] Chunk 缓存命中: {xorb_hash[:16]}... "
                f"范围 {merged_range}"
            )
            return (cache_hit.data, cache_hit.offsets)

        return None

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

        Args:
            xorb_hash: Xorb 哈希
            fetch_infos: Fetch info 列表（用于确定 chunk 范围）
            chunk_byte_indices: Chunk → byte 偏移映射（xorb 内部编号）
            decompressed_data: 解压后的数据
        """
        if not self.chunk_cache or not self.chunk_cache.enabled:
            return

        # 计算 chunk 范围
        chunk_ranges = [fi.chunk_range for fi in fetch_infos]
        if not chunk_ranges:
            return

        merged_range = ChunkRange(
            start=min(cr.start for cr in chunk_ranges),
            end=max(cr.end for cr in chunk_ranges)
        )

        # 检查长度是否匹配
        expected_len = merged_range.length() + 1
        if len(chunk_byte_indices) != expected_len:
            # 使用 INFO 级别确保输出
            logger.info(
                f"[CacheAdapter] 📊 Chunk 缓存长度不匹配分析:\n"
                f"  xorb_hash: {xorb_hash[:16]}...\n"
                f"  fetch_infos 数量: {len(fetch_infos)}"
            )
            for idx, fi in enumerate(fetch_infos):
                logger.info(
                    f"    [{idx}] chunk_range: {fi.chunk_range.start}-{fi.chunk_range.end} "
                    f"(长度 {fi.chunk_range.length()})"
                )
            logger.info(
                f"  merged_range: {merged_range.start}-{merged_range.end} (长度 {merged_range.length()})\n"
                f"  期望 indices: {expected_len}\n"
                f"  实际 indices: {len(chunk_byte_indices)}\n"
                f"  差异: {expected_len - len(chunk_byte_indices)}\n"
                f"  结论: 跳过缓存（xorb 只包含部分 chunks）"
            )
            return

        try:
            self.chunk_cache.put(
                xorb_hash,
                merged_range,
                chunk_byte_indices,
                decompressed_data
            )
            logger.debug(
                f"[CacheAdapter] ✅ 写入 chunk 缓存成功: {xorb_hash[:16]}... "
                f"范围 {merged_range}, {len(decompressed_data) / 1024 / 1024:.1f}MB"
            )
        except Exception as e:
            logger.warning(f"[CacheAdapter] 写入 chunk 缓存失败: {e}")
