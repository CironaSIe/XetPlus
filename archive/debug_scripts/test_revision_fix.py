#!/usr/bin/env python3
"""测试 revision 参数修复。"""
import sys
sys.path.insert(0, '/data/data/com.termux/files/home/xetplus')

import requests
from xet.cli.commands.download import detect_xet_file

# 测试参数
repo_id = "mykor/granite-embedding-97m-multilingual-r2-GGUF"
filename = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
token = "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"
revision = "45ce642d3fab2033d167ec09641a159010f7d9d9"

# 创建 session
session = requests.Session()
session.proxies = {
    "http": "http://127.0.0.1:12334",
    "https": "http://127.0.0.1:12334",
}

print("=" * 70)
print("测试 XET 文件检测（带 revision 参数）")
print("=" * 70)
print()
print(f"仓库: {repo_id}")
print(f"文件: {filename}")
print(f"Revision: {revision}")
print()

# 测试 1: 使用正确的 revision
print("🧪 测试 1: 使用正确的 revision (commit hash)")
result1 = detect_xet_file(repo_id, "model", filename, token, session, revision=revision)
if result1:
    print("✅ 检测成功！")
    print(f"   Xet Hash: {result1['xet_hash'][:16]}...")
    print(f"   Size: {result1['size']:,} bytes")
    print(f"   SHA256: {result1['sha256'][:16]}...")
else:
    print("❌ 检测失败")
print()

# 测试 2: 使用错误的 revision (main 分支)
print("🧪 测试 2: 使用错误的 revision (main 分支)")
result2 = detect_xet_file(repo_id, "model", filename, token, session, revision="main")
if result2:
    print("⚠️  检测成功（但文件可能不同）")
    print(f"   Xet Hash: {result2['xet_hash'][:16]}...")
else:
    print("❌ 检测失败（预期结果，因为 main 分支上文件可能不存在或不同）")
print()

# 测试 3: 不指定 revision（使用默认值 main）
print("🧪 测试 3: 不指定 revision（默认 main）")
result3 = detect_xet_file(repo_id, "model", filename, token, session)
if result3:
    print("⚠️  检测成功（使用默认 main 分支）")
    print(f"   Xet Hash: {result3['xet_hash'][:16]}...")
else:
    print("❌ 检测失败（预期结果）")
print()

print("=" * 70)
print("结论")
print("=" * 70)
if result1:
    print("✅ 修复成功！detect_xet_file 现在支持 revision 参数")
    print("   文件正确识别为 XET 格式")
else:
    print("❌ 修复失败，仍然无法检测")
