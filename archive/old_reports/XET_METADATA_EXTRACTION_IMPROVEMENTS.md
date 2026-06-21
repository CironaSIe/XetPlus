# XET 元数据提取全面改进报告

**日期**: 2026-06-21  
**改进范围**: 所有涉及 XET 文件检测和元数据提取的模块

---

## 改进目标

1. **提高健壮性**: 支持多种 xet-hash 提取方式，避免协议变化导致失败
2. **添加 SHA256**: 支持完整文件下载后的校验
3. **修正文件大小**: 使用正确的文件大小字段
4. **统一逻辑**: 在所有模块中应用相同的三级 fallback 策略

---

## 改进的文件列表

### 1. `xet/cli/commands/info.py`
**函数**: `detect_xet_file()`

**改进前**:
```python
# 只支持一种格式
match = re.search(r'<xet://([^>]+)>;\s*rel="xet-hash"', link_header)
if match:
    xet_hash = match.group(1)

# 简单的 fallback
if not xet_hash:
    match = re.search(r'<https://[^/]+/v1/reconstructions/([0-9a-f]{64})[^>]*>;\s*rel="xet-reconstruction-info"', link_header)
```

**改进后**:
```python
# 三级 fallback
# 方法1: 标准 xet:// 协议格式
match = re.search(
    r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
    link_header,
    re.IGNORECASE
)

# 方法2: reconstruction-info URL（通用）
match = re.search(
    r'<https?://[^/]+/[^/]*/reconstructions?/([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-reconstruction',
    link_header,
    re.IGNORECASE
)

# 方法3: 任何 URL 中的 64 字符 hex 串
match = re.search(
    r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
    link_header,
    re.IGNORECASE
)
```

**新增功能**:
- ✓ SHA256 提取（从 `X-Linked-ETag`）
- ✓ 文件大小修正（优先使用 `X-Linked-Size`）
- ✓ 显示 SHA256 字段

---

### 2. `xet/cli/commands/download.py`
**函数**: `detect_xet_file()`

**改进前**:
```python
# 只支持 X-Xet-Hash 头和简单的 URL 提取
xet_hash = resp.headers.get("X-Xet-Hash")

if not xet_hash and recon_url:
    hash_match = re.search(r'/reconstructions/([a-f0-9]{64})', recon_url)
    if hash_match:
        xet_hash = hash_match.group(1)
```

**改进后**:
```python
# 四级 fallback（包含 X-Xet-Hash 头）
# 方法1: X-Xet-Hash 头（直接提供）
xet_hash = resp.headers.get("X-Xet-Hash")

# 方法2: 标准 xet:// 协议格式
if not xet_hash and link_header:
    match = re.search(
        r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
        link_header,
        re.IGNORECASE
    )

# 方法3: reconstruction-info URL（通用）
if not xet_hash and recon_url:
    match = re.search(
        r'/reconstructions?/([0-9a-f]{64})',
        recon_url,
        re.IGNORECASE
    )

# 方法4: 任何 URL 中的 64 字符 hex 串
if not xet_hash and link_header:
    match = re.search(
        r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
        link_header,
        re.IGNORECASE
    )
```

**已有功能**:
- ✓ SHA256 提取（已存在）
- ✓ 文件大小正确（已存在）

---

### 3. `xet/protocol/types.py`
**类**: `XetFileInfo`  
**方法**: `from_headers()`

**改进前**:
```python
# 只支持 X-Xet-Hash 头，不支持 fallback
xet_hash = headers.get('X-Xet-Hash') or headers.get('x-xet-hash')
if not xet_hash:
    raise ValueError("Missing X-Xet-Hash header")
```

**改进后**:
```python
# 三级 fallback（与 info.py 相同）
xet_hash = headers.get('X-Xet-Hash') or headers.get('x-xet-hash')

if not xet_hash:
    link_header = headers.get('Link', '') or headers.get('link', '')
    if link_header:
        # 方法1: 标准 xet:// 协议格式
        # 方法2: reconstruction-info URL
        # 方法3: 通用 64 字符 hex 串
        ...

if not xet_hash:
    raise ValueError("Missing X-Xet-Hash header and unable to extract from Link header")
```

