"""Xorb 二进制格式解析（纯函数）。

解析 xorb (XET Object) 的二进制格式，提取压缩的 chunk 数据。
所有函数都是纯函数，无副作用，易于测试。

支持三种压缩方案：
- 0: None（原始数据）
- 1: LZ4 标准压缩
- 2: ByteGrouping4LZ4（4字节分组 + LZ4，优化浮点数据）

Chunk Header 格式（固定 8 字节）：
┌─────────┬──────────────┬────────────┬──────────────────┐
│ version │ compressed   │ comp_scheme│ uncompressed     │
│  (1B)   │ length (3B)  │   (1B)     │ length (3B)      │
└─────────┴──────────────┴────────────┴──────────────────┘
"""
from __future__ import annotations

from typing import List, Tuple, Dict
from itertools import zip_longest

try:
    import lz4.frame  # type: ignore[import-untyped]
    LZ4_AVAILABLE = True
except ImportError:
    LZ4_AVAILABLE = False


# 压缩方案常量
COMPRESSION_NONE = 0
COMPRESSION_LZ4 = 1
COMPRESSION_BYTE_GROUPING_4_LZ4 = 2


class XorbFormatError(ValueError):
    """Xorb 格式错误异常。"""
    pass


class XorbCompressionError(RuntimeError):
    """Xorb 解压错误异常。"""
    pass


def parse_chunk_header(data: bytes, offset: int = 0) -> Dict[str, int]:
    """解析 xorb chunk header（8 字节）。

    Args:
        data: 包含 header 的字节数据
        offset: header 在 data 中的起始偏移（默认 0）

    Returns:
        包含以下字段的字典：
        - version: 版本号（当前为 0）
        - compressed_length: 压缩数据长度（字节）
        - compression_scheme: 压缩方案（0/1/2）
        - decompressed_length: 解压后数据长度（字节）

    Raises:
        XorbFormatError: 如果数据不足 8 字节

    Example:
        >>> header_bytes = bytes([0, 0x47, 0x71, 0x00, 1, 0x00, 0x00, 0x02])
        >>> header = parse_chunk_header(header_bytes)
        >>> header['compressed_length']
        28999
        >>> header['compression_scheme']
        1
    """
    if len(data) < offset + 8:
        raise XorbFormatError(
            f"Chunk header 需要 8 字节，但只有 {len(data) - offset} 字节可用"
        )

    header = data[offset:offset + 8]

    return {
        'version': header[0],
        'compressed_length': int.from_bytes(header[1:4], 'little'),
        'compression_scheme': header[4],
        'decompressed_length': int.from_bytes(header[5:8], 'little'),
    }


def decompress_chunk(
    compressed_data: bytes,
    scheme: int,
    expected_size: int
) -> bytes:
    """根据压缩方案解压单个 chunk。

    Args:
        compressed_data: 压缩数据
        scheme: 压缩方案编号（0=None, 1=LZ4, 2=ByteGrouping4LZ4）
        expected_size: 期望的解压大小（用于验证）

    Returns:
        解压后的原始数据

    Raises:
        XorbFormatError: 不支持的压缩方案
        XorbCompressionError: 解压失败或大小不匹配
        ImportError: LZ4 库未安装（scheme=1 或 2 时）

    Example:
        >>> # 无压缩
        >>> data = b"hello"
        >>> decompress_chunk(data, COMPRESSION_NONE, 5) == data
        True
    """
    if scheme == COMPRESSION_NONE:
        # 无压缩，直接返回
        if len(compressed_data) != expected_size:
            raise XorbCompressionError(
                f"无压缩数据大小不匹配: 期望 {expected_size}, 实际 {len(compressed_data)}"
            )
        return compressed_data

    elif scheme == COMPRESSION_LZ4:
        # 标准 LZ4 压缩
        return _decompress_lz4(compressed_data, expected_size)

    elif scheme == COMPRESSION_BYTE_GROUPING_4_LZ4:
        # ByteGrouping4LZ4：先 LZ4 解压，再 4-byte 反分组
        lz4_data = _decompress_lz4(compressed_data, expected_size)
        return _ungrouping_4byte(lz4_data)

    else:
        raise XorbFormatError(f"不支持的压缩方案: {scheme}")


def _decompress_lz4(compressed: bytes, expected_size: int) -> bytes:
    """使用 LZ4 解压数据。

    Args:
        compressed: LZ4 压缩数据
        expected_size: 期望的解压大小（用于验证）

    Returns:
        解压后的数据

    Raises:
        ImportError: lz4 库未安装
        XorbCompressionError: LZ4 解压失败
    """
    if not LZ4_AVAILABLE:
        raise ImportError(
            "需要 lz4 库来解压 xorb 数据。请运行: pip install lz4"
        )

    try:
        decompressed = lz4.frame.decompress(compressed)
        return decompressed
    except Exception as e:
        raise XorbCompressionError(f"LZ4 解压失败: {e}") from e


def _ungrouping_4byte(grouped: bytes) -> bytes:
    """ByteGrouping4LZ4 的反变换。

    将 4 组交错排列的字节还原为原始顺序。

    分组过程（正向）：
    - 将数据分成 4 组（round-robin 分配到 group 0-3）
    - 依次输出 group 0, group 1, group 2, group 3

    反分组过程（本函数）：
    - 将数据重新交错回原始顺序

    Example:
        原始: [a0, a1, a2, a3, b0, b1, b2, b3, c0, c1]
        分组后: [a0, b0, c0, a1, b1, c1, a2, b2, c2, a3, b3]
        反分组后: [a0, a1, a2, a3, b0, b1, b2, b3, c0, c1]

    Args:
        grouped: 经过 ByteGrouping4 的数据

    Returns:
        反变换后的原始数据
    """
    n = len(grouped)
    if n == 0:
        return b''

    group_size = n // 4
    remainder = n % 4

    # 分成 4 组
    groups = []
    pos = 0
    for i in range(4):
        # 前 remainder 个组多一个字节
        extra = 1 if i < remainder else 0
        groups.append(grouped[pos:pos + group_size + extra])
        pos += group_size + extra

    # 交错合并回原始顺序
    result = bytearray()
    for quad in zip_longest(*groups, fillvalue=None):
        for b in quad:
            if b is not None:
                result.append(b)

    return bytes(result)


