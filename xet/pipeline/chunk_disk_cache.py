"""Chunk-level 磁盘缓存实现。

对齐 Rust 原版设计，缓存粒度为 (xorb_hash, chunk_range)，支持部分范围命中。

参考实现:
- ~/xet/xet_client/src/chunk_cache/mod.rs - ChunkCache trait
- ~/xet/xet_client/src/chunk_cache/disk.rs - DiskCache 实现
"""
import base64
import logging
import struct
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ChunkRange:
    """Chunk 范围 [start, end) 左闭右开。"""
    start: int  # u32
    end: int    # u32

    def contains(self, other: "ChunkRange") -> bool:
        """检查是否包含另一个范围。"""
        return self.start <= other.start and other.end <= self.end

    def length(self) -> int:
        """返回范围长度。"""
        return self.end - self.start

    def __repr__(self) -> str:
        return f"ChunkRange({self.start}, {self.end})"


@dataclass
class CacheRange:
    """缓存查询返回值。"""
    offsets: List[int]      # chunk → byte 偏移映射 (u32)
    data: bytes             # 解压后的数据
    range: ChunkRange       # 覆盖的 chunk 范围

    def extract_subrange(self, request: ChunkRange) -> "CacheRange":
        """从缓存数据中提取子范围。

        Args:
            request: 请求的范围（必须被 self.range 包含）

        Returns:
            子范围的 CacheRange

        Raises:
            ValueError: 请求范围未被包含
        """
        if not self.range.contains(request):
            raise ValueError(
                f"请求范围 {request} 未被缓存范围 {self.range} 包含"
            )

        # 计算子范围在 offsets 中的索引
        start_idx = request.start - self.range.start
        end_idx = request.end - self.range.start

        # 提取子范围的 offsets
        sub_offsets = self.offsets[start_idx:end_idx + 1]

        # 重新映射为从 0 开始
        base_offset = sub_offsets[0]
        normalized_offsets = [off - base_offset for off in sub_offsets]

        # 提取子范围的数据
        start_byte = sub_offsets[0]
        end_byte = sub_offsets[-1]
        sub_data = self.data[start_byte:end_byte]

        return CacheRange(
            offsets=normalized_offsets,
            data=sub_data,
            range=request
        )


@dataclass
class CacheItem:
    """缓存项元数据（从文件名编码/解码）。"""
    range: ChunkRange
    length: int             # u64: 文件大小（header + data）
    checksum: int           # u32: CRC32 校验和

    def encode_filename(self) -> str:
        """编码为 base64 文件名。

        格式: Base64(range_start || range_end || length || checksum)
        所有数字小端序打包
        """
        packed = struct.pack(
            '<IIQI',  # 小端序: u32, u32, u64, u32
            self.range.start,
            self.range.end,
            self.length,
            self.checksum
        )
        return base64.b64encode(packed).decode('ascii')

    @classmethod
    def decode_filename(cls, filename: str) -> "CacheItem":
        """从文件名解码。

        Args:
            filename: Base64 编码的文件名

        Returns:
            CacheItem 实例

        Raises:
            ValueError: 文件名格式错误
        """
        try:
            packed = base64.b64decode(filename.encode('ascii'))
            start, end, length, checksum = struct.unpack('<IIQI', packed)
            return cls(
                range=ChunkRange(start, end),
                length=length,
                checksum=checksum
            )
        except Exception as e:
            raise ValueError(f"无法解码文件名 {filename}: {e}") from e


