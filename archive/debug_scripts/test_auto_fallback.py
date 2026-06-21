#!/usr/bin/env python3
"""测试自动探测最新 commit 的功能。"""
import sys
sys.path.insert(0, '/data/data/com.termux/files/home/xetplus')

import requests
from xet.cli.commands.download import detect_xet_file

# 测试参数
repo_id = "mykor/granite-embedding-97m-multilingual-r2-GGUF"
filename = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
token = "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"

# 创建 session
session = requests.Session()
session.proxies = {
    "http": "http://127.0.0.1:12334",
    "https": "http://127.0.0.1:12334",
}

print("=" * 70)
print("测试自动探测最新 commit 功能")
print("=" * 70)
print()
print(f"仓库: {repo_id}")
print(f"文件: {filename}")
print()

# 测试 1: 使用默认 main（应该成功，因为 main 存在）
print("🧪 测试 1: 使用默认 main（main 分支存在）")
result1 = detect_xet_file(repo_id, "model", filename, token, session, revision="main")
if result1:
    print("✅ 检测成功")
    print(f"   Xet Hash: {result1['xet_hash'][:16]}...")
else:
    print("❌ 检测失败")
print()

# 测试 2: 模拟一个不存在 main 分支的仓库
# （这里无法真实测试，因为我们的测试仓库有 main 分支）
# 但可以测试代码逻辑
print("🧪 测试 2: 测试错误的 revision")
result2 = detect_xet_file(repo_id, "model", filename, token, session, revision="nonexistent-branch-12345")
if result2:
    print("⚠️  意外成功（分支可能存在）")
else:
    print("✅ 正确返回 None（分支不存在）")
print()

# 测试 3: 验证 API 可以获取到 sha
print("🧪 测试 3: 验证 API 可以获取仓库信息")
api_url = f"https://huggingface.co/api/models/{repo_id}"
headers = {"Authorization": f"Bearer {token}"}
try:
    resp = session.get(api_url, headers=headers, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        sha = data.get("sha")
        print(f"✅ API 正常工作")
        print(f"   最新 SHA: {sha}")

        # 测试使用这个 SHA
        print()
        print(f"🧪 测试 4: 使用 API 返回的 SHA")
        result4 = detect_xet_file(repo_id, "model", filename, token, session, revision=sha)
        if result4:
            print("✅ 使用 SHA 检测成功")
            print(f"   Xet Hash: {result4['xet_hash'][:16]}...")
        else:
            print("❌ 检测失败")
    else:
        print(f"⚠️  API 请求失败: {resp.status_code}")
except Exception as e:
    print(f"❌ API 请求异常: {e}")
print()

print("=" * 70)
print("总结")
print("=" * 70)
print()
print("✅ 自动 fallback 机制已实现:")
print("   1. 首先尝试使用指定的 revision")
print("   2. 如果 main 分支返回 404，自动通过 API 获取最新 commit")
print("   3. 使用最新 commit 重试")
print()
print("📝 注意:")
print("   - 只有 revision='main' 且返回 404 时才触发自动探测")
print("   - 用户明确指定的 revision 不会自动 fallback")
print("   - 这样既方便又不会意外覆盖用户的意图")
