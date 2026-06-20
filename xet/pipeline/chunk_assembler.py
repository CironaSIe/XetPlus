"""数据组装器 - 解压 xorb 并组装最终文件。

负责解压 xorb、按 terms 顺序拼接数据、流式写入目标文件。
基于 ~/xet.py/xet/reconstructor.py 的实现逻辑。
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
    - 解压所有 xorb → XorbBlockData
    - 按 terms 顺序提取数据片段
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

        按照 ~/xet.py 的逻辑：
        1. 解压所有 xorb → 构建 xorb_hash → XorbBlockData 缓存
        2. 按 terms 顺序从 xorb 提取数据片段并写入文件
        3. 第一个 term 需要跳过 offset_into_first_range

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

        # 1. 解压所有 xorb → 构建 xorb_hash → XorbBlockData 缓存
        xorb_cache = self._decompress_all_xorbs_to_xorb_data(xorb_data_map, recon)
        logger.info(f"[ChunkAssembler] 解压完成，共 {len(xorb_cache)} 个 xorb")

        # 2. 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 3. 按 terms 顺序重建文件
        total_written = 0

        with open(output_path, 'wb') as f:
            for idx, term in enumerate(recon.terms):
                # 从缓存中获取 xorb 数据
                if term.hash not in xorb_cache:
                    raise ValueError(
                        f"[ChunkAssembler] Term #{idx} 引用的 xorb 不在缓存中: {term.hash[:16]}..."
                    )

                xorb_data = xorb_cache[term.hash]

                # 使用 dict 提高查询效率（O(1) vs O(n)）
                chunk_offset_dict = dict(xorb_data.chunk_offsets)

                # 获取起始 chunk 的字节偏移
                start_chunk_idx = term.range.start
                start_byte = chunk_offset_dict.get(start_chunk_idx)

                if start_byte is None:
                    raise ValueError(
                        f"[ChunkAssembler] Chunk {start_chunk_idx} 未在 xorb {term.hash[:16]}... 中找到"
                    )

                # 使用 unpacked_length 计算结束位置
                end_byte = start_byte + term.unpacked_length

                # 边界检查
                if end_byte > len(xorb_data.data):
                    raise ValueError(
                        f"[ChunkAssembler] Term #{idx} 数据范围越界: "
                        f"start={start_byte}, end={end_byte}, data_len={len(xorb_data.data)}"
                    )

                # 提取数据片段
                segment = xorb_data.data[start_byte:end_byte]

                # 第一个 term 需要跳过 offset_into_first_range
                if idx == 0 and recon.offset_into_first_range > 0:
                    offset = recon.offset_into_first_range
                    if offset >= len(segment):
                        raise ValueError(
                            f"[ChunkAssembler] offset_into_first_range ({offset}) >= "
                            f"第一个 term 长度 ({len(segment)})"
                        )
                    segment = segment[offset:]
                    logger.debug(
                        f"[ChunkAssembler] 第一个 term 跳过 offset: {offset} bytes"
                    )

                # 写入文件
                f.write(segment)
                total_written += len(segment)

                # 更新进度
                if progress_tracker:
                    progress_tracker.increment_assembled(len(segment))

                # 每 100 个 term 记录一次进度
                if (idx + 1) % 100 == 0:
                    logger.debug(
                        f"[ChunkAssembler] 处理进度: {idx + 1}/{len(recon.terms)} terms"
                    )

        logger.info(
            f"[ChunkAssembler] 文件组装完成: {output_path} "
            f"({total_written} bytes, {len(recon.terms)} terms)"
        )

    def _decompress_all_xorbs_to_xorb_data(
        self, xorb_data_map: Dict[str, bytes], recon: QueryReconstructionResponse
    ) -> Dict[str, "XorbBlockData"]:
        """解压所有 xorb，返回 {xorb_hash: XorbBlockData} 缓存。

        从 recon.fetch_info 获取每个 xorb segment 的 chunk_range，
        将本地 chunk 索引转换为全局索引（合并多个 segments）。

        Args:
            xorb_data_map: {xorb_hash: compressed_xorb_data}
            recon: Reconstruction 响应（包含 fetch_info）

        Returns:
            {xorb_hash: XorbBlockData} 映射（chunk_offsets 使用全局索引）

        Raises:
            ImportError: lz4 或 blake3 未安装
            RuntimeError: 解压失败
        """
        try:
            from xet.storage.xorb_deserializer import XorbDeserializer, XorbBlockData
        except ImportError as e:
            raise ImportError(
                "[ChunkAssembler] 需要 lz4 和 blake3 库: pip install lz4 blake3"
            ) from e

        xorb_cache = {}

        for xorb_hash, compressed_data in xorb_data_map.items():
            logger.debug(
                f"[ChunkAssembler] 解压 xorb: {xorb_hash[:16]}... "
                f"({len(compressed_data)} bytes)"
            )

            # 调用反序列化函数（返回本地索引的 chunk_offsets）
            try:
                xorb_data_local = XorbDeserializer.deserialize(compressed_data)

                # 从 fetch_info 获取所有 segments 的 chunk_range
                # 一个 xorb 可能有多个 segments（不连续的 chunk 范围）
                if xorb_hash in recon.fetch_info:
                    fetch_infos = recon.fetch_info[xorb_hash]

                    # 假设下载的数据按 fetch_info 的顺序排列
                    # 每个 segment 的 chunks 在解压后是连续的
                    combined_chunk_offsets = []
                    local_chunk_idx = 0

                    for fetch_info in fetch_infos:
                        base_chunk_start = fetch_info.chunk_range.start
                        segment_chunk_count = fetch_info.chunk_range.length()

                        # 将这个 segment 的本地索引转换为全局索引
                        for i in range(segment_chunk_count):
                            if local_chunk_idx < len(xorb_data_local.chunk_offsets):
                                _, byte_offset = xorb_data_local.chunk_offsets[local_chunk_idx]
                                global_chunk_idx = base_chunk_start + i
                                combined_chunk_offsets.append((global_chunk_idx, byte_offset))
                                local_chunk_idx += 1

                    xorb_data_global = XorbBlockData(
                        chunk_offsets=combined_chunk_offsets,
                        data=xorb_data_local.data
                    )

                    logger.debug(
                        f"[ChunkAssembler] Xorb {xorb_hash[:16]}... "
                        f"有 {len(fetch_infos)} 个 segments, "
                        f"共 {len(combined_chunk_offsets)} 个 chunks"
                    )
                else:
                    # 如果没有 fetch_info，假设从 0 开始（单个 segment）
                    logger.warning(
                        f"[ChunkAssembler] Xorb {xorb_hash[:16]}... 没有 fetch_info"
                    )
                    xorb_data_global = xorb_data_local

                xorb_cache[xorb_hash] = xorb_data_global

                logger.debug(
                    f"[ChunkAssembler] Xorb {xorb_hash[:16]}... "
                    f"解压得到 {len(xorb_data_local.chunk_offsets)} 个 chunk, "
                    f"{len(xorb_data_local.data)} bytes total"
                )

            except Exception as e:
                raise RuntimeError(
                    f"[ChunkAssembler] 解压 xorb {xorb_hash[:16]}... 失败: {e}"
                ) from e

        return xorb_cache
