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

        处理 multipart segments:
        - xorb_data_map 中的数据已经是合并后的（所有 segments 按顺序拼接）
        - 需要分别反序列化每个 segment，然后按 XET.SPEC.md 合并 chunk_offsets

        参考 XET.SPEC.md 的 append_chunk_segment 逻辑。

        Args:
            xorb_data_map: {xorb_hash: merged_compressed_data}
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

        for xorb_hash, merged_data in xorb_data_map.items():
            logger.debug(
                f"[ChunkAssembler] 解压 xorb: {xorb_hash[:16]}... "
                f"({len(merged_data)} bytes)"
            )

            # 获取该 xorb 的所有 segments（按 chunk_range.start 排序）
            if xorb_hash not in recon.fetch_info:
                logger.warning(
                    f"[ChunkAssembler] Xorb {xorb_hash[:16]}... 没有 fetch_info"
                )
                continue

            fetch_infos = sorted(
                recon.fetch_info[xorb_hash],
                key=lambda fi: fi.chunk_range.start
            )

            # 分别反序列化每个 segment 并合并
            # 参考 XET.SPEC.md 的 append_chunk_segment 逻辑
            all_chunk_offsets = []
            all_data = bytearray()
            data_offset = 0

            for seg_idx, fi in enumerate(fetch_infos):
                # 提取这个 segment 的数据
                segment_byte_length = fi.url_range.length()
                segment_data = merged_data[data_offset:data_offset + segment_byte_length]
                data_offset += segment_byte_length

                # 反序列化这个 segment
                try:
                    segment_xorb = XorbDeserializer.deserialize(segment_data)
                except Exception as e:
                    raise RuntimeError(
                        f"[ChunkAssembler] 解压 xorb {xorb_hash[:16]}... "
                        f"segment {seg_idx} 失败: {e}"
                    ) from e

                # 合并 chunk_offsets
                # 注意：XET.SPEC.md 的逻辑是针对 [0, offset1, offset2, ...] 这样的偏移列表
                # 但 XorbDeserializer 返回的是 [(chunk_idx, byte_offset), ...] 元组列表
                # 两者逻辑不同！

                base_chunk_idx = fi.chunk_range.start
                base_data_offset = len(all_data)

                for local_chunk_idx, local_byte_offset in segment_xorb.chunk_offsets:
                    # 全局 chunk 索引 = segment 起始索引 + 本地索引
                    global_chunk_idx = base_chunk_idx + local_chunk_idx

                    # 全局字节偏移 = 当前累积数据长度 + 本地偏移
                    global_byte_offset = base_data_offset + local_byte_offset

                    all_chunk_offsets.append((global_chunk_idx, global_byte_offset))

                # 追加数据
                all_data.extend(segment_xorb.data)

                logger.debug(
                    f"[ChunkAssembler] Segment {seg_idx + 1}/{len(fetch_infos)}: "
                    f"chunks=[{fi.chunk_range.start},{fi.chunk_range.end}), "
                    f"{len(segment_xorb.chunk_offsets)} chunks, "
                    f"{len(segment_xorb.data)} bytes"
                )

            # 创建合并后的 XorbBlockData
            xorb_data_merged = XorbBlockData(
                chunk_offsets=all_chunk_offsets,
                data=bytes(all_data)
            )

            xorb_cache[xorb_hash] = xorb_data_merged

            logger.debug(
                f"[ChunkAssembler] Xorb {xorb_hash[:16]}... 解压完成: "
                f"{len(fetch_infos)} segments, "
                f"{len(all_chunk_offsets)} chunks total, "
                f"{len(all_data)} bytes total"
            )

        return xorb_cache
