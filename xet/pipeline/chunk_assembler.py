"""数据组装器 - 解压 xorb 并组装最终文件。

负责解压 xorb、应用 term operations（copy/reference）、流式写入目标文件。
"""
import logging
from pathlib import Path
from typing import Dict, Optional

from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.progress_tracker import ProgressTracker

logger = logging.getLogger(__name__)


class ChunkAssembler:
    """文件数据组装器。

    职责：
    - 解压所有 xorb → chunks
    - 应用 term operations（copy/reference）
    - 流式写入目标文件

    Attributes:
        temp_dir: 临时目录（用于存储中间文件，如果需要）
    """

    def __init__(self, temp_dir: Optional[Path] = None):
        """初始化数据组装器。

        Args:
            temp_dir: 临时目录路径
        """
        self.temp_dir = temp_dir
        if self.temp_dir:
            self.temp_dir.mkdir(parents=True, exist_ok=True)

    def assemble_file(
        self,
        recon: QueryReconstructionResponse,
        xorb_data_map: Dict[str, bytes],
        output_path: Path,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> None:
        """组装最终文件。

        Args:
            recon: Reconstruction 响应
            xorb_data_map: {xorb_hash: compressed_xorb_data} 映射
            output_path: 输出文件路径
            progress_tracker: 进度跟踪器（可选）

        Raises:
            ValueError: 数据缺失或格式错误
            IOError: 文件写入失败
        """
        logger.info(f"[ChunkAssembler] 开始组装文件: {output_path}")

        # 1. 解压所有 xorb → 构建 chunk 缓存
        chunk_cache = self._decompress_all_xorbs(xorb_data_map)
        logger.info(f"[ChunkAssembler] 解压完成，共 {len(chunk_cache)} 个 chunk")

        # 2. 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 3. 流式写入文件（应用 term operations）
        total_written = 0

        with open(output_path, 'wb') as f:
            # 跳过 offset_into_first_range（如果有）
            offset = recon.offset_into_first_range
            if offset > 0:
                logger.debug(
                    f"[ChunkAssembler] 跳过 offset_into_first_range: {offset} bytes"
                )

            # 处理每个 term
            for idx, term in enumerate(recon.terms):
                if term.op == "copy":
                    # Copy 操作：从 chunk 读取数据
                    chunk_data = self._get_chunk_data(
                        chunk_hash=term.chunk_hash,
                        chunk_cache=chunk_cache,
                    )

                    # 应用 offset 和 length
                    start = term.offset
                    end = start + term.unpacked_length
                    segment = chunk_data[start:end]

                    if len(segment) != term.unpacked_length:
                        raise ValueError(
                            f"[ChunkAssembler] Chunk {term.chunk_hash[:16]}... "
                            f"数据长度不匹配: 期望 {term.unpacked_length}, "
                            f"实际 {len(segment)}"
                        )

                    f.write(segment)
                    total_written += len(segment)

                elif term.op == "reference":
                    # Reference 操作：从已写入的文件内容复制
                    # 1. 刷新缓冲区
                    f.flush()

                    # 2. 定位到 reference_offset
                    f.seek(term.reference_offset)

                    # 3. 读取数据
                    data = f.read(term.unpacked_length)

                    if len(data) != term.unpacked_length:
                        raise ValueError(
                            f"[ChunkAssembler] Reference 读取长度不匹配: "
                            f"期望 {term.unpacked_length}, 实际 {len(data)}"
                        )

                    # 4. 回到文件末尾
                    f.seek(0, 2)

                    # 5. 写入引用的数据
                    f.write(data)
                    total_written += len(data)

                else:
                    raise ValueError(f"[ChunkAssembler] 未知操作: {term.op}")

                # 更新进度
                if progress_tracker:
                    progress_tracker.increment_assembled(term.unpacked_length)

                # 每 100 个 term 记录一次进度
                if (idx + 1) % 100 == 0:
                    logger.debug(
                        f"[ChunkAssembler] 处理进度: {idx + 1}/{len(recon.terms)} terms"
                    )

        logger.info(
            f"[ChunkAssembler] 文件组装完成: {output_path} "
            f"({total_written} bytes, {len(recon.terms)} terms)"
        )

    def _decompress_all_xorbs(
        self, xorb_data_map: Dict[str, bytes]
    ) -> Dict[str, bytes]:
        """解压所有 xorb，返回 {chunk_hash: decompressed_data} 缓存。

        调用 merkle-hash-rust 库进行解压。

        Args:
            xorb_data_map: {xorb_hash: compressed_xorb_data}

        Returns:
            {chunk_hash: chunk_data} 映射

        Raises:
            ImportError: merkle-hash-rust 未安装
            RuntimeError: 解压失败
        """
        try:
            from xet.storage.merkle_hash import decompress_xorb
        except ImportError as e:
            raise ImportError(
                "[ChunkAssembler] 需要 merkle-hash-rust 库: pip install merkle-hash-rust"
            ) from e

        chunk_cache = {}

        for xorb_hash, compressed_data in xorb_data_map.items():
            logger.debug(
                f"[ChunkAssembler] 解压 xorb: {xorb_hash[:16]}... "
                f"({len(compressed_data)} bytes)"
            )

            # 调用 Rust 解压函数
            try:
                chunks = decompress_xorb(compressed_data)

                # 合并到缓存
                for chunk_hash, chunk_data in chunks.items():
                    chunk_cache[chunk_hash] = chunk_data

                logger.debug(
                    f"[ChunkAssembler] Xorb {xorb_hash[:16]}... "
                    f"解压得到 {len(chunks)} 个 chunk"
                )

            except Exception as e:
                raise RuntimeError(
                    f"[ChunkAssembler] 解压 xorb 失败: {xorb_hash[:16]}..., {e}"
                ) from e

        return chunk_cache

    def _get_chunk_data(
        self, chunk_hash: str, chunk_cache: Dict[str, bytes]
    ) -> bytes:
        """从缓存获取 chunk 数据。

        Args:
            chunk_hash: Chunk 的 MerkleHash
            chunk_cache: Chunk 缓存

        Returns:
            Chunk 数据

        Raises:
            ValueError: Chunk 缺失
        """
        if chunk_hash not in chunk_cache:
            raise ValueError(
                f"[ChunkAssembler] Chunk 缺失: {chunk_hash[:16]}... "
                f"(可能 xorb 解压不完整或 reconstruction 数据错误)"
            )

        return chunk_cache[chunk_hash]
