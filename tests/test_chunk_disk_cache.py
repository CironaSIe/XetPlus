"""Chunk-level 磁盘缓存单元测试。"""
import tempfile
import pytest
from pathlib import Path

from xet.pipeline.chunk_disk_cache import (
    ChunkRange,
    CacheRange,
    CacheItem,
    ChunkDiskCache,
)


class TestChunkRange:
    """测试 ChunkRange 类。"""

    def test_contains_exact_match(self):
        """测试完全匹配的范围。"""
        r1 = ChunkRange(0, 100)
        r2 = ChunkRange(0, 100)
        assert r1.contains(r2)

    def test_contains_subrange(self):
        """测试子范围包含关系。"""
        r1 = ChunkRange(0, 100)
        r2 = ChunkRange(10, 50)
        assert r1.contains(r2)
        assert not r2.contains(r1)

    def test_contains_partial_overlap(self):
        """测试部分重叠（不包含）。"""
        r1 = ChunkRange(0, 100)
        r2 = ChunkRange(50, 150)
        assert not r1.contains(r2)
        assert not r2.contains(r1)

    def test_length(self):
        """测试范围长度计算。"""
        r = ChunkRange(10, 50)
        assert r.length() == 40


class TestCacheRange:
    """测试 CacheRange 类。"""

    def test_extract_subrange_full(self):
        """测试提取完整范围。"""
        cache_range = CacheRange(
            offsets=[0, 100, 250, 400],
            data=b"x" * 400,
            range=ChunkRange(0, 3)
        )
        extracted = cache_range.extract_subrange(ChunkRange(0, 3))
        assert extracted.range == ChunkRange(0, 3)
        assert extracted.offsets == [0, 100, 250, 400]
        assert len(extracted.data) == 400

    def test_extract_subrange_middle(self):
        """测试提取中间子范围。"""
        cache_range = CacheRange(
            offsets=[0, 100, 250, 400],
            data=b"a" * 100 + b"b" * 150 + b"c" * 150,
            range=ChunkRange(0, 3)
        )
        extracted = cache_range.extract_subrange(ChunkRange(1, 2))
        assert extracted.range == ChunkRange(1, 2)
        assert extracted.offsets == [0, 150]  # 重新映射为从 0 开始
        assert extracted.data == b"b" * 150

    def test_extract_subrange_invalid(self):
        """测试提取无效子范围（不包含）。"""
        cache_range = CacheRange(
            offsets=[0, 100, 250],
            data=b"x" * 250,
            range=ChunkRange(0, 2)
        )
        with pytest.raises(ValueError):
            cache_range.extract_subrange(ChunkRange(5, 10))


class TestCacheItem:
    """测试 CacheItem 编码/解码。"""

    def test_encode_decode_roundtrip(self):
        """测试编码和解码往返。"""
        item = CacheItem(
            range=ChunkRange(10, 200),
            length=1024 * 1024,  # 1MB
            checksum=0x12345678
        )
        filename = item.encode_filename()
        decoded = CacheItem.decode_filename(filename)

        assert decoded.range.start == item.range.start
        assert decoded.range.end == item.range.end
        assert decoded.length == item.length
        assert decoded.checksum == item.checksum

    def test_decode_invalid_filename(self):
        """测试解码无效文件名。"""
        with pytest.raises(ValueError):
            CacheItem.decode_filename("invalid_base64!")


