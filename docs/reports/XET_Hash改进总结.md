# XET Hash 提取改进总结

**日期**: 2026-06-21  
**改进范围**: xet/cli/commands/info.py

---

## 改进内容

### 1. 三级 Fallback 正则表达式

**目标**: 提高 xet-hash 提取的健壮性，支持未来协议变化

#### 方法1: 标准 `xet://` 协议格式
```python
match = re.search(
    r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
    link_header,
    re.IGNORECASE
)
```

**特性**:
- 大小写不敏感（`re.IGNORECASE`）
- 引号灵活（`["\']?` 支持双引号、单引号、无引号）
- 空格容忍（`(?:;|\s*;)\s*` 支持 `>;` 或 `> ;`）
- Hash 验证（`[0-9a-f]{64}` 确保是 64 字符 hex）

#### 方法2: Reconstruction URL 提取（当前 HF 标准）
```python
match = re.search(
    r'<https?://[^/]+/[^/]*/reconstructions?/([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-reconstruction',
    link_header,
    re.IGNORECASE
)
```

**特性**:
- 域名无关（`[^/]+` 匹配任意域名）
- 版本无关（`/[^/]*/` 匹配 `/v1/`, `/v2/` 等）
- 单复数形式（`reconstructions?` 匹配 `reconstruction` 或 `reconstructions`）
- 协议灵活（`https?://` 支持 HTTP 和 HTTPS）

#### 方法3: 通用 64 字符 hex 提取
```python
match = re.search(
    r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
    link_header,
    re.IGNORECASE
)
```

**特性**:
- 最大容错性
- 任何包含 64 字符 hex 的 xet 相关 Link

---

### 2. SHA256 提取

**新增功能**: 从 `X-Linked-ETag` 头提取 SHA256

```python
# SHA256（从 X-Linked-ETag 提取，去掉引号）
sha256 = None
linked_etag = resp.headers.get("X-Linked-ETag")
if linked_etag:
    sha256 = linked_etag.strip('"')

return {
    "xet_hash": xet_hash,
    "auth_url": auth_url,
    "size": size,
    "sha256": sha256,  # 新增
}
```

**用途**: 用于完整文件下载后的校验

---

### 3. 文件大小修正

**修正前**:
```python
content_length = resp.headers.get("Content-Length")
size = int(content_length) if content_length else 0
```

**修正后**:
```python
# 优先使用 X-Linked-Size（真实文件大小）
linked_size = resp.headers.get("X-Linked-Size")
content_length = resp.headers.get("Content-Length")
size = int(linked_size) if linked_size else (int(content_length) if content_length else 0)
```

**原因**:
- `Content-Length`: 302 响应体大小（小，如 1098 bytes）
- `X-Linked-Size`: 真实文件大小（大，如 105467232 bytes）

---

### 4. 显示改进

**修正前**:
```
📄 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
  类型: XET ✅
  大小: 1.1 KB (1,100 bytes)  ← 错误！
  Xet Hash: e0aacd103e054264f5ede71ce63218c1...
```

**修正后**:
```
📄 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
  类型: XET ✅
  大小: 100.6 MB (105,467,232 bytes)  ← 正确！
  Xet Hash: e0aacd103e054264f5ede71ce63218c1...
  SHA256: 355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf  ← 新增！
  Terms: 17
  Xorbs: 10 (unique)
  ...
```

---

## 覆盖的协议变化场景

### 场景1: 标准格式
```
Link: <xet://e0aacd...>; rel="xet-hash"
→ 方法1 匹配
```

### 场景2: HuggingFace 当前格式
```
Link: <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd...>; rel="xet-reconstruction-info"
→ 方法2 匹配
```

### 场景3: 未来 v2 API
```
Link: <https://new-domain.com/v2/reconstruction/e0aacd...>; rel='XET-Reconstruction-Info'
→ 方法2 匹配（单数、v2、单引号、大小写）
```

### 场景4: 其他平台
```
Link: <https://cdn.example.com/files/e0aacd...>; rel=xet-file
→ 方法3 匹配（最后 fallback）
```

---

## HuggingFace vs hf-mirror 兼容性

### 测试结果

| 特性 | HuggingFace.co | hf-mirror.com |
|------|----------------|---------------|
| Link 头（xet-auth） | ✓ | ✓ |
| Link 头（xet-reconstruction-info） | ✓ | ✓ |
| X-Linked-ETag（SHA256） | ✓ | ✓ |
| X-Linked-Size | ✓ | ✓ |
| 三级 fallback 兼容 | ✓ | ✓ |

**结论**: 两者完全兼容，改进后的代码同时支持两个端点

---

## 测试验证

### 改进前（P3 测试失败）
```
[1/4] TC-P3-01: info 命令
   → 执行 info 命令...
   → 验证输出...
❌ 测试失败！info 输出缺少必要字段
```

**原因**: 正则表达式太严格，未能从 reconstruction URL 提取 hash

### 改进后（预期通过）
```
📄 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
  类型: XET ✅
  大小: 100.6 MB (105,467,232 bytes)
  Xet Hash: e0aacd103e054264f5ede71ce63218c1...
  SHA256: 355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf
  Terms: 17
  ...
```

✓ xet hash: 提取成功  
✓ 大小: 正确显示  
✓ SHA256: 新增显示  

---

## 文档产出

1. **XET_HASH_EXTRACTION_METHODS.md** - HEAD 命令和 Hash 提取完整说明
2. **HUGGINGFACE_VS_HFMIRROR.md** - 两个端点的详细对比
3. **XET_HASH_EXTRACTION_IMPROVEMENT.md** - 改进方案设计文档

---

## 下一步

- ✓ 三级 fallback 正则已实现
- ✓ SHA256 提取已实现
- ✓ 文件大小修正已实现
- ✓ HuggingFace 兼容性已验证
- ✓ hf-mirror 兼容性已验证
- 🔄 P3 集成测试运行中
- ⏳ 等待测试结果确认
