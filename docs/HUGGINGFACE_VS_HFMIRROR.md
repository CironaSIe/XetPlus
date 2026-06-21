# HuggingFace vs hf-mirror XET 协议支持对比

**日期**: 2026-06-21  
**测试文件**: mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf

---

## 测试结果总结

**结论**: **hf-mirror.com 完全支持 XET 协议！**

两者功能相同，唯一区别是网络路径。

---

## 详细对比

### 1. HTTP 响应状态

| 特性 | HuggingFace.co | hf-mirror.com |
|------|----------------|---------------|
| Status Code | 302 Found | 302 Found |
| 重定向目标 | CAS Bridge | CAS Bridge |

### 2. XET 元数据支持

| 响应头 | HuggingFace.co | hf-mirror.com | 说明 |
|--------|----------------|---------------|------|
| Link (xet-auth) | ✓ | ✓ | 认证端点 URL |
| Link (xet-reconstruction-info) | ✓ | ✓ | 重建信息端点 |
| X-Linked-ETag | ✓ | ✓ | SHA256 校验和 |
| X-Linked-Size | ✓ | ✓ | 真实文件大小 |
| X-Repo-Commit | ✓ | ✓ | Git commit hash |

### 3. Link 头详细内容

#### HuggingFace.co
```http
Link: <https://huggingface.co/api/models/mykor/granite-embedding-97m-multilingual-r2-GGUF/xet-read-token/45ce642d3fab2033d167ec09641a159010f7d9d9>; rel="xet-auth",
      <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel="xet-reconstruction-info"
```

#### hf-mirror.com
```http
Link: <https://hf-mirror.com/api/models/mykor/granite-embedding-97m-multilingual-r2-GGUF/xet-read-token/45ce642d3fab2033d167ec09641a159010f7d9d9>; rel="xet-auth",
      <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel="xet-reconstruction-info"
```

**差异**: 
- xet-auth URL 的域名：`huggingface.co` vs `hf-mirror.com`
- xet-reconstruction-info URL 相同（都指向 CAS 服务器）

### 4. SHA256 和文件大小

| 字段 | HuggingFace.co | hf-mirror.com |
|------|----------------|---------------|
| SHA256 | 355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf | 355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf |
| 文件大小 | 105467232 bytes | 105467232 bytes |
| XET Hash | e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02 | e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02 |

**结论**: 完全相同

---

## 网络访问差异

### HuggingFace.co（通过代理）
```
用户 → 代理 → huggingface.co → 302 → CAS Bridge
```

### hf-mirror.com（直连）
```
用户 → hf-mirror.com → 302 → CAS Bridge
```

**优势**:
- hf-mirror.com 在中国大陆有 CDN 节点
- 直连速度通常快于通过代理访问 huggingface.co
- 两者最终都重定向到相同的 CAS Bridge

---

## XET+ CLI 支持情况

### --hf-endpoint 参数

**支持的值**:
- `huggingface.co`（默认）
- `hf-mirror.com`（国内用户推荐）

**示例**:
```bash
# 使用 huggingface.co（通过代理）
HTTPS_PROXY=http://127.0.0.1:12334 python -m xet.cli.main info \
    mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --token $TOKEN

# 使用 hf-mirror.com（直连）
python -m xet.cli.main info \
    mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --token $TOKEN \
    --hf-endpoint https://hf-mirror.com
```

### 代理配置

| 场景 | 推荐配置 | 说明 |
|------|---------|------|
| 国内无代理 | --hf-endpoint https://hf-mirror.com | 最快速度 |
| 国内有代理 | HTTPS_PROXY + huggingface.co | 可选 |
| 国外 | 默认（huggingface.co） | 无需配置 |

---

## detect_xet_file() 兼容性

**当前实现**: ✓ 完全兼容

```python
def detect_xet_file(repo_id, repo_type, filename, token, session):
    # 构造 URL（自动使用配置的 hf_endpoint）
    file_url = f"{hf_endpoint}/{repo_id}/resolve/main/{filename}"
    
    # HEAD 请求
    resp = session.head(file_url, headers=headers, allow_redirects=False, timeout=30)
    
    # 提取元数据（两个端点返回相同的头部）
    xet_hash = extract_xet_hash(resp.headers.get("Link"))
    sha256 = resp.headers.get("X-Linked-ETag", "").strip('"')
    size = int(resp.headers.get("X-Linked-Size", 0))
    
    return {"xet_hash": xet_hash, "sha256": sha256, "size": size}
```

---

## 建议

### 用户选择指南

1. **国内用户（无代理）**:
   ```bash
   xet config network.hf_endpoint https://hf-mirror.com
   ```

2. **国内用户（有稳定代理）**:
   ```bash
   # 保持默认 huggingface.co
   export HTTPS_PROXY=http://127.0.0.1:12334
   ```

3. **国外用户**:
   ```bash
   # 无需配置，默认即可
   ```

### 性能优化

- hf-mirror.com 走国内 CDN，首次连接延迟低
- HuggingFace.co 通过代理可能有额外延迟
- 两者都支持 HOST 优化
- 两者最终下载都走 CAS Bridge（性能相同）

---

## 总结

| 特性 | HuggingFace.co | hf-mirror.com |
|------|----------------|---------------|
| XET 协议支持 | ✓ 完整 | ✓ 完整 |
| Link 头 | ✓ | ✓ |
| SHA256 | ✓ | ✓ |
| 文件大小 | ✓ | ✓ |
| 国内直连 | ✗ 需要代理 | ✓ 快速 |
| XET+ 兼容 | ✓ | ✓ |

**推荐**: 
- 国内用户优先使用 hf-mirror.com（无需代理）
- 国外用户使用默认 huggingface.co
- 两者功能完全相同，仅网络路径不同
