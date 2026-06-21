#!/usr/bin/env python3
"""测试 HuggingFace API 获取最新 commit。"""
import requests
import json

repo_id = "mykor/granite-embedding-97m-multilingual-r2-GGUF"
token = "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"

session = requests.Session()
session.proxies = {
    "http": "http://127.0.0.1:12334",
    "https": "http://127.0.0.1:12334",
}

print("=" * 70)
print("测试获取仓库最新 commit")
print("=" * 70)
print()

# 方法 1: /api/models/{repo_id} 获取仓库信息
print("方法 1: GET /api/models/{repo_id}")
url = f"https://huggingface.co/api/models/{repo_id}"
headers = {"Authorization": f"Bearer {token}"}

try:
    resp = session.get(url, headers=headers, timeout=30)
    print(f"状态码: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        print(f"✅ 成功获取仓库信息")
        print(f"   SHA: {data.get('sha', 'N/A')}")
        print(f"   lastModified: {data.get('lastModified', 'N/A')}")
        print(f"   默认分支: {data.get('branch', 'N/A')}")

        # 打印完整响应（调试用）
        print()
        print("完整响应 (前 500 字符):")
        print(json.dumps(data, indent=2)[:500])
    else:
        print(f"❌ 失败: {resp.text[:200]}")
except Exception as e:
    print(f"❌ 异常: {e}")

print()
print("=" * 70)

# 方法 2: /api/models/{repo_id}/revision/{branch}
print("方法 2: GET /api/models/{repo_id}/revision/main")
url = f"https://huggingface.co/api/models/{repo_id}/revision/main"

try:
    resp = session.get(url, headers=headers, timeout=30)
    print(f"状态码: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        print(f"✅ 成功获取 main 分支信息")
        print(f"   SHA: {data.get('sha', 'N/A')}")

        print()
        print("完整响应 (前 500 字符):")
        print(json.dumps(data, indent=2)[:500])
    elif resp.status_code == 404:
        print(f"⚠️  main 分支不存在")
    else:
        print(f"❌ 失败: {resp.text[:200]}")
except Exception as e:
    print(f"❌ 异常: {e}")

print()
print("=" * 70)

# 方法 3: HEAD 请求文件，查看 X-Repo-Commit header
print("方法 3: HEAD 请求文件，查看响应头")
filename = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"

try:
    resp = session.head(url, headers=headers, allow_redirects=False, timeout=30)
    print(f"状态码: {resp.status_code}")

    commit = resp.headers.get("X-Repo-Commit")
    if commit:
        print(f"✅ X-Repo-Commit: {commit}")
    else:
        print(f"❌ 无 X-Repo-Commit header")

    print()
    print("所有 X- 开头的响应头:")
    for key, value in sorted(resp.headers.items()):
        if key.startswith("X-"):
            print(f"   {key}: {value}")

except Exception as e:
    print(f"❌ 异常: {e}")

print()
print("=" * 70)
print("结论")
print("=" * 70)
print("推荐方案: 使用 /api/models/{repo_id} 获取 sha 作为最新 commit")
