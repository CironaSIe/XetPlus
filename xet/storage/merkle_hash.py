"""Merkle 树哈希计算（xet-core 兼容）。

基于 xet-core data_hash.rs + aggregated_hashes.rs 的完整实现：
- compute_data_hash: DATA_KEY keyed blake3 计算 chunk hash
- compute_internal_node_hash: INTERNAL_NODE_HASH keyed blake3 计算内部节点 hash
- aggregated_node_hash: next_merge_cut (BF=4) 概率切分，迭代合并到单根
- xorb_hash: Merkle 树根 (no HMAC)
- file_hash: aggregated_node_hash → HMAC(zero_salt, root_bytes)
- LZ4/BG4 解压工具 (scheme 1/2)
"""
import struct
import logging
from typing import List, Tuple

try:
    from blake3 import blake3 as _blake3  # type: ignore[import]
    BLAKE3_AVAILABLE = True
except ImportError:
    BLAKE3_AVAILABLE = False

logger = logging.getLogger(__name__)

DATA_KEY = bytes([
    102, 151, 245, 119, 91, 149, 80, 222,
    49, 53, 203, 172, 165, 151, 24, 28,
    157, 228, 33, 16, 155, 235, 43, 88,
    180, 208, 176, 75, 147, 173, 242, 41,
])

INTERNAL_NODE_HASH_KEY = bytes([
    1, 126, 197, 199, 165, 71, 41, 150,
    253, 148, 102, 102, 180, 138, 2, 230,
    93, 221, 83, 111, 55, 199, 109, 210,
    248, 99, 82, 230, 74, 83, 113, 63,
])

VERIFICATION_KEY = bytes([
    127, 24, 87, 214, 206, 86, 237, 102,
    18, 127, 249, 19, 231, 165, 195, 243,
    164, 205, 38, 213, 181, 219, 73, 230,
    65, 36, 152, 127, 40, 251, 148, 195,
])

ZERO_SALT = bytes(32)

BRANCHING_FACTOR = 4


def blake3_available() -> bool:
    return BLAKE3_AVAILABLE


# ============================================================
# 字节/hex 转换工具
# ============================================================

def _datahash_hex(digest_32: bytes) -> str:
    """32 bytes → 4×LE u64 → 64 hex 字符。"""
    u64s = struct.unpack('<4Q', digest_32)
    return ''.join(f'{u:016x}' for u in u64s)


def hash_to_hex(h: bytes) -> str:
    return _datahash_hex(h)


def hex_to_hash(hex_str: str) -> bytes:
    """64 hex chars → 32 bytes (4×LE u64)。"""
    u64s = [int(hex_str[i:i+16], 16) for i in range(0, 64, 16)]
    return struct.pack('<4Q', *u64s)


def bytes_to_u64s_le(b: bytes) -> Tuple[int, int, int, int]:
    return struct.unpack('<4Q', b)


# ============================================================
# 1. compute_data_hash
# ============================================================

def compute_data_hash(data: bytes) -> str:
    """返回 64 hex 字符的 chunk hash。"""
    return hash_to_hex(compute_data_hash_bytes(data))


def compute_data_hash_bytes(data: bytes) -> bytes:
    """返回 32 字节的 chunk hash（raw bytes）。"""
    if not BLAKE3_AVAILABLE:
        raise ImportError("需要 blake3 库来计算 xorb 哈希")
    return _blake3(data, key=DATA_KEY).digest()


# ============================================================
# 2. compute_internal_node_hash
# ============================================================

def compute_internal_node_hash(data: bytes) -> str:
    """返回 64 hex 字符的内部节点 hash。"""
    return hash_to_hex(compute_internal_node_hash_bytes(data))


def compute_internal_node_hash_bytes(data: bytes) -> bytes:
    if not BLAKE3_AVAILABLE:
        raise ImportError("需要 blake3 库来计算 xorb 哈希")
    return _blake3(data, key=INTERNAL_NODE_HASH_KEY).digest()


# ============================================================
# 3. keyed blake3 通用（用于 file_hash、range_hash 的 HMAC 步骤）
# ============================================================

def keyed_hash(data: bytes, key: bytes) -> bytes:
    if not BLAKE3_AVAILABLE:
        raise ImportError("需要 blake3 库来计算 xorb 哈希")
    return _blake3(data, key=key).digest()


# ============================================================
# 4. write_hash_entry: "{hex_hash} : {size}\n"
# ============================================================

def _write_hash_entry(hash_hex: str, size: int) -> str:
    return f"{hash_hex} : {size}\n"


# ============================================================
# 5. next_merge_cut: 概率切分 (BF=4)
# ============================================================

