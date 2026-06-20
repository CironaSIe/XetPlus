"""XET 协议层 - 纯函数实现。

所有函数无副作用，易于测试和维护。
"""

from .xorb_format import (
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

__all__ = [
    'parse_chunk_header',
    'decompress_chunk',
    'deserialize_xorb_stream',
    'merge_xorb_parts',
    'is_lz4_available',
    'COMPRESSION_NONE',
    'COMPRESSION_LZ4',
    'COMPRESSION_BYTE_GROUPING_4_LZ4',
    'XorbFormatError',
    'XorbCompressionError',
]
