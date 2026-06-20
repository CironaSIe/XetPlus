"""xorb_format 模块单元测试。

测试 xorb 二进制格式解析的所有纯函数。
"""
import pytest
from xet.protocol.xorb_format import (
    parse_chunk_header,
    decompress_chunk,
    deserialize_xorb_stream,
    merge_xorb_parts,
    is_lz4_available,
    COMPRESSION_NONE,
    COMPRESSION_LZ4,
    COMPRESSION_BYTE_GROUPING_4_LZ4,
    XorbFormatError,
    XorbCompressionError,
)


# ============================================================================
# parse_chunk_header 测试
# ============================================================================

def test_parse_header_valid():
    """测试有效的 xorb chunk header。"""
    # 构造 header: version=0, compressed=4096, scheme=1(LZ4), decompressed=16384
    header = bytes([
        0,                      # version
        0x00, 0x10, 0x00,      # compressed_length = 4096 (u24 LE)
        1,                      # scheme = LZ4
        0x00, 0x40, 0x00,      # decompressed_length = 16384 (u24 LE)
    ])

    result = parse_chunk_header(header)

    assert result['version'] == 0
    assert result['compressed_length'] == 4096
    assert result['compression_scheme'] == 1
    assert result['decompressed_length'] == 16384


def test_parse_header_with_offset():
    """测试带偏移的 header 解析。"""
    # 在前面加些垃圾数据
    data = b'\x00\x00\x00\x00' + bytes([
        0,                      # version
        0xFF, 0x00, 0x00,      # compressed_length = 255
        2,                      # scheme = ByteGrouping4LZ4
        0x00, 0x04, 0x00,      # decompressed_length = 1024
    ])

    result = parse_chunk_header(data, offset=4)

    assert result['version'] == 0
    assert result['compressed_length'] == 255
    assert result['compression_scheme'] == 2
    assert result['decompressed_length'] == 1024


def test_parse_header_truncated():
    """测试截断的 header。"""
    truncated = bytes([0, 1, 2])  # 只有 3 字节

    with pytest.raises(XorbFormatError, match="需要 8 字节"):
        parse_chunk_header(truncated)


def test_parse_header_u24_max():
    """测试 u24 最大值（16,777,215）。"""
    header = bytes([
        0,
        0xFF, 0xFF, 0xFF,      # compressed = 16777215
        0,
        0xFF, 0xFF, 0xFF,      # decompressed = 16777215
    ])

    result = parse_chunk_header(header)

    assert result['compressed_length'] == 16777215
    assert result['decompressed_length'] == 16777215


# ============================================================================
# decompress_chunk 测试
# ============================================================================

def test_decompress_none():
    """测试无压缩方案。"""
    data = b"hello world"
    result = decompress_chunk(data, COMPRESSION_NONE, len(data))

    assert result == data


def test_decompress_none_size_mismatch():
    """测试无压缩方案大小不匹配。"""
    data = b"hello"

    with pytest.raises(XorbCompressionError, match="大小不匹配"):
        decompress_chunk(data, COMPRESSION_NONE, 10)


@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_decompress_lz4():
    """测试 LZ4 压缩。"""
    import lz4.frame

    original = b"hello world " * 100  # 重复数据，压缩效果好
    compressed = lz4.frame.compress(original)

    result = decompress_chunk(compressed, COMPRESSION_LZ4, len(original))

    assert result == original


