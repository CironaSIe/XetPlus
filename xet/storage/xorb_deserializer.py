"""Xorb 二进制反序列化模块。

解析 xorb (XET Object) 的二进制格式，提取压缩的 chunk 数据。
支持三种压缩方案：
- 0: None（原始数据）
- 1: LZ4 标准压缩
- 2: ByteGrouping4LZ4（4字节分组 + LZ4，优化浮点数据）
"""
import struct
import logging
from pathlib import Path
from typing import List, Tuple
from itertools import zip_longest

try:
    import lz4.frame  # type: ignore[import]
    LZ4_AVAILABLE = True
except ImportError:
    LZ4_AVAILABLE = False

try:
    from blake3 import blake3  # type: ignore[import]
    BLAKE3_AVAILABLE = True
except ImportError:
    BLAKE3_AVAILABLE = False

logger = logging.getLogger(__name__)


# XorbBlockData 类型定义
class XorbBlockData:
    """解压后的 xorb 数据块。

    反序列化一个完整的 xorb 后得到的结果。

    Attributes:
        chunk_offsets: chunk 索引到字节偏移的映射列表 [(chunk_idx, byte_offset), ...]
        data: 所有解压后 chunk 的拼接数据
    """
    def __init__(self, chunk_offsets: List[Tuple[int, int]], data: bytes):
        self.chunk_offsets = chunk_offsets
        self.data = data


def blake3_validate(data: bytes, expected_hex: str) -> bool:
    """校验数据的 Blake3 哈希是否匹配预期值。

    注意：这是简单模式（无 key），仅验证 plain blake3(data) == expected_hex。
    xorb hash 的正确校验请使用 verify_xorb_hash()。

    Args:
        data: 原始字节数据
        expected_hex: 64 位十六进制 Blake3 哈希字符串

    Returns:
        True 表示校验通过（Blake3 库可用且哈希匹配，否则返回 True 跳过）
    """
    if not BLAKE3_AVAILABLE:
        logger.warning("[Blake3] 库未安装，跳过 Blake3 校验")
        return True
    try:
        actual = blake3(data).hexdigest()  # type: ignore[operator]
        return actual == expected_hex
    except Exception:
        logger.warning("[Blake3] 校验异常，跳过")
        return True


def _save_debug_hashes(chunk_list: list, expected_hex: str, computed: str) -> None:
    """保存失败 xorb 的 debugging 信息到系统临时目录。"""
    import os, json, tempfile
    from .merkle_hash import compute_data_hash
    safe_name = expected_hex[:16]
    dirpath = str(Path(tempfile.gettempdir()) / 'xet_debug')  # L1 修复: 跨平台路径
    os.makedirs(dirpath, exist_ok=True)
    # 保存 per-chunk (hash, size) 列表
    records = []
    for data, size in chunk_list:
        h = compute_data_hash(data)
        records.append({"hash": h, "size": size})
    info = {
        "expected": expected_hex,
        "computed": computed,
        "num_chunks": len(records),
        "chunks": records,
    }
    path = os.path.join(dirpath, f"{safe_name}.json")
    with open(path, "w") as f:
        json.dump(info, f)
    logger.warning(f"[XorbHash] Debug 数据已保存: {path}")


