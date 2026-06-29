"""MDB Shard 二进制格式反序列化器。

解析 HuggingFace XET MDB shard 二进制格式，提取 per-chunk expected hash 列表。
用于 D1 逐 chunk data_hash 校验。

参考：xet_core_structures/src/metadata_shard/
"""
import struct
from typing import List, Tuple, Optional, Dict

HEADER_TAG = bytes([
    0x48, 0x46, 0x52, 0x65, 0x70, 0x6F, 0x4D, 0x65,
    0x74, 0x61, 0x44, 0x61, 0x74, 0x61, 0x00, 0x55,
    0x69, 0x67, 0x45, 0x6A, 0x7B, 0x81, 0x57, 0x83,
    0xA5, 0xBD, 0xD9, 0x5C, 0xCD, 0xD1, 0x4A, 0xA9,
])

BOOKEND_HASH = bytes([0xFF]) * 32
ENTRY_SIZE = 48
FOOTER_SIZE = 200
HEADER_VERSION = 2
FOOTER_VERSION = 1

FILE_FLAG_WITH_VERIFICATION = 0x80000000
FILE_FLAG_WITH_METADATA_EXT = 0x40000000
CHUNK_FLAG_GLOBAL_DEDUP = 0x80000000


def _read_u32(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from('<I', data, off)[0], off + 4


def _read_u64(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from('<Q', data, off)[0], off + 8


def _read_hash(data: bytes, off: int) -> Tuple[bytes, int]:
    return data[off:off + 32], off + 32


def _is_bookend(h: bytes) -> bool:
    return h == BOOKEND_HASH


class XorbChunkEntry:
    __slots__ = ('chunk_hash', 'byte_start', 'unpacked_size', 'flags')

    def __init__(self, chunk_hash: bytes, byte_start: int, unpacked_size: int, flags: int):
        self.chunk_hash = chunk_hash
        self.byte_start = byte_start
        self.unpacked_size = unpacked_size
        self.flags = flags


class XorbBlock:
    __slots__ = ('xorb_hash', 'flags', 'chunks', 'num_bytes', 'num_bytes_on_disk')

    def __init__(self, xorb_hash: bytes, flags: int):
        self.xorb_hash = xorb_hash
        self.flags = flags
        self.chunks: List[XorbChunkEntry] = []
        self.num_bytes = 0
        self.num_bytes_on_disk = 0


class FileSegment:
    __slots__ = ('xorb_hash', 'flags', 'unpacked_bytes', 'chunk_start', 'chunk_end')

    def __init__(self, xorb_hash: bytes, flags: int, unpacked_bytes: int,
                 chunk_start: int, chunk_end: int):
        self.xorb_hash = xorb_hash
        self.flags = flags
        self.unpacked_bytes = unpacked_bytes
        self.chunk_start = chunk_start
        self.chunk_end = chunk_end


class FileEntry:
    __slots__ = ('file_hash', 'flags', 'segments', 'verifications', 'sha256')

    def __init__(self, file_hash: bytes, flags: int):
        self.file_hash = file_hash
        self.flags = flags
        self.segments: List[FileSegment] = []
        self.verifications: List[bytes] = []
        self.sha256: Optional[bytes] = None


class ShardData:
    def __init__(self):
        self.files: List[FileEntry] = []
        self.xorbs: List[XorbBlock] = []
        self.hmac_key: bytes = bytes(32)
        self.footer_offset: int = 0


def parse_shard(data: bytes) -> ShardData:
    if len(data) < 48 + FOOTER_SIZE:
        raise ValueError(f"Shard too small: {len(data)} bytes")

    tag = data[0:32]
    if tag != HEADER_TAG:
        raise ValueError(f"Invalid shard magic: {tag[:16].hex()}")

    version = struct.unpack_from('<Q', data, 32)[0]
    if version != HEADER_VERSION:
        raise ValueError(f"Expected header version {HEADER_VERSION}, got {version}")

    result = ShardData()

    _parse_footer(data, result)
    _parse_file_info(data, result)
    _parse_xorb_info(data, result)

    return result


def _parse_footer(data: bytes, result: ShardData):
    start = len(data) - FOOTER_SIZE
    o = start

    version, o = _read_u64(data, o)
    if version != FOOTER_VERSION:
        raise ValueError(f"Expected footer version {FOOTER_VERSION}, got {version}")

    file_info_offset, o = _read_u64(data, o)
    xorb_info_offset, o = _read_u64(data, o)
    file_lookup_offset, o = _read_u64(data, o)
    file_lookup_num, o = _read_u64(data, o)
    xorb_lookup_offset, o = _read_u64(data, o)
    xorb_lookup_num, o = _read_u64(data, o)
    chunk_lookup_offset, o = _read_u64(data, o)
    chunk_lookup_num, o = _read_u64(data, o)

    hmac_key, o = _read_hash(data, o)
    result.hmac_key = hmac_key

    timestamp, o = _read_u64(data, o)
    expiry, o = _read_u64(data, o)
    o += 48  # _buffer[6]

    stored_on_disk, o = _read_u64(data, o)
    materialized, o = _read_u64(data, o)
    stored, o = _read_u64(data, o)
    footer_offset, o = _read_u64(data, o)

    result.footer_offset = footer_offset
    result._f_file_info_off = file_info_offset
    result._f_xorb_info_off = xorb_info_offset


def _parse_file_info(data: bytes, result: ShardData):
    o = getattr(result, '_f_file_info_off', 0)

    while o + ENTRY_SIZE <= len(data):
        file_hash, o = _read_hash(data, o)
        file_flags, o = _read_u32(data, o)
        num_entries, o = _read_u32(data, o)
        _unused, o = _read_u64(data, o)

        if _is_bookend(file_hash):
            break

        fe = FileEntry(file_hash, file_flags)
        has_v = (file_flags & FILE_FLAG_WITH_VERIFICATION) != 0
        has_m = (file_flags & FILE_FLAG_WITH_METADATA_EXT) != 0

        for _ in range(num_entries):
            xorb_hash, o = _read_hash(data, o)
            xf, o = _read_u32(data, o)
            ub, o = _read_u32(data, o)
            cs, o = _read_u32(data, o)
            ce, o = _read_u32(data, o)
            fe.segments.append(FileSegment(xorb_hash, xf, ub, cs, ce))

        if has_v:
            for _ in range(num_entries):
                rh, o = _read_hash(data, o)
                o += 16  # _unused
                fe.verifications.append(rh)

        if has_m:
            sha, o = _read_hash(data, o)
            o += 16  # _unused
            fe.sha256 = sha

        result.files.append(fe)


def _parse_xorb_info(data: bytes, result: ShardData):
    o = getattr(result, '_f_xorb_info_off', 0)

    while o + ENTRY_SIZE <= len(data):
        xorb_hash, o = _read_hash(data, o)
        xorb_flags, o = _read_u32(data, o)
        num_entries, o = _read_u32(data, o)
        num_bytes, o = _read_u32(data, o)
        num_bytes_disk, o = _read_u32(data, o)

        if _is_bookend(xorb_hash):
            break

        xb = XorbBlock(xorb_hash, xorb_flags)
        xb.num_bytes = num_bytes
        xb.num_bytes_on_disk = num_bytes_disk

        for _ in range(num_entries):
            ch, o = _read_hash(data, o)
            bs, o = _read_u32(data, o)
            us, o = _read_u32(data, o)
            fl, o = _read_u32(data, o)
            _un, o = _read_u32(data, o)
            xb.chunks.append(XorbChunkEntry(ch, bs, us, fl))

        result.xorbs.append(xb)


def get_xorb_chunk_hashes(shard: ShardData, xorb_hash: bytes) -> List[bytes]:
    for xb in shard.xorbs:
        if xb.xorb_hash == xorb_hash:
            return [c.chunk_hash for c in xb.chunks]
    return []


def get_file_chunk_hashes(shard: ShardData, file_hash: bytes) -> List[bytes]:
    for fe in shard.files:
        if fe.file_hash == file_hash:
            hashes = []
            for seg in fe.segments:
                for xb in shard.xorbs:
                    if xb.xorb_hash == seg.xorb_hash:
                        for c in xb.chunks[seg.chunk_start:seg.chunk_end]:
                            hashes.append(c.chunk_hash)
                        break
            return hashes
    return []