@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_decompress_byte_grouping_4_lz4():
    """测试 ByteGrouping4LZ4 压缩。

    ByteGrouping4 的分组算法：
    - 将原始数据按位置 round-robin 分配到 4 个组
    - 原始: [a0, a1, a2, a3, b0, b1, b2, b3, c0, c1]
    - 分组后: [a0, b0, c0] [a1, b1, c1] [a2, b2, c2] [a3, b3] （4个组）
    - 输出: group0 + group1 + group2 + group3
    """
    import lz4.frame
    from xet.protocol.xorb_format import _ungrouping_4byte

    # 简单测试：16 字节，正好 4 组各 4 字节
    original = bytes(range(16))

    # 手动分组（按位置 round-robin）
    # group0: [0, 4, 8, 12]
    # group1: [1, 5, 9, 13]
    # group2: [2, 6, 10, 14]
    # group3: [3, 7, 11, 15]
    groups = [[], [], [], []]
    for i, byte_val in enumerate(original):
        groups[i % 4].append(byte_val)

    grouped = bytes([b for group in groups for b in group])
    # grouped 应该是: [0,4,8,12, 1,5,9,13, 2,6,10,14, 3,7,11,15]

    compressed = lz4.frame.compress(grouped)

    # 解压（应该还原 original）
    result = decompress_chunk(compressed, COMPRESSION_BYTE_GROUPING_4_LZ4, len(grouped))

    assert result == original


def test_decompress_unknown_scheme():
    """测试不支持的压缩方案。"""
    data = b"dummy"

    with pytest.raises(XorbFormatError, match="不支持的压缩方案"):
        decompress_chunk(data, 99, len(data))


def test_decompress_lz4_not_available():
    """测试 LZ4 库未安装时的错误。"""
    # 临时替换 LZ4_AVAILABLE
    import xet.protocol.xorb_format as xorb_mod
    original_flag = xorb_mod.LZ4_AVAILABLE

    try:
        xorb_mod.LZ4_AVAILABLE = False

        with pytest.raises(ImportError, match="需要 lz4 库"):
            decompress_chunk(b"dummy", COMPRESSION_LZ4, 5)
    finally:
        xorb_mod.LZ4_AVAILABLE = original_flag


# ============================================================================
# deserialize_xorb_stream 测试
# ============================================================================

def test_deserialize_empty():
    """测试空数据。"""
    with pytest.raises(XorbFormatError, match="不能为空"):
        deserialize_xorb_stream(b"")


@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_deserialize_single_chunk():
    """测试单个 chunk。"""
    import lz4.frame

    original = b"hello world"
    compressed = lz4.frame.compress(original)

    # 构造 xorb: header + compressed data
    header = bytes([
        0,                                      # version
        len(compressed) & 0xFF,                # compressed_length (u24 LE)
        (len(compressed) >> 8) & 0xFF,
        (len(compressed) >> 16) & 0xFF,
        1,                                      # scheme = LZ4
        len(original) & 0xFF,                  # decompressed_length (u24 LE)
        (len(original) >> 8) & 0xFF,
        (len(original) >> 16) & 0xFF,
    ])
    xorb_bytes = header + compressed

    data, offsets = deserialize_xorb_stream(xorb_bytes)

    assert data == original
    assert len(offsets) == 1
    assert offsets[0] == (0, 0)  # chunk 0 at offset 0


@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_deserialize_multiple_chunks():
    """测试多个 chunks。"""
    import lz4.frame

    chunks_data = [b"chunk1", b"chunk2", b"chunk3"]
    xorb_bytes = bytearray()

    for chunk in chunks_data:
        compressed = lz4.frame.compress(chunk)
        header = bytes([
            0,
            len(compressed) & 0xFF,
            (len(compressed) >> 8) & 0xFF,
            (len(compressed) >> 16) & 0xFF,
            1,  # LZ4
            len(chunk) & 0xFF,
            (len(chunk) >> 8) & 0xFF,
            (len(chunk) >> 16) & 0xFF,
        ])
        xorb_bytes.extend(header + compressed)

    data, offsets = deserialize_xorb_stream(bytes(xorb_bytes))

    assert data == b"chunk1chunk2chunk3"
    assert len(offsets) == 3
    assert offsets[0] == (0, 0)
    assert offsets[1] == (1, 6)   # chunk1 长度 6
    assert offsets[2] == (2, 12)  # chunk1 + chunk2 长度 12