def verify_xorb_hash(xorb_data: XorbBlockData, expected_hex: str) -> bool:
    """【已废弃】用 xet-core Merkle 树算法校验 xorb 哈希。

    警告：该函数在真实下载中 100% 失败（server hash ≠ 数据 hash），
    已从 reconstructor.py 中移除。官方 RemoteClient 也不验证此项。

    对每个 chunk 计算 keyed blake3(DATA_KEY)，再通过 Merkle 树
    聚合（INTERNAL_NODE_HASH key），与 expected_hex 比较。
    对应 Rust xet-core validate_xorb_object()。

    Args:
        xorb_data: XorbBlockData 包含 chunk_offsets 和 解压后 data
        expected_hex: 来自 API 的 xorb hash（64 hex 字符）

    Returns:
        True 表示校验通过
    """
    from .merkle_hash import compute_xorb_hash, blake3_available

    if not blake3_available():
        logger.warning("[XorbHash] Blake3 库未安装，跳过校验")
        return True

    chunks = xorb_data.chunk_offsets
    data = xorb_data.data
    if not chunks:
        logger.warning("[XorbHash] 无 chunk，跳过校验")
        return False

    seen = set()
    unique = []
    for idx, off in sorted(chunks, key=lambda x: (x[0], x[1])):
        if idx not in seen:
            seen.add(idx)
            unique.append((idx, off))

    offsets = [off for _, off in unique] + [len(data)]

    sizes = [offsets[i + 1] - offsets[i] for i in range(len(unique))]
    chunk_list = []
    for (i, chunk_bytes) in enumerate(
        (data[offsets[i]:offsets[i + 1]] for i in range(len(unique)))
    ):
        if sizes[i] == 0:
            continue
        chunk_list.append((chunk_bytes, sizes[i]))
    try:
        computed = compute_xorb_hash(chunk_list)
        if computed != expected_hex:
            logger.warning(
                f"[XorbHash] 不匹配: computed={computed}, "
                f"expected={expected_hex}"
            )
            # 保存调试信息
            import pickle, os, tempfile
            from .merkle_hash import compute_data_hash
            dbg = {
                'expected': expected_hex, 'computed': computed,
                'n_chunks': len(chunk_list),
                'chunk_hashes': [
                    (compute_data_hash(d), s) for d, s in chunk_list
                ],
                'offsets_raw': list(chunks),
                'offsets_unique': unique,
                'total_data_len': len(data),
            }
            try:
                os.makedirs('/tmp/xet_debug', exist_ok=True)
                with open(f'/tmp/xet_debug/{expected_hex[:16]}.pkl', 'wb') as f:
                    pickle.dump(dbg, f)
                logger.debug(f"[XorbHash] 调试数据已保存到 /tmp/xet_debug/{expected_hex[:16]}.pkl")
            except Exception as e:
                logger.debug(f"[XorbHash] 保存调试数据失败: {e}")
            return False
        logger.debug("[XorbHash] ✅ 校验通过")
        return True
    except Exception:
        logger.warning("[XorbHash] 校验异常，跳过", exc_info=True)
        return True


# 压缩方案常量
COMPRESSION_NONE = 0
COMPRESSION_LZ4 = 1
COMPRESSION_BYTE_GROUPING_4_LZ4 = 2