def _next_merge_cut(hashes: List[Tuple[str, int]]) -> int:
    n = len(hashes)
    if n <= 2:
        return n
    end = min(2 * BRANCHING_FACTOR + 1, n)
    for i in range(2, end):
        h_hex = hashes[i][0]
        last_u64 = int(h_hex[-16:], 16)
        if last_u64 % BRANCHING_FACTOR == 0:
            return i + 1
    return end


# ============================================================
# 6. merged_hash_of_sequence
# ============================================================

def _merged_hash_of_sequence(group: List[Tuple[str, int]]) -> Tuple[str, int]:
    buf = ''.join(_write_hash_entry(h, s) for h, s in group).encode()
    total_len = sum(s for _, s in group)
    return (hash_to_hex(compute_internal_node_hash_bytes(buf)), total_len)


# ============================================================
# 7. aggregated_node_hash
# ============================================================

def _aggregated_node_hash(chunks: List[Tuple[str, int]]) -> str:
    if not chunks:
        return '0' * 64
    hv = list(chunks)
    while len(hv) > 1:
        new_hv: List[Tuple[str, int]] = []
        read_idx = 0
        while read_idx < len(hv):
            cut = read_idx + _next_merge_cut(hv[read_idx:])
            merged = _merged_hash_of_sequence(hv[read_idx:cut])
            new_hv.append(merged)
            read_idx = cut
        hv = new_hv
    return hv[0][0]


# ============================================================
# 8. compute_xorb_hash: Merkle 树根（无 HMAC）
# ============================================================

def compute_xorb_hash(chunks: List[Tuple[bytes, int]]) -> str:
    if not chunks:
        return '0' * 64
    hash_and_len = [(compute_data_hash(data), size) for data, size in chunks]
    return _aggregated_node_hash(hash_and_len)


# ============================================================
# 9. compute_file_hash: aggregated_node_hash → HMAC(zero_salt)
# ============================================================

def compute_file_hash(chunks: List[Tuple[bytes, int]]) -> str:
    """文件级 hash：Merkle 根带 HMAC 加盐。

    与 xorb_hash 的区别：额外经过 blake3(keyed=ZERO_SALT, root_bytes)。
    """
    if not chunks:
        return '0' * 64
    hash_and_len = [(compute_data_hash(data), size) for data, size in chunks]
    root_hex = _aggregated_node_hash(hash_and_len)
    root_bytes = hex_to_hash(root_hex)
    hmac_bytes = keyed_hash(root_bytes, key=ZERO_SALT)
    return hash_to_hex(hmac_bytes)


# ============================================================
# 10. compute_file_hash_from_hashes: 已知 chunk hash 时直接计算
# ============================================================

def compute_file_hash_from_hashes(chunks: List[Tuple[str, int]]) -> str:
    """直接使用 chunk hash hex 字符串和 size 计算 file_hash。"""
    if not chunks:
        return '0' * 64
    root_hex = _aggregated_node_hash(chunks)
    root_bytes = hex_to_hash(root_hex)
    hmac_bytes = keyed_hash(root_bytes, key=ZERO_SALT)
    return hash_to_hex(hmac_bytes)


def compute_xorb_hash_from_hashes(chunks: List[Tuple[str, int]]) -> str:
    if not chunks:
        return '0' * 64
    return _aggregated_node_hash(chunks)


# ============================================================
# 11. LZ4 Frame 解压 (scheme 1)
# ============================================================

def lz4_frame_decompress(data: bytes) -> bytes:
    import lz4.frame
    return lz4.frame.decompress(data)


# ============================================================
# 12. BG4 Regroup (scheme 2)
# ============================================================

def bg4_regroup(g: bytes) -> bytes:
    """将 BG4 分组重新交织回原始排列。"""
    n = len(g)
    split = n // 4
    rem = n % 4
    g0_end = split + (1 if rem >= 1 else 0)
    g1_end = g0_end + split + (1 if rem >= 2 else 0)
    g2_end = g1_end + split + (1 if rem >= 3 else 0)
    g0 = g[:g0_end]
    g1 = g[g0_end:g1_end]
    g2 = g[g1_end:g2_end]
    g3 = g[g2_end:]
    data = bytearray(n)
    for i in range(split):
        data[4*i] = g0[i]
        data[4*i+1] = g1[i]
        data[4*i+2] = g2[i]
        data[4*i+3] = g3[i]
    if rem >= 1:
        data[4*split] = g0[split]
    if rem >= 2:
        data[4*split+1] = g1[split]
    if rem >= 3:
        data[4*split+2] = g2[split]
    return bytes(data)


def bg4_lz4_decompress(data: bytes) -> bytes:
    """BG4 + LZ4 Frame 解压 (scheme 2)。"""
    import lz4.frame
    grouped = lz4.frame.decompress(data)
    return bg4_regroup(grouped)