class ChunkDiskCache:
    """Chunk-level 磁盘缓存。

    文件布局:
        cache_root/
        ├── {prefix}/                   # key 的前 2 个字符
        │   ├── {xorb_hash_base64}/
        │   │   ├── {range_len_checksum_base64}
        │   │   └── ...
        │   └── ...
        └── ...

    文件内容:
        [Header]
          u32: chunk_byte_indices.len()
          u32[]: chunk_byte_indices
        [Data]
          bytes: 解压后的数据
    """

    def __init__(self, cache_root: Path, capacity_bytes: int):
        """初始化缓存。

        Args:
            cache_root: 缓存根目录
            capacity_bytes: 缓存容量（字节）
        """
        self.cache_root = cache_root
        self.capacity = capacity_bytes
        self.enabled = capacity_bytes > 0

        # 内存索引: {xorb_hash: [CacheItem, ...]}
        self._state: Dict[str, List[CacheItem]] = {}
        self._total_bytes = 0
        self._lock = threading.Lock()

        if self.enabled:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            self._scan_cache()

    def get(self, xorb_hash: str, chunk_range: ChunkRange) -> Optional[CacheRange]:
        """查询缓存（支持部分范围命中）。

        Args:
            xorb_hash: Xorb 哈希值
            chunk_range: 请求的 chunk 范围

        Returns:
            CacheRange 如果命中，否则 None
        """
        if not self.enabled:
            return None

        with self._lock:
            # 查找匹配的缓存项
            item = self._find_match(xorb_hash, chunk_range)
            if not item:
                return None

            # 读取缓存文件
            try:
                cache_file = self._get_cache_file_path(xorb_hash, item)
                if not cache_file.exists():
                    logger.warning(
                        f"[ChunkCache] 缓存文件不存在: {cache_file}"
                    )
                    self._remove_item(xorb_hash, item)
                    return None

                # 验证文件大小
                actual_size = cache_file.stat().st_size
                if actual_size != item.length:
                    logger.warning(
                        f"[ChunkCache] 文件大小不匹配: {cache_file}, "
                        f"期望 {item.length}, 实际 {actual_size}"
                    )
                    self._remove_item(xorb_hash, item)
                    return None

                # 读取文件
                with open(cache_file, 'rb') as f:
                    # 读取 header: chunk_byte_indices.len() + 数组
                    indices_count = struct.unpack('<I', f.read(4))[0]
                    offsets = list(struct.unpack(
                        f'<{indices_count}I',
                        f.read(4 * indices_count)
                    ))
                    data = f.read()

                # 验证 checksum
                actual_checksum = zlib.crc32(data) & 0xFFFFFFFF
                if actual_checksum != item.checksum:
                    logger.warning(
                        f"[ChunkCache] 校验和不匹配: {cache_file}, "
                        f"期望 {item.checksum}, 实际 {actual_checksum}"
                    )
                    self._remove_item(xorb_hash, item)
                    return None

                cache_range = CacheRange(
                    offsets=offsets,
                    data=data,
                    range=item.range
                )

                # 如果请求的是子范围，提取子范围
                if item.range != chunk_range:
                    cache_range = cache_range.extract_subrange(chunk_range)

                logger.debug(
                    f"[ChunkCache] 缓存命中: {xorb_hash[:16]}... "
                    f"请求 {chunk_range}, 缓存 {item.range}"
                )

                return cache_range

            except Exception as e:
                logger.warning(
                    f"[ChunkCache] 读取缓存失败: {xorb_hash[:16]}... {e}"
                )
                self._remove_item(xorb_hash, item)
                return None

    def put(
        self,
        xorb_hash: str,
        chunk_range: ChunkRange,
        chunk_byte_indices: List[int],
        data: bytes
    ) -> None:
        """写入缓存。

        Args:
            xorb_hash: Xorb 哈希值
            chunk_range: Chunk 范围
            chunk_byte_indices: Chunk → byte 偏移映射
            data: 解压后的数据

        Raises:
            ValueError: 参数验证失败
        """
        if not self.enabled:
            return

        # 验证参数
        expected_len = chunk_range.length() + 1
        if len(chunk_byte_indices) != expected_len:
            raise ValueError(
                f"chunk_byte_indices 长度不匹配: "
                f"期望 {expected_len}, 实际 {len(chunk_byte_indices)}"
            )

        if chunk_byte_indices[0] != 0:
            raise ValueError(
                f"chunk_byte_indices[0] 必须为 0, 实际 {chunk_byte_indices[0]}"
            )

        if chunk_byte_indices[-1] != len(data):
            raise ValueError(
                f"chunk_byte_indices[-1] 必须等于 data.len(), "
                f"期望 {len(data)}, 实际 {chunk_byte_indices[-1]}"
            )

        # 计算 checksum
        checksum = zlib.crc32(data) & 0xFFFFFFFF

        # 构建 header
        header = struct.pack('<I', len(chunk_byte_indices))
        header += struct.pack(f'<{len(chunk_byte_indices)}I', *chunk_byte_indices)

        # 计算文件大小
        file_size = len(header) + len(data)

        # 创建 CacheItem
        item = CacheItem(
            range=chunk_range,
            length=file_size,
            checksum=checksum
        )

        with self._lock:
            # 检查是否已存在
            if xorb_hash in self._state:
                for existing in self._state[xorb_hash]:
                    if existing.range == chunk_range:
                        logger.debug(
                            f"[ChunkCache] 缓存项已存在: {xorb_hash[:16]}... {chunk_range}"
                        )
                        return

            # 驱逐旧项（如果需要）
            self._evict_to_capacity(file_size)

            # 写入文件
            cache_file = self._get_cache_file_path(xorb_hash, item)
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            try:
                with open(cache_file, 'wb') as f:
                    f.write(header)
                    f.write(data)

                # 更新索引
                if xorb_hash not in self._state:
                    self._state[xorb_hash] = []
                self._state[xorb_hash].append(item)
                self._total_bytes += file_size

                logger.debug(
                    f"[ChunkCache] 写入缓存: {xorb_hash[:16]}... {chunk_range}, "
                    f"{file_size / 1024 / 1024:.1f}MB"
                )

            except Exception as e:
                logger.error(f"[ChunkCache] 写入失败: {e}")
                if cache_file.exists():
                    cache_file.unlink()
                raise

    def _find_match(
        self,
        xorb_hash: str,
        chunk_range: ChunkRange
    ) -> Optional[CacheItem]:
        """查找包含请求范围的缓存项。

        Args:
            xorb_hash: Xorb 哈希值
            chunk_range: 请求的 chunk 范围

        Returns:
            匹配的 CacheItem，或 None
        """
        items = self._state.get(xorb_hash, [])
        for item in items:
            if item.range.contains(chunk_range):
                return item
        return None

    def _evict_to_capacity(self, required_bytes: int) -> None:
        """驱逐缓存项直到有足够空间。

        Args:
            required_bytes: 需要的空间（字节）
        """
        import random

        while self._total_bytes + required_bytes > self.capacity:
            if not self._state:
                break

            # 随机选择一个 xorb_hash
            xorb_hash = random.choice(list(self._state.keys()))
            items = self._state[xorb_hash]

            if not items:
                del self._state[xorb_hash]
                continue

            # 随机选择一个 item
            item = random.choice(items)

            # 删除文件和索引
            self._remove_item(xorb_hash, item)

    def _remove_item(self, xorb_hash: str, item: CacheItem) -> None:
        """删除缓存项（文件 + 索引）。

        Args:
            xorb_hash: Xorb 哈希值
            item: 缓存项
        """
        # 删除文件
        cache_file = self._get_cache_file_path(xorb_hash, item)
        if cache_file.exists():
            try:
                cache_file.unlink()
                self._total_bytes -= item.length
            except Exception as e:
                logger.warning(f"[ChunkCache] 删除文件失败: {cache_file}, {e}")

        # 更新索引
        if xorb_hash in self._state:
            items = self._state[xorb_hash]
            if item in items:
                items.remove(item)
            if not items:
                del self._state[xorb_hash]
                # 删除空目录
                xorb_dir = self._get_xorb_dir(xorb_hash)
                if xorb_dir.exists() and not any(xorb_dir.iterdir()):
                    xorb_dir.rmdir()

    def _get_cache_file_path(self, xorb_hash: str, item: CacheItem) -> Path:
        """获取缓存文件路径。

        Args:
            xorb_hash: Xorb 哈希值
            item: 缓存项

        Returns:
            缓存文件路径
        """
        xorb_dir = self._get_xorb_dir(xorb_hash)
        filename = item.encode_filename()
        return xorb_dir / filename

    def _get_xorb_dir(self, xorb_hash: str) -> Path:
        """获取 xorb 目录。

        Args:
            xorb_hash: Xorb 哈希值

        Returns:
            Xorb 目录路径
        """
        # 使用 base64 编码 xorb_hash 作为目录名
        xorb_encoded = base64.b64encode(xorb_hash.encode('utf-8')).decode('ascii')
        prefix = xorb_hash[:2] if len(xorb_hash) >= 2 else 'xx'
        return self.cache_root / prefix / xorb_encoded

    def _scan_cache(self) -> None:
        """扫描缓存目录，构建内存索引。"""
        if not self.cache_root.exists():
            return

        for prefix_dir in self.cache_root.iterdir():
            if not prefix_dir.is_dir():
                continue

            for xorb_dir in prefix_dir.iterdir():
                if not xorb_dir.is_dir():
                    continue

                # 解码 xorb_hash
                try:
                    xorb_hash = base64.b64decode(
                        xorb_dir.name.encode('ascii')
                    ).decode('utf-8')
                except Exception:
                    logger.warning(f"[ChunkCache] 无法解码目录名: {xorb_dir.name}")
                    continue

                # 扫描该 xorb 的所有缓存项
                items = []
                for cache_file in xorb_dir.iterdir():
                    if not cache_file.is_file():
                        continue

                    try:
                        item = CacheItem.decode_filename(cache_file.name)
                        # 验证文件大小
                        actual_size = cache_file.stat().st_size
                        if actual_size == item.length:
                            items.append(item)
                            self._total_bytes += item.length
                        else:
                            logger.warning(
                                f"[ChunkCache] 扫描时发现损坏文件: {cache_file}"
                            )
                            cache_file.unlink()
                    except Exception as e:
                        logger.warning(
                            f"[ChunkCache] 扫描文件失败: {cache_file}, {e}"
                        )

                if items:
                    self._state[xorb_hash] = items

        logger.info(
            f"[ChunkCache] 缓存扫描完成: {len(self._state)} xorbs, "
            f"{self._total_bytes / 1024 / 1024:.1f}MB"
        )

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            # 删除所有文件
            for xorb_hash, items in self._state.items():
                for item in items:
                    cache_file = self._get_cache_file_path(xorb_hash, item)
                    if cache_file.exists():
                        cache_file.unlink()

            # 清空索引
            self._state.clear()
            self._total_bytes = 0

            logger.info("[ChunkCache] 缓存已清空")
