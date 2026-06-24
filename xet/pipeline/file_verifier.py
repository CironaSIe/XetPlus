"""文件校验与修复器 - Verify + Repair 核心。

信任链设计（双层验证）：

  第一层：文件级 SHA256（外部锚点）
     从 HF Hub 的 X-Linked-ETag 获取期望值，对比文件内容。
     这是真正的验证：服务器提供锚点，本地计算比对。
     通过 → 文件正确，直接清理 checkpoint 退出。
     失败 → 数据有问题，进入第二层诊断。

  第二层：per-term SHA256 诊断（本地诊断工具）
     读取 checkpoint 中存储的组装时 SHA256，
     逐 term 重算比对 → 找出损坏的 term。
     注意：这只能检测"写入后"的损坏（竞态、bit rot、截断），
           不能检测"下载时就是错误数据"的情况。
           后者只能由第一层文件级 SHA256 发现。

  修复流程：
     对诊断出的损坏 term，按 xorb_hash 分组，
     只重新下载对应的 xorb，解压后覆写文件损坏部分。
"""
import hashlib
import logging
import threading
import os
import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.checkpoint_manager import CheckpointManager
from xet.pipeline.types import ReconstructionCheckpoint, TermHashRecord

logger = logging.getLogger(__name__)


class VerifyError(Exception):
    pass


class NoCheckpointError(VerifyError):
    pass


class VerifyReport:
    """校验结果报告。

    Attributes:
        file_sha256_ok: 文件级 SHA256 校验是否通过（None 表示无锚点）
        expected_sha256: 期望的文件 SHA256（服务器提供）
        actual_sha256: 实际的文件 SHA256
        total_terms: 总共诊断的 term 数量
        corrupt_terms: per-term 诊断发现的损坏 term 索引列表
        total_bytes: 诊断的总字节数
        corrupt_bytes: 损坏的字节数
        repaired: 是否已执行修复
        repair_failures: 修复失败的 xorb hash 列表
        diagnosis: 是否执行了 per-term 诊断
        has_checkpoint: 是否有 per-term checkpoint
    """

    def __init__(
        self,
        file_sha256_ok: Optional[bool] = None,
        expected_sha256: str = "",
        actual_sha256: str = "",
        total_terms: int = 0,
        corrupt_terms: Optional[List[int]] = None,
        total_bytes: int = 0,
        corrupt_bytes: int = 0,
        repaired: bool = False,
        repair_failures: Optional[List[str]] = None,
        diagnosis: bool = False,
        has_checkpoint: bool = False,
    ):
        self.file_sha256_ok = file_sha256_ok
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256
        self.total_terms = total_terms
        self.corrupt_terms = corrupt_terms or []
        self.total_bytes = total_bytes
        self.corrupt_bytes = corrupt_bytes
        self.repaired = repaired
        self.repair_failures = repair_failures or []
        self.diagnosis = diagnosis
        self.has_checkpoint = has_checkpoint

    @property
    def is_healthy(self) -> bool:
        if self.file_sha256_ok is True:
            return True
        if self.file_sha256_ok is False:
            return False
        if self.diagnosis:
            return len(self.corrupt_terms) == 0
        return True

    @property
    def corruption_ratio(self) -> float:
        if self.total_terms == 0:
            return 0.0
        return len(self.corrupt_terms) / self.total_terms

    def __str__(self) -> str:
        lines = []
        if self.file_sha256_ok is True:
            lines.append(f"  ✅ 文件 SHA256 校验通过")
            return "\n".join(lines)
        if self.file_sha256_ok is False:
            lines.append(f"  ❌ 文件 SHA256 校验失败")
            lines.append(f"    期望: {self.expected_sha256[:16]}...")
            lines.append(f"    实际: {self.actual_sha256[:16]}...")
        if not self.has_checkpoint and self.file_sha256_ok is False:
            lines.append(f"    无 per-term 诊断存档，建议重新下载文件")
            return "\n".join(lines)
        if self.diagnosis:
            lines.append(f"  Per-term 诊断: {self.total_terms} terms, "
                         f"{self.total_bytes / 1024 / 1024:.1f} MB")
            if not self.corrupt_terms:
                lines.append(f"    ✅ 所有 term 数据一致（损坏可能在传输路径上）")
            else:
                lines.append(f"    ❌ {len(self.corrupt_terms)}/{self.total_terms} terms 损坏 "
                             f"({self.corrupt_bytes / 1024 / 1024:.1f} MB)")
            if self.repaired:
                if self.repair_failures:
                    lines.append(f"    ⚠ 修复完成，但 {len(self.repair_failures)} 个 xorb 修复失败")
                else:
                    lines.append(f"    ✅ 已修复所有损坏的 term")
        return "\n".join(lines)