**已有功能**:
- ✓ SHA256 提取（已存在）
- ✓ 文件大小正确（已存在）

---

## 其他涉及 XET 元数据的文件

### 4. `xet/network/host_optimizer.py`
**功能**: 检测 XET 文件（用于 HOST 优化）

**当前实现**:
```python
xet_etag = resp.headers.get("x-linked-etag") or resp.headers.get("X-Linked-ETag")
if 'rel="xet-auth"' in link_header or 'rel="xet-reconstruction-info"' in link_header:
    return True, xet_etag
```

**状态**: ✓ 无需改进（只检测是否为 XET 文件，不提取 hash）

---

### 5. `xet/network/auth.py`
**功能**: 提取 `xet-auth` URL

**当前实现**:
```python
for url, rel in matches:
    if rel == 'xet-auth':
        return url
```

**状态**: ✓ 无需改进（只提取 auth URL，不提取 hash）

---

### 6. `xet/network/cas_client.py`
**功能**: 验证 reconstruction 响应

**当前实现**:
```python
if 'X-Xet-Hash' not in resp.headers and 'x-xet-hash' not in resp.headers:
    raise XetError(...)
```

**状态**: ✓ 无需改进（CAS 服务器响应必须有 X-Xet-Hash 头）

---

## 三级 Fallback 策略详解

### 方法1: 标准 `xet://` 协议格式
```
Link: <xet://e0aacd103e054264...>; rel="xet-hash"
```

**正则**:
```python
r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?'
```

**特性**:
- 大小写不敏感（`re.IGNORECASE`）
- 引号灵活（`["\']?`）
- 空格容忍（`(?:;|\s*;)\s*`）
- Hash 验证（`[0-9a-f]{64}`）

---

### 方法2: Reconstruction URL 提取
```
Link: <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd103e054264...>; rel="xet-reconstruction-info"
```

**正则**:
```python
r'<https?://[^/]+/[^/]*/reconstructions?/([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-reconstruction'
```

**特性**:
- 域名无关（`[^/]+`）
- 版本无关（`/[^/]*/` 匹配 `/v1/`, `/v2/` 等）
- 单复数形式（`reconstructions?`）
- 协议灵活（`https?://`）

---

### 方法3: 通用 64 字符 hex 提取
```
Link: <https://cdn.example.com/files/e0aacd103e054264...>; rel=xet-file
```

**正则**:
```python
r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet'
```

**特性**:
- 最大容错性
- 只要 rel 包含 "xet" 且 URL 包含 64 字符 hex

---

## SHA256 提取（完整文件校验）

### 响应头位置
```http
X-Linked-ETag: "355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"
```

### 提取代码
```python
sha256 = None
linked_etag = resp.headers.get("X-Linked-ETag")
if linked_etag:
    sha256 = linked_etag.strip('"')  # 去掉引号
```

### 用途
- XET Hash: 用于从 CAS 服务器重建文件（分块下载）
- SHA256: 用于验证下载后的完整文件是否正确

---

## 文件大小修正

### 问题
```python
# 错误：使用 Content-Length（302 响应体大小）
content_length = resp.headers.get("Content-Length")  # 1098 bytes
size = int(content_length)
```

### 修正
```python
# 正确：优先使用 X-Linked-Size（真实文件大小）
linked_size = resp.headers.get("X-Linked-Size")      # 105467232 bytes
content_length = resp.headers.get("Content-Length")   # 1098 bytes
size = int(linked_size) if linked_size else (int(content_length) if content_length else 0)
```

### 响应头对比
```http
Content-Length: 1098              ← 302 响应体大小
X-Linked-Size: 105467232          ← 真实文件大小（100.6 MB）
```

---

## 测试验证

