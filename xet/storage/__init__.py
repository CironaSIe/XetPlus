"""XET Storage Layer - 文件写入、断点管理和哈希验证。

提供统一的文件写入接口、断点续传功能、以及 xet-core 兼容的 Merkle hash 链。
"""

from .writer import (
    FileWriter,
    SequentialWriter,
    GlobalWriter,
    create_writer,
)

from .checkpoint import (
    DownloadCheckpoint,
    CheckpointManager,
    create_checkpoint,
)

from .merkle_hash import (
    # 基本 hash 函数
    compute_data_hash,
    compute_data_hash_bytes,
    compute_internal_node_hash,
    compute_internal_node_hash_bytes,
    keyed_hash,

    # 转换工具
    hash_to_hex,
    hex_to_hash,
    bytes_to_u64s_le,

    # Merkle 树
    compute_xorb_hash,
    compute_xorb_hash_from_hashes,
    compute_file_hash,
    compute_file_hash_from_hashes,

    # 解压工具
    lz4_frame_decompress,
    bg4_regroup,
    bg4_lz4_decompress,

    # 状态查询
    blake3_available,

    # 常量
    DATA_KEY,
    INTERNAL_NODE_HASH_KEY,
    VERIFICATION_KEY,
    ZERO_SALT,
    BRANCHING_FACTOR,
)

__all__ = [
    # Writer
    'FileWriter',
    'SequentialWriter',
    'GlobalWriter',
    'create_writer',

    # Checkpoint
    'DownloadCheckpoint',
    'CheckpointManager',
    'create_checkpoint',

    # Hash
    'compute_data_hash',
    'compute_data_hash_bytes',
    'compute_internal_node_hash',
    'compute_internal_node_hash_bytes',
    'keyed_hash',
    'hash_to_hex',
    'hex_to_hash',
    'bytes_to_u64s_le',
    'compute_xorb_hash',
    'compute_xorb_hash_from_hashes',
    'compute_file_hash',
    'compute_file_hash_from_hashes',
    'lz4_frame_decompress',
    'bg4_regroup',
    'bg4_lz4_decompress',
    'blake3_available',
    'DATA_KEY',
    'INTERNAL_NODE_HASH_KEY',
    'VERIFICATION_KEY',
    'ZERO_SALT',
    'BRANCHING_FACTOR',
]
