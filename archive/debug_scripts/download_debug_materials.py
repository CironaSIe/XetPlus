#!/usr/bin/env python3
"""下载调试材料：reconstruction 信息和所有 xorb 数据。

目标：
1. 下载 reconstruction JSON（包含所有 chunk 重组指令）
2. 下载所有 xorb 数据并保存到本地
3. 解压 xorb 并记录 chunk_byte_indices
4. 离线分析 chunk_cache_adapter 的逻辑

这些数据是调试材料，不是缓存。
"""
import json
import logging
import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent))

from xet.network.cas_client import CASClient
from xet.network.auth import XetAuth
from xet.cli.config_manager import ConfigManager
from xet.storage.xorb_deserializer import XorbDeserializer
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = __import__('argparse').ArgumentParser(description="下载调试材料")
    parser.add_argument("--repo", default="mykor/granite-embedding-97m-multilingual-r2-GGUF")
    parser.add_argument(
        "--path",
        default="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
    )
    parser.add_argument("--output-dir", default="debug_materials", help="输出目录")
    parser.add_argument("--proxy", default="http://127.0.0.1:12334", help="代理地址")
    parser.add_argument("--hf-token", default="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", help="HuggingFace token")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("="*60)
    logger.info("📦 下载调试材料")
    logger.info("="*60)
    logger.info(f"仓库: {args.repo}")
    logger.info(f"文件: {args.path}")
    logger.info(f"输出: {output_dir}")
    if args.proxy:
        logger.info(f"代理: {args.proxy}")
    logger.info("")

    # 初始化 CAS 客户端
    # 直接使用已知的配置，避免 auth.py 的 resolve 问题
    config = ConfigManager()

    # 创建 session 并配置代理
    session = requests.Session()
    if args.proxy:
        session.proxies = {
            "http": args.proxy,
            "https": args.proxy,
        }

    # 使用已知的 endpoint 和 auth_url
    cas_endpoint = "https://cas-server.xethub.hf.co"
    auth_url = "https://huggingface.co/api/models/mykor/granite-embedding-97m-multilingual-r2-GGUF/xet-read-token/45ce642d3fab2033d167ec09641a159010f7d9d9"

    # 获取 CAS token
    logger.info("🔑 获取 CAS access token...")
    resp = session.get(auth_url, headers={"Authorization": f"Bearer {args.hf_token}"})
    resp.raise_for_status()
    data = resp.json()
    cas_token = data['accessToken']
    cas_endpoint = data.get('endpoint', cas_endpoint)
    logger.info(f"  ✅ Token 获取成功")
    logger.info(f"  CAS endpoint: {cas_endpoint}")
    logger.info("")

    cas_client = CASClient(
        endpoint=cas_endpoint,
        access_token=cas_token,
        session=session,
        auth=None,
        repo_id=args.repo,
    )

    # 1. 获取文件信息
    logger.info("🔍 步骤 1: 获取文件信息")

    # 构造 HuggingFace 文件 URL
    hf_url = f"https://huggingface.co/mykor/granite-embedding-97m-multilingual-r2-GGUF/resolve/45ce642d3fab2033d167ec09641a159010f7d9d9/{args.path}"

    file_info = CASClient.get_xet_file_info(hf_url, session)
    file_hash = file_info.xet_hash
    logger.info(f"  文件 hash: {file_hash}")
    logger.info(f"  文件大小: {file_info.size:,} bytes")
    logger.info("")

    # 2. 下载 reconstruction 信息
    logger.info("📥 步骤 2: 下载 reconstruction 信息")
    recon = cas_client.get_reconstruction(file_hash)

    # 保存为 JSON
    recon_file = output_dir / "reconstruction.json"
    recon_dict = {
        "file_hash": file_hash,
        "file_size": file_info.size,
        "offset_into_first_range": recon.offset_into_first_range,
        "num_terms": len(recon.terms),
        "num_xorbs": len(recon.fetch_info),
        "terms": [
            {
                "idx": idx,
                "hash": term.hash,
                "unpacked_length": term.unpacked_length,
            }
            for idx, term in enumerate(recon.terms)
        ],
        "xorbs": {}
    }

    for xorb_hash, fetch_infos in recon.fetch_info.items():
        recon_dict["xorbs"][xorb_hash] = {
            "num_segments": len(fetch_infos),
            "fetch_infos": [
                {
                    "url": fi.url,
                    "url_range": {"start": fi.url_range.start, "end": fi.url_range.end},
                    "chunk_range": {"start": fi.chunk_range.start, "end": fi.chunk_range.end},
                }
                for fi in fetch_infos
            ]
        }

    with open(recon_file, 'w') as f:
        json.dump(recon_dict, f, indent=2)

    logger.info(f"  ✅ 已保存: {recon_file}")
    logger.info(f"  Terms: {len(recon.terms)}")
    logger.info(f"  Xorbs: {len(recon.fetch_info)}")
    logger.info("")

    # 3. 下载所有 xorbs
    logger.info(f"📥 步骤 3: 下载所有 xorbs ({len(recon.fetch_info)} 个)")
    xorbs_dir = output_dir / "xorbs"
    xorbs_dir.mkdir(exist_ok=True)

    xorb_analysis = {}

    for idx, (xorb_hash, fetch_infos) in enumerate(recon.fetch_info.items(), 1):
        logger.info(f"\n[{idx}/{len(recon.fetch_info)}] {xorb_hash[:16]}...")

        # 下载并合并 segments
        segments = []
        sorted_infos = sorted(fetch_infos, key=lambda fi: fi.chunk_range.start)

        for seg_idx, fi in enumerate(sorted_infos):
            logger.info(
                f"  下载 segment {seg_idx}: "
                f"chunk_range {fi.chunk_range.start}-{fi.chunk_range.end}"
            )
            segment_data = cas_client.get_xorb_data(url=fi.url, url_range=fi.url_range)
            segments.append(segment_data)

        merged_data = b''.join(segments)
        logger.info(f"  合并后: {len(merged_data):,} bytes (compressed)")

        # 解压 xorb
        try:
            xorb_data = XorbDeserializer.deserialize(merged_data)
            chunk_byte_indices = xorb_data.get_chunk_byte_indices()

            logger.info(f"  解压成功: {len(xorb_data.data):,} bytes (decompressed)")
            logger.info(f"  Chunks: {len(chunk_byte_indices) - 1}")

            # 保存解压数据
            decompressed_file = xorbs_dir / f"{xorb_hash}.bin"
            with open(decompressed_file, 'wb') as f:
                f.write(xorb_data.data)

            # 保存分析信息
            xorb_analysis[xorb_hash] = {
                "compressed_size": len(merged_data),
                "decompressed_size": len(xorb_data.data),
                "num_chunks": len(chunk_byte_indices) - 1,
                "chunk_byte_indices": chunk_byte_indices,
                "num_segments": len(segments),
                "fetch_infos": [
                    {
                        "chunk_range": {
                            "start": fi.chunk_range.start,
                            "end": fi.chunk_range.end,
                        }
                    }
                    for fi in sorted_infos
                ]
            }

        except Exception as e:
            logger.error(f"  ❌ 解压失败: {e}")
            xorb_analysis[xorb_hash] = {"error": str(e)}

    # 4. 保存完整分析
    analysis_file = output_dir / "xorb_analysis.json"
    with open(analysis_file, 'w') as f:
        json.dump(xorb_analysis, f, indent=2)

    logger.info(f"\n✅ 所有材料已保存到: {output_dir}")
    logger.info(f"  - {recon_file.name}: reconstruction 信息")
    logger.info(f"  - {analysis_file.name}: xorb 分析结果")
    logger.info(f"  - xorbs/*.bin: 解压后的 xorb 数据")


if __name__ == "__main__":
    main()