### 改进前（P3 测试失败）
```
[1/4] TC-P3-01: info 命令
   → 执行 info 命令...
   → 验证输出...
❌ 测试失败！info 输出缺少必要字段

📄 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
  类型: XET ✅
  大小: 1.1 KB (1,100 bytes)      ← 错误！
  Xet Hash: (未提取)               ← 失败！
```

### 改进后（P3 测试通过）
```
[1/4] TC-P3-01: info 命令
   → 执行 info 命令...
   → 验证输出...
✅ 测试通过！info 命令输出正确

📄 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
  类型: XET ✅
  大小: 100.6 MB (105,467,232 bytes)  ← 正确！
  Xet Hash: e0aacd103e054264...        ← 成功提取！
  SHA256: 355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf  ← 新增！
  Terms: 17
  Xorbs: 10 (unique)
  ...
```

---

## HuggingFace vs hf-mirror 兼容性

### 测试结果
两者都**完全支持** XET 协议！

| 响应头 | HuggingFace.co | hf-mirror.com |
|--------|----------------|---------------|
| Link (xet-auth) | ✓ | ✓ |
| Link (xet-reconstruction-info) | ✓ | ✓ |
| X-Linked-ETag (SHA256) | ✓ | ✓ |
| X-Linked-Size | ✓ | ✓ |

**区别**:
- xet-auth URL 中的域名：`huggingface.co` vs `hf-mirror.com`
- 最终都重定向到相同的 CAS Bridge
- 三级 fallback 同时支持两个端点

---

## 协议演进覆盖

### 场景1: 当前 HuggingFace 格式
```
Link: <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd...>; rel="xet-reconstruction-info"
→ 方法2 匹配 ✓
```

### 场景2: 未来 v2 API
```
Link: <https://new-domain.com/v2/reconstruction/e0aacd...>; rel='XET-Reconstruction-Info'
→ 方法2 匹配 ✓（单数、v2、单引号、大小写）
```

### 场景3: 标准格式（未来可能）
```
Link: <xet://e0aacd...>; rel="xet-hash"
→ 方法1 匹配 ✓
```

### 场景4: 其他平台
```
Link: <https://cdn.example.com/files/e0aacd...>; rel=xet-file
→ 方法3 匹配 ✓
```

---

## 改进总结

### 改进的文件（3个）
1. ✅ `xet/cli/commands/info.py` - 三级 fallback + SHA256 + 文件大小
2. ✅ `xet/cli/commands/download.py` - 四级 fallback（含 X-Xet-Hash）
3. ✅ `xet/protocol/types.py` - 三级 fallback

### 无需改进的文件（3个）
4. ✓ `xet/network/host_optimizer.py` - 只检测是否为 XET
5. ✓ `xet/network/auth.py` - 只提取 auth URL
6. ✓ `xet/network/cas_client.py` - CAS 响应必须有 X-Xet-Hash

### 新增功能
- ✅ SHA256 提取和显示
- ✅ 文件大小修正
- ✅ 三级/四级 fallback
- ✅ HuggingFace 和 hf-mirror 同时支持

### 测试结果
- ✅ P3-01: info 命令测试通过
- 🔄 P3-02: config 命令测试进行中
- ⏳ P3-03: 完整下载工作流待测试
- ⏳ P3-04: 批量下载待测试

---

## 文档产出

1. **XET_HASH_EXTRACTION_METHODS.md** - HEAD 命令和 Hash 提取完整说明
2. **HUGGINGFACE_VS_HFMIRROR.md** - 两个端点的详细对比
3. **XET_HASH_EXTRACTION_IMPROVEMENT.md** - 改进方案设计
4. **XET_HASH_IMPROVEMENT_SUMMARY.md** - 改进总结（本文档）

---

## 下一步

- ✅ 三级 fallback 正则已应用到所有相关模块
- ✅ SHA256 提取已实现
- ✅ 文件大小修正已实现
- ✅ HuggingFace 和 hf-mirror 兼容性验证
- 🔄 等待 P3 完整测试结果
- ⏳ 如需要，可以添加单元测试覆盖所有 fallback 路径