def deserialize_xorb_stream(
    xorb_bytes: bytes,
    base_chunk_index: int = 0
) -> Tuple[bytes, List[Tuple[int, int]]]:
    """解析完整 xorb 数据流。

    按序解析所有 chunk，解压后返回拼接的数据和偏移信息。

    Args:
        xorb_bytes: 原始 xorb 字节数据（来自 HTTP 下载）
        base_chunk_index: 起始 chunk 索引（用于 multipart 合并）

    Returns:
        (data, chunk_offsets) 元组：
        - data: 所有解压后的 chunk 拼接数据
        - chunk_offsets: [(chunk_index, byte_offset), ...] 列表

    Raises:
        XorbFormatError: 数据格式无效
        XorbCompressionError: 解压失败
        ImportError: 需要但未安装 lz4 库

    Example:
        >>> xorb_data = b"..."  # 从文件或 HTTP 读取
        >>> data, offsets = deserialize_xorb_stream(xorb_data)
        >>> print(f"解压后: {len(data)} bytes, {len(offsets)} chunks")
    """
    if not xorb_bytes:
        raise XorbFormatError("xorb_bytes 不能为空")

    chunk_offsets: List[Tuple[int, int]] = []
    all_data = bytearray()
    chunk_index = base_chunk_index
    offset = 0

    while offset < len(xorb_bytes):
        # 检查是否有足够的字节读取 header
        remaining = len(xorb_bytes) - offset
        if remaining < 8:
            # 如果是第一个 chunk 就不完整，则是错误
            if chunk_index == base_chunk_index:
                raise XorbFormatError(
                    f"数据不完整: 需要至少 8 字节 header, 但只有 {len(xorb_bytes)} 字节"
                )
            # 否则可能是尾部填充，警告后跳过
            break

        # 解析 header
        try:
            header = parse_chunk_header(xorb_bytes, offset)
        except XorbFormatError as e:
            if chunk_index == base_chunk_index:
                raise  # 第一个 chunk 必须完整
            break  # 后续 chunk 不完整则忽略

        # 计算数据位置
        data_start = offset + 8
        data_end = data_start + header['compressed_length']

        # 边界检查
        if data_end > len(xorb_bytes):
            raise XorbFormatError(
                f"Chunk #{chunk_index} 数据越界: "
                f"需要 {data_end} bytes, 只有 {len(xorb_bytes)} bytes"
            )

        # 提取压缩数据
        compressed_data = xorb_bytes[data_start:data_end]

        # 解压
        raw_data = decompress_chunk(
            compressed_data,
            header['compression_scheme'],
            header['decompressed_length']
        )

        # 验证解压大小
        if len(raw_data) != header['decompressed_length']:
            raise XorbCompressionError(
                f"Chunk #{chunk_index} 解压大小不匹配: "
                f"期望 {header['decompressed_length']}, 实际 {len(raw_data)}"
            )

        # 记录偏移并追加数据
        chunk_offsets.append((chunk_index, len(all_data)))
        all_data.extend(raw_data)
        chunk_index += 1
        offset = data_end

    return bytes(all_data), chunk_offsets


def merge_xorb_parts(
    parts: List[Tuple[int, bytes]]
) -> Tuple[bytes, List[Tuple[int, int]]]:
    """合并 multipart xorb 数据。

    按照 XET.SPEC.md §2.5 的算法：
    - 第一个 part 直接使用其 chunk_offsets
    - 后续 part 需要跳过首位的 chunk index 0，并 rebase 到全局偏移

    Args:
        parts: [(part_index, xorb_bytes), ...] 列表，按顺序排列

    Returns:
        (data, chunk_offsets) 元组，格式同 deserialize_xorb_stream

    Raises:
        XorbFormatError: 任何 part 反序列化失败

    Example:
        >>> parts = [(0, part0_bytes), (1, part1_bytes)]
        >>> data, offsets = merge_xorb_parts(parts)
    """
    if not parts:
        raise XorbFormatError("parts 列表不能为空")

    all_data = bytearray()
    all_chunk_offsets: List[Tuple[int, int]] = []

    for part_idx, part_bytes in parts:
        # 反序列化单个 part
        part_data, part_offsets = deserialize_xorb_stream(part_bytes)

        base_offset = len(all_data)

        if part_idx == 0:
            # 第一个 part: 使用原始偏移
            all_chunk_offsets.extend(part_offsets)
        else:
            # 后续 part: rebase 偏移，跳过首位的 0
            for chunk_idx, byte_offset in part_offsets:
                if chunk_idx == 0:
                    continue  # 跳过首位的 0（相对于新 part）
                all_chunk_offsets.append((chunk_idx, byte_offset + base_offset))

        # 追加数据
        all_data.extend(part_data)

    return bytes(all_data), all_chunk_offsets


def is_lz4_available() -> bool:
    """检查 LZ4 库是否可用。

    Returns:
        如果可以导入 lz4 则返回 True
    """
    return LZ4_AVAILABLE
