# XET Hash 提取方法完整说明

**日期**: 2026-06-21  
**问题**: HEAD 命令与 XET Hash 提取的关系

---

## HEAD 命令的作用

在 XET 协议中，**HEAD 请求是获取 XET 文件元数据的标准方法**，它通过 HTTP 响应头返回关键信息而不下载文件本身。

### HEAD 请求返回的关键响应头

```http
HTTP/1.1 302 Found
Content-Length: 1098
X-Repo-Commit: 45ce642d3fab2033d167ec09641a159010f7d9d9
X-Linked-Size: 105467232
X-Linked-ETag: "355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"
Link: <https://huggingface.co/api/models/.../xet-read-token/...>; rel="xet-auth",
      <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel="xet-reconstruction-info"
```

---

## XET Hash 的三种提取方法（优先级从高到低）

### 方法1: 标准 `xet://` 协议格式（理想状态）

**Link Header 格式**:
```
Link: <xet://e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel="xet-hash"
```

**提取正则**:
```python
match = re.search(
    r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
    link_header,
    re.IGNORECASE
)
```

**优点**: 明确、标准化  
**缺点**: HuggingFace 当前不使用此格式

---

### 方法2: 从 `xet-reconstruction-info` URL 提取（当前HF标准）

**Link Header 格式**:
```
Link: <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel="xet-reconstruction-info"
```

**提取正则**:
```python
match = re.search(
    r'<https?://[^/]+/[^/]*/reconstructions?/([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-reconstruction',
    link_header,
    re.IGNORECASE
)
```

**特点**:
- 不限定域名（`[^/]+` 匹配任意域名）
- 不限定版本号（`/[^/]*/` 匹配 `/v1/`, `/v2/` 等）
- 支持单复数形式（`reconstructions?` 匹配 `reconstruction` 或 `reconstructions`）
- 大小写不敏感（`re.IGNORECASE`）
- 引号灵活（`["\']?` 支持双引号、单引号或无引号）

**优点**: HuggingFace 当前标准格式  
**缺点**: 依赖 URL 结构

---

### 方法3: 通用 64 字符 hex 提取（最后 fallback）

**Link Header 格式**（任何包含 64 字符 hex 的 xet 相关 Link）:
```
Link: <https://cdn.example.com/files/e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel=xet-file
```

**提取正则**:
```python
match = re.search(
    r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
    link_header,
    re.IGNORECASE
)
```

**优点**: 最大容错性  
**缺点**: 可能误匹配（但概率极低，因为要求 rel 包含 "xet"）

---

## SHA256 的提取方法（用于完整文件校验）

**不在 Link 头中！** SHA256 在独立的响应头中：

### `X-Linked-ETag` 头

```http
X-Linked-ETag: "355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"
```

**提取代码**:
```python
sha256 = None
linked_etag = resp.headers.get("X-Linked-ETag")
if linked_etag:
    sha256 = linked_etag.strip('"')  # 去掉引号
```

**作用**: 
- XET Hash 用于从 CAS 服务器重建文件
- SHA256 用于验证下载后的完整文件是否正确

---

## 完整的文件大小获取

```python
# 优先使用 X-Linked-Size（真实文件大小）
linked_size = resp.headers.get("X-Linked-Size")
content_length = resp.headers.get("Content-Length")
size = int(linked_size) if linked_size else (int(content_length) if content_length else 0)
```

**原因**: 
- `Content-Length`: 302 响应体的大小（小文件，如 1098 bytes）
- `X-Linked-Size`: 实际 XET 文件的大小（大文件，如 105467232 bytes）

---

## HEAD 命令的使用场景

### 1. 检测文件是否为 XET 格式
```python
resp = session.head(file_url, headers=headers, allow_redirects=False, timeout=30)
if resp.status_code in (301, 302, 307, 308):
    link_header = resp.headers.get("Link", "")
    if "xet-auth" in link_header and "xet-reconstruction" in link_header:
        # 是 XET 文件
```

### 2. 获取认证 URL
```python
match = re.search(r'<([^>]+)>;\s*rel="xet-auth"', link_header)
if match:
    auth_url = match.group(1)
    if not auth_url.startswith("http"):
        auth_url = f"https://huggingface.co{auth_url}"
```

### 3. 获取 XET Hash（重建文件用）
使用上述三种方法的 fallback 链

### 4. 获取 SHA256（校验用）
从 `X-Linked-ETag` 头提取

### 5. 获取真实文件大小
从 `X-Linked-Size` 头提取

---

## 完整的 detect_xet_file() 流程

```python
def detect_xet_file(repo_id, repo_type, filename, token, session):
    # 1. 构造文件 URL
    file_url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. 发送 HEAD 请求（不下载文件）
    resp = session.head(file_url, headers=headers, allow_redirects=False, timeout=30)
    
    # 3. 检查是否为重定向响应
    if resp.status_code not in (301, 302, 307, 308):
        return None
    
    # 4. 检查 Link 头
    link_header = resp.headers.get("Link", "")
    if not link_header:
        return None
    
    # 5. 提取 auth_url
    auth_url = extract_auth_url(link_header)
    
    # 6. 提取 xet_hash（三级 fallback）
    xet_hash = extract_xet_hash(link_header)
    
    # 7. 提取 SHA256
    sha256 = resp.headers.get("X-Linked-ETag", "").strip('"')
    
    # 8. 提取文件大小
    size = int(resp.headers.get("X-Linked-Size", 0))
    
    return {
        "xet_hash": xet_hash,    # 用于 CAS 重建
        "auth_url": auth_url,    # 用于获取 CAS token
        "size": size,            # 真实文件大小
        "sha256": sha256,        # 用于完整文件校验
    }
```

---

## 为什么需要三级 fallback？

### 协议演进历史
1. **早期**: 可能使用 `xet://hash` 格式
2. **当前**: HuggingFace 使用 reconstruction URL 嵌入 hash
3. **未来**: 可能改为 v2 API、不同域名、或新的格式

### 实际案例
- **当前 HF**: `/v1/reconstructions/{hash}`
- **未来可能**: `/v2/reconstruction/{hash}` (单数、v2)
- **其他平台**: `https://cdn.xet.io/files/{hash}`

### 三级 fallback 的价值
```python
# 如果只用一个正则，这些都会失败：
"<https://new-domain.com/v2/reconstruction/...>; rel='XET-Reconstruction'"  # 单数、v2、单引号、大写
"<https://cdn.example.com/api/reconstructions/...>;rel=xet-recon-info"      # 无引号、缩写
"<xet-file://...>; rel=\"xet-hash\""                                         # 协议变化

# 三级 fallback 全部覆盖
```

---

## 总结

**HEAD 命令是 XET 协议的核心**:
1. ✅ 不下载文件，只获取元数据
2. ✅ 返回 XET Hash（用于重建）
3. ✅ 返回 SHA256（用于校验）
4. ✅ 返回认证 URL（用于获取 CAS token）
5. ✅ 返回真实文件大小

**三级 fallback 策略**:
1. 标准 `xet://` 格式（最严格）
2. Reconstruction URL 提取（当前标准）
3. 通用 hex 提取（最宽松）

**关键响应头**:
- `Link`: 包含 xet-auth、xet-reconstruction-info
- `X-Linked-ETag`: SHA256 校验和
- `X-Linked-Size`: 真实文件大小
- `X-Repo-Commit`: Git commit hash