class TestChunkDiskCache:
    """测试 ChunkDiskCache 类。"""

    @pytest.fixture
    def temp_cache(self):
        """创建临时缓存目录。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ChunkDiskCache(
                cache_root=Path(tmpdir),
                capacity_bytes=10 * 1024 * 1024  # 10MB
            )
            yield cache

    def test_cache_put_and_get_exact_match(self, temp_cache):
        """测试完全匹配的缓存写入和读取。"""
        xorb_hash = "test_xorb_1"
        chunk_range = ChunkRange(0, 3)
        chunk_byte_indices = [0, 100, 250, 400]
        data = b"a" * 100 + b"b" * 150 + b"c" * 150

        # 写入缓存
        temp_cache.put(xorb_hash, chunk_range, chunk_byte_indices, data)

        # 读取缓存
        result = temp_cache.get(xorb_hash, chunk_range)
        assert result is not None
        assert result.range == chunk_range
        assert result.offsets == chunk_byte_indices
        assert result.data == data

    def test_cache_get_partial_range_hit(self, temp_cache):
        """测试部分范围命中（缓存 [0,100) 满足请求 [10,50)）。"""
        xorb_hash = "test_xorb_2"
        cached_range = ChunkRange(0, 100)
        chunk_byte_indices = [0] + [i * 10 for i in range(1, 101)]  # 100 个 chunk，每个 10 字节
        data = b"x" * 1000

        # 写入缓存
        temp_cache.put(xorb_hash, cached_range, chunk_byte_indices, data)

        # 请求子范围
        request_range = ChunkRange(10, 50)
        result = temp_cache.get(xorb_hash, request_range)

        assert result is not None
        # 实现会自动提取子范围
        assert result.range == request_range
        # 验证提取的数据正确
        assert len(result.data) == 400  # chunk 10-49, 每个 10 字节
        assert result.offsets[0] == 0  # 重新映射为从 0 开始
        assert result.offsets[-1] == len(result.data)

    def test_cache_miss(self, temp_cache):
        """测试缓存未命中。"""
        result = temp_cache.get("non_existent_xorb", ChunkRange(0, 10))
        assert result is None

    def test_cache_eviction(self, temp_cache):
        """测试缓存驱逐。"""
        # 创建小容量缓存（只能存 2KB）
        small_cache = ChunkDiskCache(
            cache_root=temp_cache.cache_root / "small",
            capacity_bytes=2 * 1024
        )

        # 写入第一个缓存项（1KB）
        data1 = b"a" * 1024
        small_cache.put("xorb1", ChunkRange(0, 1), [0, 1024], data1)
        assert small_cache._total_bytes > 0

        # 写入第二个缓存项（1.5KB，应该触发驱逐）
        data2 = b"b" * 1536
        small_cache.put("xorb2", ChunkRange(0, 1), [0, 1536], data2)

        # 验证总大小在容量限制内
        assert small_cache._total_bytes <= 2 * 1024

    def test_cache_clear(self, temp_cache):
        """测试缓存清空。"""
        # 写入一些数据
        temp_cache.put("xorb1", ChunkRange(0, 1), [0, 100], b"x" * 100)
        temp_cache.put("xorb2", ChunkRange(0, 1), [0, 200], b"y" * 200)

        assert temp_cache._total_bytes > 0

        # 清空缓存
        temp_cache.clear()

        assert temp_cache._total_bytes == 0
        assert len(temp_cache._state) == 0

    def test_cache_validation_wrong_indices_length(self, temp_cache):
        """测试参数验证：chunk_byte_indices 长度错误。"""
        with pytest.raises(ValueError, match="chunk_byte_indices 长度不匹配"):
            temp_cache.put(
                "xorb1",
                ChunkRange(0, 3),  # 需要 4 个索引
                [0, 100, 250],     # 只有 3 个
                b"x" * 250
            )

    def test_cache_validation_first_index_not_zero(self, temp_cache):
        """测试参数验证：第一个索引不为 0。"""
        with pytest.raises(ValueError, match="chunk_byte_indices\\[0\\] 必须为 0"):
            temp_cache.put(
                "xorb1",
                ChunkRange(0, 2),
                [10, 100, 250],  # 第一个不是 0
                b"x" * 250
            )

    def test_cache_validation_last_index_mismatch(self, temp_cache):
        """测试参数验证：最后一个索引不等于数据长度。"""
        with pytest.raises(ValueError, match="chunk_byte_indices\\[-1\\] 必须等于 data.len"):
            temp_cache.put(
                "xorb1",
                ChunkRange(0, 2),
                [0, 100, 300],  # 最后一个是 300，但数据只有 250
                b"x" * 250
            )

    def test_cache_disabled(self):
        """测试禁用缓存（capacity = 0）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = ChunkDiskCache(
                cache_root=Path(tmpdir),
                capacity_bytes=0  # 禁用
            )
            assert not cache.enabled

            # 写入不应该做任何事
            cache.put("xorb1", ChunkRange(0, 1), [0, 100], b"x" * 100)
            assert cache._total_bytes == 0

            # 读取应该返回 None
            result = cache.get("xorb1", ChunkRange(0, 1))
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