class FileVerifier:
    """文件校验与修复器。

    验证流程：
      1. 文件级 SHA256（外部锚点优先）→ 通过则退出
      2. Per-term 诊断（仅当文件级失败且有 checkpoint 时）

    修复流程：
      对损坏 term 按 xorb 分组 → 下载 xorb → 解压 → 覆写文件
    """

    def __init__(
        self,
        output_path: Path,
        file_hash: str,
        temp_dir: Optional[Path] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        cas_client=None,
        max_workers: int = 4,
        expected_sha256: str = "",
    ):
        self.output_path = output_path
        self.file_hash = file_hash
        self.temp_dir = temp_dir or Path.cwd() / ".xet_temp"
        self.checkpoint_manager = checkpoint_manager
        self.cas_client = cas_client
        self.max_workers = max_workers
        self._expected_sha256 = expected_sha256

    def verify(self, diagnose: bool = False) -> VerifyReport:
        """执行验证。

        第一层：文件级 SHA256（需要 expected_sha256 锚点）。
        第二层（可选）：per-term 诊断（需要 checkpoint）。

        Args:
            diagnose: 文件级失败后是否执行 per-term 诊断

        Returns:
            VerifyReport
        """
        if not self.output_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.output_path}")

        expected = self._resolve_expected_sha256()
        report = VerifyReport()

        # ── 第一层：文件级 SHA256 ──
        if expected:
            actual = self._calculate_file_sha256()
            report.actual_sha256 = actual
            report.expected_sha256 = expected
            if actual.lower() == expected.lower():
                report.file_sha256_ok = True
                logger.info(f"[FileVerifier] 文件 SHA256 校验通过")
                return report
            report.file_sha256_ok = False
            logger.error(
                f"[FileVerifier] 文件 SHA256 不匹配: "
                f"期望 {expected[:16]}..., 实际 {actual[:16]}..."
            )
        else:
            report.file_sha256_ok = None
            logger.info(f"[FileVerifier] 无文件级 SHA256 锚点，跳过文件级验证")

        # ── 第二层：per-term 诊断（可选）──
        if diagnose:
            self._run_diagnosis(report)

        return report

    def repair(self, report: Optional[VerifyReport] = None) -> bool:
        """执行修复。

        先验证，如果文件级通过则直接返回。
        否则使用 per-term 诊断定位损坏 term，下载 xorb 修复。

        Returns:
            True 表示修复后文件级 SHA256 匹配
        """
        if not self.cas_client:
            raise RuntimeError("修复需要设置 cas_client")

        # 先验证 + 诊断
        report = report or self.verify(diagnose=True)

        # 文件级已通过
        if report.file_sha256_ok is True:
            logger.info("[FileVerifier] 文件完好，无需修复")
            return True

        # 文件级失败 + 诊断无损坏 term → 损坏在传输路径，需要全量重下
        if not report.corrupt_terms:
            if report.file_sha256_ok is False:
                logger.error(
                    "[FileVerifier] 文件级 SHA256 不匹配但 per-term 诊断无损坏项。\n"
                    "  这可能意味着下载时就收到了错误数据。\n"
                    "  请重新下载整个文件:\n"
                    f"    xet download <文件路径>"
                )
                return False
            # 无文件级锚点且无诊断数据 → 无法验证
            logger.error("[FileVerifier] 缺少校验数据，无法验证文件完整性")
            return False

        # ── 执行修复 ──
        checkpoint = self._load_checkpoint()
        if not checkpoint or not checkpoint.has_per_term_hashes():
            raise NoCheckpointError("缺少 per-term 校验存档，无法修复")

        per_term = checkpoint.per_term_hashes

        xorb_groups: Dict[str, List[Tuple[int, TermHashRecord]]] = {}
        for term_idx in report.corrupt_terms:
            if term_idx not in per_term:
                logger.warning(f"Term #{term_idx} 不在校验存档中，跳过")
                continue
            record = per_term[term_idx]
            xorb_groups.setdefault(record.xorb_hash, []).append((term_idx, record))

        logger.info(
            f"[FileVerifier] 修复 {len(report.corrupt_terms)} terms, "
            f"涉及 {len(xorb_groups)} 个 xorb"
        )

        recon = self.cas_client.get_reconstruction(self.file_hash)

        repair_failures: List[str] = []
        for xorb_hash, terms in xorb_groups.items():
            try:
                self._repair_xorb(recon, xorb_hash, terms)
                logger.info(f"[FileVerifier] Xorb {xorb_hash[:16]}... 修复完成")
            except Exception as e:
                logger.error(f"[FileVerifier] Xorb {xorb_hash[:16]}... 修复失败: {e}")
                repair_failures.append(xorb_hash)

        report.repaired = not repair_failures
        report.repair_failures = repair_failures

        # ── 修复后验证 ──
        if not repair_failures:
            expected = self._resolve_expected_sha256()
            if expected:
                final_sha = self._calculate_file_sha256()
                ok = final_sha.lower() == expected.lower()
                logger.info(
                    f"[FileVerifier] 修复后文件 SHA256: "
                    f"{'✅ 通过' if ok else '❌ 失败'} "
                    f"({final_sha[:16]}...)"
                )
                return ok
            logger.info("[FileVerifier] 修复完成（无 SHA256 锚点，无法确认）")
            return True

        return False

    def _resolve_expected_sha256(self) -> str:
        """获取期望的文件级 SHA256 锚点。

        优先级：1. 构造参数  2. checkpoint  3. 侧车文件
        """
        if self._expected_sha256:
            return self._expected_sha256
        checkpoint = self._load_checkpoint()
        if checkpoint and checkpoint.expected_sha256:
            return checkpoint.expected_sha256
        # 尝试侧车文件
        try:
            sidecar = self.output_path.with_suffix(self.output_path.suffix + ".xet_verify")
            if sidecar.exists():
                with open(sidecar, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('expected_sha256', '')
        except Exception:
            pass
        return ""

    def _run_diagnosis(self, report: VerifyReport) -> None:
        """per-term 诊断：读取文件对比 checkpoint SHA256。"""
        checkpoint = self._load_checkpoint()
        if not checkpoint or not checkpoint.has_per_term_hashes():
            logger.warning("[FileVerifier] 无 per-term 诊断存档，跳过诊断")
            report.has_checkpoint = False
            return

        report.has_checkpoint = True
        per_term = checkpoint.per_term_hashes
        corrupt_terms: List[int] = []
        total_bytes = 0
        corrupt_bytes = 0

        file_size = self.output_path.stat().st_size
        last_record = max(per_term.values(), key=lambda r: r.file_offset + r.unpacked_length)
        expected_min_size = last_record.file_offset + last_record.unpacked_length
        if file_size < expected_min_size:
            raise VerifyError(
                f"文件大小不足: 实际 {file_size} bytes, "
                f"期望至少 {expected_min_size} bytes。文件可能被截断。"
            )

        with open(self.output_path, 'rb') as f:
            for term_idx in sorted(per_term.keys()):
                record = per_term[term_idx]
                f.seek(record.file_offset)
                file_data = f.read(record.unpacked_length)

                if len(file_data) != record.unpacked_length:
                    corrupt_terms.append(term_idx)
                    corrupt_bytes += record.unpacked_length
                    continue

                actual_sha = hashlib.sha256(file_data).hexdigest()
                total_bytes += record.unpacked_length

                if actual_sha != record.sha256:
                    corrupt_terms.append(term_idx)
                    corrupt_bytes += record.unpacked_length

        report.total_terms = len(per_term)
        report.corrupt_terms = corrupt_terms
        report.total_bytes = total_bytes
        report.corrupt_bytes = corrupt_bytes
        report.diagnosis = True

    def _repair_xorb(self, recon, xorb_hash: str, terms: List[Tuple[int, TermHashRecord]]) -> None:
        """下载 xorb 并修复其中损坏的 term。"""
        if xorb_hash not in recon.fetch_info:
            raise ValueError(f"Xorb {xorb_hash[:16]}... 没有 fetch_info")

        fetch_infos = recon.fetch_info[xorb_hash]
        sorted_infos = sorted(fetch_infos, key=lambda fi: fi.chunk_range.start)
        segments = []
        assert self.cas_client is not None
        for fi in sorted_infos:
            segment_data = self.cas_client.get_xorb_data_with_retry(
                url=fi.url, url_range=fi.url_range,
                xorb_hash=xorb_hash, file_hash=self.file_hash,
            )
            segments.append(segment_data)

        merged_data = b''.join(segments)

        from xet.storage.xorb_deserializer import XorbDeserializer, StreamingXorbAccessor

        if len(sorted_infos) == 1:
            fi = sorted_infos[0]
            seg_xorb = XorbDeserializer.deserialize(merged_data)
            base_cid = fi.chunk_range.start
            chunk_offsets = [(base_cid + lcidx, lboff) for lcidx, lboff in seg_xorb.chunk_offsets]
            accessor = StreamingXorbAccessor(raw_bytes=merged_data, chunk_offsets=chunk_offsets)
        else:
            all_data_rebased = bytearray()
            rebased_offsets = []
            pos = 0
            for fi in sorted_infos:
                seg_len = fi.url_range.length()
                seg_data = merged_data[pos:pos + seg_len]
                pos += seg_len
                seg_xorb = XorbDeserializer.deserialize(seg_data)
                base_cid = fi.chunk_range.start
                for lcidx, lboff in seg_xorb.chunk_offsets:
                    rebased_offsets.append((base_cid + lcidx, len(all_data_rebased) + lboff))
                all_data_rebased.extend(seg_xorb.data)
            accessor = StreamingXorbAccessor(
                raw_bytes=bytes(all_data_rebased),
                chunk_offsets=rebased_offsets,
            )

        chunk_offsets_dict = dict(accessor.chunk_offsets)

        with open(self.output_path, 'r+b') as f:
            for term_idx, record in terms:
                term_info = recon.terms[term_idx]
                start_chunk = term_info.range.start
                end_chunk = term_info.range.end

                if start_chunk not in chunk_offsets_dict:
                    raise ValueError(f"Term #{term_idx} start chunk {start_chunk} 不在 chunk_offsets 中")

                start_byte = chunk_offsets_dict[start_chunk]
                if end_chunk not in chunk_offsets_dict:
                    sorted_chunks = sorted(chunk_offsets_dict.items())
                    end_byte = next(
                        (off for cid, off in sorted_chunks if cid >= end_chunk),
                        accessor.data_size()
                    )
                else:
                    end_byte = chunk_offsets_dict[end_chunk]

                assert isinstance(end_byte, int)
                if end_byte > accessor.data_size():
                    raise ValueError(f"Term #{term_idx} 数据越界")

                assert isinstance(start_byte, int)
                segment = accessor.extract_range(start_byte, end_byte)

                if term_idx == 0 and recon.offset_into_first_range > 0:
                    offset = recon.offset_into_first_range
                    if offset >= len(segment):
                        raise ValueError(f"offset_into_first_range ({offset}) >= 第一个 term 长度 ({len(segment)})")
                    segment = segment[offset:]

                f.seek(record.file_offset)
                f.write(segment)
                logger.debug(f"[FileVerifier] Term #{term_idx} 已修复 (offset={record.file_offset}, size={len(segment)})")

    def _load_checkpoint(self) -> Optional[ReconstructionCheckpoint]:
        if not self.checkpoint_manager:
            return None
        return self.checkpoint_manager.load(self.file_hash)

    def _calculate_file_sha256(self) -> str:
        sha256 = hashlib.sha256()
        with open(self.output_path, 'rb') as f:
            while True:
                data = f.read(8 * 1024 * 1024)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