def test_deserialize_truncated_header():
    """测试截断的 header（第一个 chunk）。"""
    truncated = bytes([0, 1, 2, 3])  # 少于 8 字节

    with pytest.raises(XorbFormatError, match="数据不完整"):
        deserialize_xorb_stream(truncated)


@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_deserialize_truncated_payload():
    """测试截断的 payload。"""
    import lz4.frame

    original = b"hello"
    compressed = lz4.frame.compress(original)

    # header 声称有 100 字节，但实际只给 10 字节
    header = bytes([0, 100, 0, 0, 1, len(original), 0, 0])
    xorb_bytes = header + compressed[:10]  # 只给部分数据

    with pytest.raises(XorbFormatError, match="数据越界"):
        deserialize_xorb_stream(xorb_bytes)


def test_deserialize_with_base_chunk_index():
    """测试带起始 chunk 索引。"""
    # 无压缩的简单测试
    data1 = b"hello"
    header = bytes([0, 5, 0, 0, 0, 5, 0, 0])  # scheme=0 (NONE)
    xorb_bytes = header + data1

    data, offsets = deserialize_xorb_stream(xorb_bytes, base_chunk_index=100)

    assert data == data1
    assert offsets[0] == (100, 0)  # chunk 100


# ============================================================================
# merge_xorb_parts 测试
# ============================================================================

def test_merge_xorb_parts_empty():
    """测试空 parts 列表。"""
    with pytest.raises(XorbFormatError, match="不能为空"):
        merge_xorb_parts([])


@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_merge_xorb_parts_sequential():
    """测试顺序合并多个 parts。"""
    import lz4.frame

    # Part 0: 2 chunks
    chunks_part0 = [b"chunk0", b"chunk1"]
    part0 = bytearray()
    for chunk in chunks_part0:
        compressed = lz4.frame.compress(chunk)
        header = bytes([0, len(compressed), 0, 0, 1, len(chunk), 0, 0])
        part0.extend(header + compressed)

    # Part 1: 2 chunks (第一个 chunk index 应该是 0，需要跳过)
    chunks_part1 = [b"chunk2", b"chunk3"]
    part1 = bytearray()
    for chunk in chunks_part1:
        compressed = lz4.frame.compress(chunk)
        header = bytes([0, len(compressed), 0, 0, 1, len(chunk), 0, 0])
        part1.extend(header + compressed)

    parts = [(0, bytes(part0)), (1, bytes(part1))]
    data, offsets = merge_xorb_parts(parts)

    assert data == b"chunk0chunk1chunk2chunk3"
    assert len(offsets) == 3  # part1 的第一个 chunk 被跳过
    assert offsets[0][0] == 0  # chunk 0
    assert offsets[1][0] == 1  # chunk 1
    assert offsets[2][0] == 1  # part1 的 chunk 1（跳过了 chunk 0）


# ============================================================================
# 集成测试：使用真实 xorb 数据
# ============================================================================

@pytest.mark.skipif(not is_lz4_available(), reason="需要 lz4 库")
def test_deserialize_real_xorb():
    """使用真实下载的 xorb 文件测试（如果存在）。"""
    from pathlib import Path

    xorb_path = Path("/data/data/com.termux/files/home/test.xorb")

    if not xorb_path.exists():
        pytest.skip("真实 xorb 文件不存在")

    xorb_bytes = xorb_path.read_bytes()

    # 解析
    data, offsets = deserialize_xorb_stream(xorb_bytes)

    # 验证结果
    assert len(data) == 63527244  # 已知的解压后大小
    assert len(offsets) == 796    # 已知的 chunk 数量
    assert offsets[0] == (0, 0)

    # 验证第一个 chunk 的偏移
    assert offsets[1] == (1, 131072)  # 第二个 chunk 在 131072 字节处


# ============================================================================
# 辅助函数测试
# ============================================================================

def test_is_lz4_available():
    """测试 LZ4 可用性检查。"""
    result = is_lz4_available()
    assert isinstance(result, bool)
