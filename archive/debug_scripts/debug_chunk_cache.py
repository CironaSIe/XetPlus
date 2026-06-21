#!/usr/bin/env python3
"""调试 chunk 缓存问题的工具脚本。

步骤：
1. 下载 reconstruction 信息并保存为 JSON
2. 下载所有 xorb 数据并保存到本地
3. 离线分析每个 xorb 的 chunk 结构
4. 找出 chunk_byte_indices 长度不匹配的根本原因
"""
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from xet.network.cas_client import CASClient
from xet.protocol.types import QueryReconstructionResponse
from xet.storage.xorb_deserializer import XorbDeserializer
from xet.cli.config_manager import ConfigManager
from xet.network.auth import XetAuth
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def download_reconstruction_info(
    cas_client: CASClient,
    file_hash: str,
    output_path: Path,
):
    """下载并保存 reconstruction 信息。"""
    logger.info(f"📥 下载 reconstruction 信息: {file_hash}")

    recon = cas_client.get_reconstruction(file_hash)

    # 转换为可序列化的字典
    recon_dict = {
        "file_hash": file_hash,
        "offset_into_first_range": recon.offset_into_first_range,
        "total_file_size": recon.total_file_size,
        "terms": [
            {
                "term_idx": idx,
                "hash": term.hash,
                "unpacked_length": term.unpacked_length,
            }
            for idx, term in enumerate(recon.terms)
        ],
        "fetch_info": {}
    }

    # 保存每个 xorb 的 fetch_infos
    for xorb_hash, fetch_infos in recon.fetch_info.items():
        recon_dict["fetch_info"][xorb_hash] = [
            {
                "url": fi.url,
                "url_range": {
                    "start": fi.url_range.start,
                    "end": fi.url_range.end,
                },
                "chunk_range": {
                    "start": fi.chunk_range.start,
                    "end": fi.chunk_range.end,
                }
            }
            for fi in fetch_infos
        ]

    # 保存为 JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(recon_dict, f, indent=2, ensure_ascii=False)

    logger.info(f"✅ Reconstruction 信息已保存: {output_path}")
    logger.info(f"   - Terms: {len(recon.terms)}")
    logger.info(f"   - Xorbs: {len(recon.fetch_info)}")

    return recon