class XorbDeserializer:
    """Xorb 二进制格式反序列化器。

    解析 xorb 的 chunk-based 格式，按顺序解压每个 chunk 并拼接。

    Chunk Header 格式（固定 8 字节）：
    ┌─────────┬──────────────┬────────────┬──────────────────┐
    │ version │ compressed   │ comp_scheme│ uncompressed     │
    │  (1B)   │ length (3B)  │   (1B)     │ length (3B)      │
    └─────────┴──────────────┴────────────┴──────────────────┘

    version: 版本号（当前为 0）
    compressed length: u24 little-endian
    compression scheme: 0=None, 1=LZ4, 2=ByteGrouping4LZ4
    uncompressed length: u24 little-endian
    """

    @staticmethod
    def deserialize(xorb_bytes: bytes) -> XorbBlockData:
        """反序列化完整的 xorb 数据。

        按序解析所有 chunk，解压后返回拼接的数据和偏移信息。

        Args:
            xorb_bytes: 原始 xorb 字节数据（来自 HTTP 下载）

        Returns:
            XorbBlockData 包含：
            - chunk_offsets: [(chunk_index, byte_offset), ...]
            - data: 所有解压后的 chunk 拼接数据

        Raises:
            ValueError: 数据格式无效或解压失败
            ImportError: 需要但未安装 lz4 库
        """
        if not xorb_bytes:
            raise ValueError("xorb_bytes 不能为空")

        chunk_offsets: List[Tuple[int, int]] = []
        all_data = bytearray()
        chunk_index = 0
        offset = 0

        logger.debug(f"[Xorb] 开始反序列化, 总长度: {len(xorb_bytes)} bytes")

        while offset < len(xorb_bytes):
            # 检查是否有足够的字节读取 header
            # Chunk Header 固定 8 字节
            # 格式: version(1B) + compressed_length(3B u24 LE) +
            #       compression_scheme(1B) + uncompressed_length(3B u24 LE)
            if offset + 8 > len(xorb_bytes):
                if chunk_index == 0:
                    raise ValueError(
                        f"[Xorb] 数据不完整: 需要至少 8 字节 header, 但只有 {len(xorb_bytes)} 字节"
                    )
                logger.warning(f"[Xorb] 在偏移 {offset} 处数据不完整 "
                              f"(需要 8 字节 header, 剩余 {len(xorb_bytes) - offset})")
                break

            # 读取 8 字节 chunk header
            header = xorb_bytes[offset:offset + 8]

            # 解析 header 字段（严格按照 XET.SPEC.md §2.1）
            version = header[0]                              # 1 byte: 版本号 (当前 = 0)
            compressed_len = int.from_bytes(header[1:4], 'little')  # 3 bytes: 压缩长度 (u24 LE)
            comp_scheme = header[4]                          # 1 byte: 压缩方案
            decompressed_len = int.from_bytes(header[5:8], 'little')  # 3 bytes: 解压长度 (u24 LE)

            # ✅ O10: 移除逐 chunk 日志 (大xorb有800+chunks会产生大量无用输出)
            # 仅在反序列化完成后输出汇总信息

            # 计算数据位置
            data_start = offset + 8
            data_end = data_start + compressed_len

            # 边界检查
            if data_end > len(xorb_bytes):
                raise ValueError(
                    f"[Xorb] Chunk #{chunk_index} 数据越界: "
                    f"需要 {data_end} bytes, 只有 {len(xorb_bytes)} bytes"
                )

            # 提取压缩数据
            comp_data = xorb_bytes[data_start:data_end]

            # 根据压缩方案解压
            raw_data = XorbDeserializer._decompress(comp_data, comp_scheme, decompressed_len)

            # 验证解压大小
            if len(raw_data) != decompressed_len:
                raise ValueError(
                    f"[Xorb] Chunk #{chunk_index} 解压大小不匹配: "
                    f"期望 {decompressed_len}, 实际 {len(raw_data)}"
                )

            # 记录偏移并追加数据
            chunk_offsets.append((chunk_index, len(all_data)))
            all_data.extend(raw_data)
            chunk_index += 1
            offset = data_end

        logger.debug(f"[Xorb] 反序列化完成: {chunk_index} chunks, "
                     f"总大小 {len(all_data)} bytes")

        return XorbBlockData(chunk_offsets=chunk_offsets, data=bytes(all_data))

    @staticmethod
    def _decompress(data: bytes, scheme: int, expected_size: int) -> bytes:
        """根据压缩方案解压单个 chunk。

        Args:
            data: 压缩数据
            scheme: 压缩方案编号 (0/1/2)
            expected_size: 期望的解压大小

        Returns:
            解压后的原始数据

        Raises:
            ValueError: 不支持的压缩方案或解压失败
        """
        if scheme == COMPRESSION_NONE:
            # 无压缩，直接返回
            return data

        elif scheme == COMPRESSION_LZ4:
            # 标准 LZ4 压缩
            return XorbDeserializer._decompress_lz4(data, expected_size)

        elif scheme == COMPRESSION_BYTE_GROUPING_4_LZ4:
            # ByteGrouping4LZ4：先 LZ4 解压，再 4-byte 反分组
            lz4_data = XorbDeserializer._decompress_lz4(data, expected_size)
            return XorbDeserializer._ungrouping_4byte(lz4_data)

        else:
            raise ValueError(f"未知的压缩方案: {scheme}")

    @staticmethod
    def _decompress_lz4(compressed: bytes, expected_size: int) -> bytes:
        """使用 LZ4 解压数据。

        Args:
            compressed: LZ4 压缩数据
            expected_size: 期望的解压大小（用于验证）

        Returns:
            解压后的数据

        Raises:
            ImportError: lz4 库未安装
            RuntimeError: LZ4 解压失败
        """
        if not LZ4_AVAILABLE:
            raise ImportError(
                "需要 lz4 库来解压 xorb 数据。请运行: pip install lz4"
            )

        # 导入并使用 lz4.frame（在函数内部导入以延迟加载检查）
        import lz4.frame as lz4_module  # type: ignore[import]

        try:
            decompressed = lz4_module.decompress(compressed)
            return decompressed
        except Exception as e:
            logger.error(f"[Xorb] LZ4 解压失败: {e}")
            raise RuntimeError(f"LZ4 解压失败: {e}")

    @staticmethod
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

    @classmethod
    def is_lz4_available(cls) -> bool:
        """检查 LZ4 库是否可用。

        Returns:
            如果可以导入 lz4 则返回 True
        """
        return LZ4_AVAILABLE

    @staticmethod
    def parse_multipart_byteranges(response) -> List[bytes]:
        """解析 multipart/byteranges 响应，提取各个 segment 数据。

        当 V2 API 返回的 xorb 数据被拆分为多个范围时，
        HTTP 响应使用 multipart/byteranges 格式（RFC 7233）。

        Content-Type 示例:
            multipart/byteranges; boundary=XXXXX

        每个部分格式:
            --XXXXX\r\n
            Content-Type: application/octet-stream\r\n
            Content-Range: bytes START-END/TOTAL\r\n
            \r\n
            <binary data>\r\n

        Args:
            response: requests.Response 对象（stream=True 状态）

        Returns:
            各 segment 的原始字节数据列表，按顺序排列

        Raises:
            ValueError: 如果响应格式无效或无法解析 boundary

        Example:
            >>> resp = session.get(url, headers={"Range": "bytes=0-1000,1500-2500"}, stream=True)
            >>> segments = XorbDeserializer.parse_multipart_byteranges(resp)
            >>> print(f"收到 {len(segments)} 个 segment")
        """
        content_type = response.headers.get('Content-Type', '')

        if 'multipart/byteranges' not in content_type:
            # 不是 multipart 响应，返回单段数据
            return [response.content]

        # 提取 boundary
        import re
        boundary_match = re.search(r'boundary="?([^";\s]+)"?', content_type)

        if not boundary_match:
            raise ValueError(
                f"[Xorb Multipart] 无法从 Content-Type 提取 boundary: {content_type}"
            )

        boundary = boundary_match.group(1)
        boundary_bytes = f'--{boundary}'.encode('utf-8')
        end_boundary = f'--{boundary}--'.encode('utf-8')

        logger.debug(f"[Xorb Multipart] 解析 multipart, boundary={boundary}")

        segments = []
        current_segment = bytearray()
        in_data = False

        for line in response.iter_lines():
            if line is None:
                continue

            if isinstance(line, str):
                line = line.encode('utf-8')

            # 检查边界标记
            if line == end_boundary:
                # 最终边界，结束解析
                if current_segment:
                    segments.append(bytes(current_segment))
                    current_segment = bytearray()
                break

            elif line == boundary_bytes or line == (boundary_bytes + b'\r'):
                # 新 segment 开始（或首个）
                if current_segment and in_data:
                    # 保存上一个 segment
                    segments.append(bytes(current_segment))
                    current_segment = bytearray()

                in_data = False  # 等待 header 结束

            elif line == b'' or line == b'\r':
                # 空行表示 header 结束，后续是数据
                in_data = True

            elif in_data:
                # 数据行，追加到当前 segment
                current_segment.extend(line + b'\n')

        # 处理最后一个 segment
        if current_segment and in_data:
            segments.append(bytes(current_segment))

        logger.debug(f"[Xorb Multipart] 解析完成, 共 {len(segments)} 个 segment")
        for i, seg in enumerate(segments):
            logger.debug(f"  Segment #{i}: {len(seg)} bytes")

        return segments

    @staticmethod
    def deserialize_multipart_segments(segments: List[bytes]) -> XorbBlockData:
        """将多个 xorb segment 合并为完整的 XorbBlockData。

        按照 XET.SPEC.md §2.5 的算法：
        - 第一个 segment 直接使用其 chunk_byte_indices
        - 后续 segment 需要跳过首位的 0，并 rebase 到全局偏移

        Args:
            segments: 多个 xorb segment 数据（来自 parse_multipart_byteranges）

        Returns:
            合并后的完整 XorbBlockData

        Raises:
            ValueError: 如果任何 segment 反序列化失败
        """
        all_data = bytearray()
        all_chunk_offsets = []

        for seg_idx, segment in enumerate(segments):
            logger.debug(f"[Xorb Multipart] 反序列化 segment #{seg_idx}: {len(segment)} bytes")

            # 反序列化单个 segment
            seg_result = XorbDeserializer.deserialize(segment)

            base_offset = len(all_data)

            if seg_idx == 0:
                # 第一个 segment: 使用原始偏移
                all_chunk_offsets.extend(seg_result.chunk_offsets)
            else:
                # 后续 segment: rebase 偏移
                for chunk_idx, byte_offset in seg_result.chunk_offsets:
                    if chunk_idx == 0:
                        continue  # 跳过首位的 0（相对于新 segment）
                    all_chunk_offsets.append((chunk_idx, byte_offset + base_offset))

            # 追加数据
            all_data.extend(seg_result.data)

        logger.debug(f"[Xorb Multipart] 合并完成: {len(segments)} segments → "
                     f"{len(all_data)} bytes, {len(all_chunk_offsets)} chunks")

        return XorbBlockData(chunk_offsets=all_chunk_offsets, data=bytes(all_data))
