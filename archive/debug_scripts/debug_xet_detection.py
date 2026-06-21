#!/usr/bin/env python3
"""调试 XET 文件检测问题。"""
import requests
import re

# 测试的 URL
url = "https://huggingface.co/mykor/granite-embedding-97m-multilingual-r2-GGUF/resolve/45ce642d3fab2033d167ec09641a159010f7d9d9/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
token = "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"

print("=" * 70)
print("🔍 调试 XET 文件检测")
print("=" * 70)
print()
print(f"URL: {url}")
print()

# 发送 HEAD 请求
headers = {"Authorization": f"Bearer {token}"}

print("发送 HEAD 请求...")
resp = requests.head(url, headers=headers, allow_redirects=False, timeout=30,
                     proxies={"http": "http://127.0.0.1:12334", "https": "http://127.0.0.1:12334"})

print(f"状态码: {resp.status_code}")
print()

# 打印所有响应头
print("响应头:")
for key, value in sorted(resp.headers.items()):
    print(f"  {key}: {value}")
print()

# 检查关键的 header
print("=" * 70)
print("关键 Headers 检查")
print("=" * 70)
print()

xet_hash = resp.headers.get("X-Xet-Hash")
print(f"X-Xet-Hash: {xet_hash}")
if xet_hash:
    print("  ✅ 存在")
else:
    print("  ❌ 不存在")
print()

link_header = resp.headers.get("Link", "")
print(f"Link: {link_header[:100]}..." if len(link_header) > 100 else f"Link: {link_header}")
if link_header:
    print("  ✅ 存在")
    match = re.search(r'<([^>]+)>;\s*rel="xet-auth"', link_header)
    if match:
        auth_url = match.group(1)
        print(f"  Auth URL: {auth_url}")
    else:
        print("  ⚠️  未找到 xet-auth")
else:
    print("  ❌ 不存在")
print()

linked_size = resp.headers.get("X-Linked-Size")
print(f"X-Linked-Size: {linked_size}")
if linked_size:
    print(f"  ✅ {int(linked_size):,} bytes")
else:
    print("  ❌ 不存在")
print()

linked_etag = resp.headers.get("X-Linked-ETag")
print(f"X-Linked-ETag: {linked_etag}")
if linked_etag:
    print(f"  ✅ {linked_etag.strip('\"')}")
else:
    print("  ❌ 不存在")
print()

# 判断结果
print("=" * 70)
print("结论")
print("=" * 70)
print()

if resp.status_code in (301, 302, 307, 308):
    print("✅ 状态码正确（重定向）")
else:
    print(f"❌ 状态码错误：期望 301/302/307/308，实际 {resp.status_code}")

if xet_hash:
    print("✅ 有 X-Xet-Hash")
else:
    print("❌ 无 X-Xet-Hash")

if link_header and 'xet-auth' in link_header:
    print("✅ 有 xet-auth Link")
else:
    print("❌ 无 xet-auth Link")

print()
if xet_hash and link_header and resp.status_code in (301, 302, 307, 308):
    print("✅ 这是一个有效的 XET 文件！")
else:
    print("❌ 不满足 XET 文件检测条件")