def download_all_xorbs(
    cas_client: CASClient,
    recon: QueryReconstructionResponse,
    output_dir: Path,
):
    """下载所有 xorb 数据到本地，并按 chunk 粒度分析。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"📥 开始下载 {len(recon.fetch_info)} 个 xorbs...")

    xorb_metadata = {}

    for xorb_idx, (xorb_hash, fetch_infos) in enumerate(recon.fetch_info.items()):
        logger.info(f"\n[{xorb_idx + 1}/{len(recon.fetch_info)}] {xorb_hash[:16]}...")

        # 下载所有 segments 并合并
        segments = []
        sorted_infos = sorted(fetch_infos, key=lambda fi: fi.chunk_range.start)

        logger.info(f"  Fetch infos ({len(sorted_infos)} 个):")
        for seg_idx, fi in enumerate(sorted_infos):
            segment_data = cas_client.get_xorb_data(
                url=fi.url,
                url_range=fi.url_range,
            )
            segments.append(segment_data)
            logger.info(
                f"    [{seg_idx}] {len(segment_data):,} bytes compressed, "
                f"chunk_range={fi.chunk_range.start}-{fi.chunk_range.end} "
                f"(长度 {fi.chunk_range.end - fi.chunk_range.start})"
            )

        # 合并数据
        merged_data = b''.join(segments)

        # 立即解压并分析
        try:
            xorb_data = XorbDeserializer.deserialize(merged_data)
            chunk_byte_indices = xorb_data.get_chunk_byte_indices()

            logger.info(f"  解压成功:")
            logger.info(f"    压缩大小: {len(merged_data):,} bytes")
            logger.info(f"    解压大小: {len(xorb_data.data):,} bytes")
            logger.info(f"    Chunks: {len(chunk_byte_indices) - 1}")

            # 显示 chunk offsets 的编号范围
            if xorb_data.chunk_offsets:
                chunk_nums = [off[0] for off in xorb_data.chunk_offsets]
                logger.info(
                    f"    Chunk 编号范围: {min(chunk_nums)}-{max(chunk_nums)} "
                    f"(共 {len(set(chunk_nums))} 个唯一 chunk)"
                )

            decompressed = True
        except Exception as e:
            logger.warning(f"  ⚠️ 解压失败: {e}")
            chunk_byte_indices = []
            decompressed = False

        # 保存压缩数据
        xorb_file = output_dir / f"{xorb_hash}.xorb"
        with open(xorb_file, 'wb') as f:
            f.write(merged_data)

        # 保存元数据（包含详细的 chunk 信息）
        xorb_metadata[xorb_hash] = {
            "file": str(xorb_file),
            "compressed_size": len(merged_data),
            "decompressed": decompressed,
            "decompressed_size": len(xorb_data.data) if decompressed else 0,
            "num_chunks": len(chunk_byte_indices) - 1 if decompressed else 0,
            "num_segments": len(segments),
            "fetch_infos": [
                {
                    "chunk_range": {
                        "start": fi.chunk_range.start,
                        "end": fi.chunk_range.end,
                    },
                    "segment_size": len(segments[idx])
                }
                for idx, fi in enumerate(sorted_infos)
            ]
        }

    # 保存元数据
    metadata_file = output_dir / "xorbs_metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(xorb_metadata, f, indent=2)

    logger.info(f"\n✅ 所有 xorbs 已下载完成: {output_dir}")
    return xorb_metadata


def analyze_xorbs_offline(
    xorbs_dir: Path,
    recon_file: Path,
):
    """离线分析所有 xorbs 的结构。"""
    logger.info("🔍 开始离线分析 xorbs...")

    # 加载 reconstruction 信息
    with open(recon_file, 'r') as f:
        recon_dict = json.load(f)

    # 加载元数据
    metadata_file = xorbs_dir / "xorbs_metadata.json"
    with open(metadata_file, 'r') as f:
        xorb_metadata = json.load(f)

    analysis_results = []

    for xorb_hash, metadata in xorb_metadata.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"分析 Xorb: {xorb_hash[:16]}...")
        logger.info(f"{'='*60}")

        # 读取压缩数据
        xorb_file = Path(metadata["file"])
        with open(xorb_file, 'rb') as f:
            compressed_data = f.read()

        # 解压 xorb
        try:
            xorb_data = XorbDeserializer.deserialize(compressed_data)
        except Exception as e:
            logger.error(f"❌ 解压失败: {e}")
            continue

        # 获取 chunk_byte_indices
        chunk_byte_indices = xorb_data.get_chunk_byte_indices()

        # 获取 fetch_infos
        fetch_infos = recon_dict["fetch_info"][xorb_hash]

        logger.info(f"\n📊 基本信息:")
        logger.info(f"  压缩大小: {len(compressed_data):,} bytes")
        logger.info(f"  解压大小: {len(xorb_data.data):,} bytes")
        logger.info(f"  Chunk offsets: {len(xorb_data.chunk_offsets)}")
        logger.info(f"  Chunk byte indices: {len(chunk_byte_indices)}")
        logger.info(f"  实际 chunks 数量: {len(chunk_byte_indices) - 1}")

        # 分析 fetch_infos
        logger.info(f"\n📦 Fetch Infos ({len(fetch_infos)} 个):")
        chunk_ranges = []
        for idx, fi in enumerate(fetch_infos):
            cr = fi["chunk_range"]
            chunk_ranges.append((cr["start"], cr["end"]))
            logger.info(
                f"  [{idx}] chunk_range: {cr['start']}-{cr['end']} "
                f"(长度 {cr['end'] - cr['start']})"
            )

        # 计算 merged_range
        merged_start = min(cr[0] for cr in chunk_ranges)
        merged_end = max(cr[1] for cr in chunk_ranges)
        merged_length = merged_end - merged_start

        logger.info(f"\n🔗 Merged Range:")
        logger.info(f"  Start: {merged_start}")
        logger.info(f"  End: {merged_end}")
        logger.info(f"  Length: {merged_length}")
        logger.info(f"  期望 indices 数量: {merged_length + 1}")

        # 检查是否匹配
        expected_indices = merged_length + 1
        actual_indices = len(chunk_byte_indices)

        logger.info(f"\n✅ 匹配检查:")
        logger.info(f"  期望: {expected_indices}")
        logger.info(f"  实际: {actual_indices}")

        if expected_indices == actual_indices:
            logger.info(f"  ✅ 长度匹配")
            match_status = "MATCH"
        else:
            logger.info(f"  ❌ 长度不匹配 (差异: {expected_indices - actual_indices})")
            match_status = "MISMATCH"

            # 详细分析不匹配原因
            logger.info(f"\n🔍 不匹配原因分析:")

            # 检查 chunk_ranges 是否连续
            sorted_ranges = sorted(chunk_ranges, key=lambda r: r[0])
            is_contiguous = True
            for i in range(len(sorted_ranges) - 1):
                if sorted_ranges[i][1] != sorted_ranges[i + 1][0]:
                    is_contiguous = False
                    logger.info(
                        f"  ⚠️ 发现间隙: range[{i}].end={sorted_ranges[i][1]} "
                        f"!= range[{i+1}].start={sorted_ranges[i+1][0]}"
                    )

            if is_contiguous:
                logger.info(f"  ✅ Chunk ranges 是连续的")
            else:
                logger.info(f"  ❌ Chunk ranges 不连续")

            # 检查 xorb 内部的 chunk 编号
            if xorb_data.chunk_offsets:
                chunk_indices = [off[0] for off in xorb_data.chunk_offsets]
                min_chunk = min(chunk_indices)
                max_chunk = max(chunk_indices)
                logger.info(f"  Xorb 内部 chunk 编号范围: {min_chunk}-{max_chunk}")
                logger.info(f"  Xorb 实际包含 {len(set(chunk_indices))} 个不同的 chunks")

        # 保存分析结果
        analysis_results.append({
            "xorb_hash": xorb_hash,
            "compressed_size": len(compressed_data),
            "decompressed_size": len(xorb_data.data),
            "num_chunks": len(chunk_byte_indices) - 1,
            "num_fetch_infos": len(fetch_infos),
            "merged_range": {
                "start": merged_start,
                "end": merged_end,
                "length": merged_length,
            },
            "expected_indices": expected_indices,
            "actual_indices": actual_indices,
            "match_status": match_status,
            "chunk_ranges": chunk_ranges,
        })

    # 保存分析报告
    report_file = xorbs_dir / "analysis_report.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(analysis_results, f, indent=2)

    logger.info(f"\n✅ 分析报告已保存: {report_file}")

    # 汇总统计
    logger.info(f"\n📈 汇总统计:")
    total = len(analysis_results)
    matched = sum(1 for r in analysis_results if r["match_status"] == "MATCH")
    mismatched = total - matched

    logger.info(f"  总计 xorbs: {total}")
    logger.info(f"  ✅ 匹配: {matched} ({matched/total*100:.1f}%)")
    logger.info(f"  ❌ 不匹配: {mismatched} ({mismatched/total*100:.1f}%)")


def main():
    """主函数。"""
    import argparse

    parser = argparse.ArgumentParser(description="调试 chunk 缓存问题")
    parser.add_argument("--repo", default="xet-team/Granite", help="仓库名")
    parser.add_argument(
        "--path",
        default="granite-embedding/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf",
        help="文件路径"
    )
    parser.add_argument("--output-dir", default="debug_data", help="输出目录")
    parser.add_argument("--analyze-only", action="store_true", help="仅分析已下载的数据")

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    recon_file = output_dir / "reconstruction.json"
    xorbs_dir = output_dir / "xorbs"

    if args.analyze_only:
        # 仅分析
        if not recon_file.exists():
            logger.error(f"❌ Reconstruction 文件不存在: {recon_file}")
            return

        analyze_xorbs_offline(xorbs_dir, recon_file)
        return

    # 下载阶段
    config = ConfigManager()

    # 获取认证信息
    auth = XetAuth()
    token_info = auth.get_token(args.repo)

    # 创建 session
    session = requests.Session()

    # 创建 CAS 客户端
    cas_client = CASClient(
        endpoint=token_info.endpoint,
        access_token=token_info.access_token,
        session=session,
        auth=auth,
        repo_id=args.repo,
    )

    # 1. 获取文件信息
    logger.info(f"🔍 检测文件: {args.repo}/{args.path}")
    file_info = cas_client.detect_xet_file(args.repo, args.path)
    file_hash = file_info.file_hash

    logger.info(f"✅ 文件 hash: {file_hash}")
    logger.info(f"   大小: {file_info.file_size:,} bytes")

    # 2. 下载 reconstruction 信息
    recon = download_reconstruction_info(cas_client, file_hash, recon_file)

    # 3. 下载所有 xorbs
    download_all_xorbs(cas_client, recon, xorbs_dir)

    # 4. 离线分析
    analyze_xorbs_offline(xorbs_dir, recon_file)


if __name__ == "__main__":
    main()
