"""Merkle 树哈希计算（xet-core 兼容）。

基于 xet-core data_hash.rs + aggregated_hashes.rs 的完整实现：
- DATA_KEY keyed blake3 计算 chunk hash
- INTERNAL_NODE_HASH keyed blake3 计算内部节点 hash
- next_merge_cut 概率切分（分支因子 4）
- aggregated_node_hash 迭代合并直到单节点
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

BRANCHING_FACTOR = 4


def blake3_available() -> bool:
    return BLAKE3_AVAILABLE


def _datahash_hex(digest_32: bytes) -> str:
    """32 bytes blake3 输出 → 4×LE u64 → 64 hex 字符。"""
    u64s = struct.unpack('<4Q', digest_32)
    return ''.join(f'{u:016x}' for u in u64s)


def compute_data_hash(data: bytes) -> str:
    """用 DATA_KEY 计算 chunk 的 keyed blake3 哈希。"""
    if not BLAKE3_AVAILABLE:
        raise ImportError("需要 blake3 库来计算 xorb 哈希")
    digest = _blake3(data, key=DATA_KEY).digest()  # type: ignore[operator]
    return _datahash_hex(digest)


def compute_internal_node_hash(data: bytes) -> str:
    """用 INTERNAL_NODE_HASH_KEY 计算内部节点的 keyed blake3 哈希。"""
    if not BLAKE3_AVAILABLE:
        raise ImportError("需要 blake3 库来计算 xorb 哈希")
    digest = _blake3(data, key=INTERNAL_NODE_HASH_KEY).digest()  # type: ignore[operator]
    return _datahash_hex(digest)


def _next_merge_cut(hashes: List[Tuple[str, int]]) -> int:
    """概率切分：hash 最后 u64 % 4 == 0 时切分。

    最小 2 个一组，最大 2 * BRANCHING_FACTOR + 1 = 9 个一组。
    对应 xet-core aggregated_hashes.rs:next_merge_cut。
    """
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


def _merged_hash_of_sequence(group: List[Tuple[str, int]]) -> Tuple[str, int]:
    """合并一组 (hash, size) 为一个内部节点。

    格式："{hex_hash} : {size}\n" 拼接后 keyed blake3。
    对应 xet-core aggregated_hashes.rs:merged_hash_of_sequence。
    """
    buf = ''.join(f"{h} : {s}\n" for h, s in group).encode()
    total_len = sum(s for _, s in group)
    return (compute_internal_node_hash(buf), total_len)


def _aggregated_node_hash(chunks: List[Tuple[str, int]]) -> str:
    """迭代合并 (hash, size) 列表直到剩一个根节点。

    对应 xet-core aggregated_hashes.rs:aggregated_node_hash。
    """
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


def compute_xorb_hash(chunks: List[Tuple[bytes, int]]) -> str:
    """计算 xorb 的 Merkle 树哈希。

    Args:
        chunks: [(chunk_bytes, chunk_size), ...]

    Returns:
        64 hex 字符的 xorb hash
    """
    if not chunks:
        return '0' * 64
    hash_and_len = [(compute_data_hash(data), size) for data, size in chunks]
    return _aggregated_node_hash(hash_and_len)


def compute_file_hash(chunks: List[Tuple[bytes, int]]) -> str:
    """计算文件的 Merkle 树哈希（与 xorb hash 算法相同）。"""
    return compute_xorb_hash(chunks)
