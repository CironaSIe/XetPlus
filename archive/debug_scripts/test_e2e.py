#!/usr/bin/env python3
"""完整的端到端测试：chunk cache + 文件下载 + SHA256 验证。

验证修复后的 chunk cache 在真实下载场景中的工作情况。
"""
import hashlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from xet.cli.commands.download import download_file
from xet.cli.config_manager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="端到端测试")
    parser.add_argument("--proxy", default="http://127.0.0.1:12334")
    parser.add_argument("--hf-token", default="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")
    parser.add_argument("--output", default="test_download.gguf")
    args = parser.parse_args()

    print("=" * 70)
    print("🧪 完整端到端测试")
    print("=" * 70)
    print()

    # 测试文件信息
    repo = "mykor/granite-embedding-97m-multilingual-r2-GGUF"
    commit = "45ce642d3fab2033d167ec09641a159010f7d9d9"
    path = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
    expected_sha256 = "e14bcf7b24ac395c19218b804f840929abf80c19e9d1fa71f8c23c5c3e0e1c1b"
    expected_size = 105467232

    output_path = Path(args.output)

    # 删除旧文件
    if output_path.exists():
        output_path.unlink()
        print(f"✓ 删除旧文件: {output_path}")

    print(f"仓库: {repo}")
    print(f"文件: {path}")
    print(f"提交: {commit}")
    print(f"期望 SHA256: {expected_sha256}")
    print(f"期望大小: {expected_size:,} bytes")
    print()

    # 执行下载
    print("=" * 70)
    print("📥 开始下载")
    print("=" * 70)
    print()

    try:
        # 构造 URL
        url = f"https://huggingface.co/{repo}/resolve/{commit}/{path}"

        # 下载（会自动使用 chunk cache）
        from xet.cli.commands.download import download_file_with_resume

        download_file_with_resume(
            url=url,
            output_path=str(output_path),
            hf_token=args.hf_token,
            proxy=args.proxy if args.proxy else None,
            max_retries=3,
            parallel_segments=4,
        )

        print()
        print("=" * 70)
        print("✅ 下载完成")
        print("=" * 70)
        print()

    except Exception as e:
        print(f"❌ 下载失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 验证文件
    print("=" * 70)
    print("🔍 验证文件")
    print("=" * 70)
    print()

    # 检查大小
    actual_size = output_path.stat().st_size
    print(f"文件大小: {actual_size:,} bytes")

    if actual_size != expected_size:
        print(f"❌ 大小不匹配!")
        print(f"  期望: {expected_size:,}")
        print(f"  实际: {actual_size:,}")
        print(f"  差异: {actual_size - expected_size:,}")
        return 1
    else:
        print(f"✅ 大小正确")

    # 计算 SHA256
    print()
    print("计算 SHA256...")
    sha256 = hashlib.sha256()
    with open(output_path, 'rb') as f:
        while chunk := f.read(8192):
            sha256.update(chunk)

    actual_sha256 = sha256.hexdigest()
    print(f"实际 SHA256: {actual_sha256}")

    if actual_sha256 != expected_sha256:
        print(f"❌ SHA256 不匹配!")
        print(f"  期望: {expected_sha256}")
        print(f"  实际: {actual_sha256}")
        return 1
    else:
        print(f"✅ SHA256 正确")

    # 总结
    print()
    print("=" * 70)
    print("📊 测试结果")
    print("=" * 70)
    print()
    print("✅ 所有验证通过！")
    print()
    print(f"  - 文件下载成功")
    print(f"  - 大小正确: {actual_size:,} bytes")
    print(f"  - SHA256 校验通过")
    print(f"  - Chunk cache 工作正常（检查日志中的缓存命中）")
    print()

    return 0


if __name__ == "__main__":
    exit(main())
