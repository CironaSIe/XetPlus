"""Xorb 解压适配层。

将 ~/xet.py 的 xorb_deserializer 适配到 XET+ 的 ChunkAssembler 接口。
"""
import logging
from typing import Dict

from .xorb_deserializer import XorbDeserializer
from .merkle_hash import compute_data_hash

logger = logging.getLogger(__name__)


def decompress_xorb(xorb_bytes: bytes) -> Dict[str, bytes]:
    """解压 xorb 容器，提取内部的 chunks。

    这是 XET+ ChunkAssembler 期望的接口，返回 {chunk_hash: chunk_data} 映射。

    Args:
        xorb_bytes: 压缩的 xorb 数据

    Returns:
        {chunk_hash: chunk_data} 映射，其中 chunk_hash 是 64 字符的十六进制字符串

    Raises:
        ValueError: xorb 数据格式错误
        ImportError: 缺少 lz4 或 blake3 库
        RuntimeError: 解压失败
    """
    logger.debug(f"[XorbAdapter] 开始解压 xorb: {len(xorb_bytes)} bytes")

    # 1. 使用 ~/xet.py 的反序列化
    xorb_data = XorbDeserializer.deserialize(xorb_bytes)

    logger.debug(
        f"[XorbAdapter] 反序列化完成: {len(xorb_data.chunk_offsets)} chunks, "
        f"{len(xorb_data.data)} bytes total"
    )

    # 2. 提取每个 chunk 并计算 hash
    chunks = {}

    for i, (chunk_idx, byte_offset) in enumerate(xorb_data.chunk_offsets):
        # 确定 chunk 结束位置
        if i + 1 < len(xorb_data.chunk_offsets):
            next_offset = xorb_data.chunk_offsets[i + 1][1]
        else:
            next_offset = len(xorb_data.data)

        # 提取 chunk 数据
        chunk_data = xorb_data.data[byte_offset:next_offset]

        # 计算 chunk hash（使用 keyed blake3）
        chunk_hash = compute_data_hash(chunk_data)

        chunks[chunk_hash] = chunk_data

        # 每 100 个 chunk 记录一次进度
        if (i + 1) % 100 == 0:
            logger.debug(
                f"[XorbAdapter] 处理进度: {i + 1}/{len(xorb_data.chunk_offsets)} chunks"
            )

    logger.info(
        f"[XorbAdapter] 解压完成: {len(chunks)} chunks, "
        f"avg size: {len(xorb_data.data) // len(chunks) if chunks else 0} bytes"
    )

    return chunks
