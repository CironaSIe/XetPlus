# CAS 实现与测试信息对齐检查

## ✅ 已对齐的实现

### 1. Auth URL 格式 ✅
**测试信息要求**：
```
/api/{repo_type}s/{repo_id}/xet-read-token/{commit_hash}
```

**实际实现** (`auth.py:168`):
```python
url = f"https://huggingface.co/api/{repo_type_plural}/{repo_id}/xet-read-token/{commit_hash}"
```
- ✅ 格式完全匹配
- ✅ 测试目标 1 的 auth URL 验证通过：
  - `https://huggingface.co/api/models/mykor/granite-embedding-97m-multilingual-r2-GGUF/xet-read-token/45ce642d3fab2033d167ec09641a159010f7d9d9`

### 2. CAS Endpoint 处理 ✅
**测试信息**：
- CAS endpoint: `cas-server.xethub.hf.co`
- 需要完整 URL: `https://cas-server.xethub.hf.co`

**实际实现**：
- `auth.py:194`: `endpoint = data.get('endpoint', 'https://cas-server.xethub.hf.co')` ✅
- `cas_client.py:73`: `self.endpoint = endpoint.rstrip('/')` ✅
- API URL 构建 (`cas_client.py:136`): `f"{self.endpoint}/v2/reconstructions/{file_hash}"` ✅

### 3. V2/V1 API Fallback ✅
**测试信息**：
- V2 API: `/v2/reconstructions/{file_hash}`
- V1 API: `/v1/reconstructions/{file_hash}`

**实际实现** (`cas_client.py:134-184`):
- ✅ 尝试 V2，404/501 时 fallback V1
- ✅ 缓存 V2 可用性状态 (`_v2_available`)

### 4. 401 处理（Token 刷新）✅
**测试信息要求**：
- 401 → 强制刷新 token + 重新获取 reconstruction

**实际实现**：
- `cas_client.py:96-109`: `_refresh_token()` ✅
- `cas_client.py:551-577`: `_force_refresh_token()` 带重试 ✅
- `get_reconstruction()` 中的 401 处理 (第 145-154 行) ✅
- `get_xorb_data_with_retry()` 中的 401 处理 (第 392-409 行) ✅

### 5. 403 处理（URL 过期）✅
**测试信息**：
- 403 风暴防护需要全局协调

**实际实现** (`cas_client.py:412-450`):
- ✅ URLRefreshCoordinator 协调刷新
- ✅ 专用退避策略：`base_403 = 5.0`, `delay = base_403 * (2.5 ** attempt)`
- ✅ 获取新 reconstruction + 查找新 URL

### 6. Xorb 下载不发送 Authorization ✅
**关键安全要求**：
- Xorb 下载必须**不发送 Authorization**（避免 CloudFront 403）

**实际实现** (`cas_client.py:206-222`):
```python
headers = {
    "Range": url_range.to_header(),
    "X-Xet-Session-Id": self.session_id,
    "Authorization": None,  # 抑制 session 级别的默认头
}
```
- ✅ 显式设置 `Authorization: None`
- ✅ 添加 `X-Xet-Session-Id` 用于 CloudFront 会话跟踪
- ✅ 注释明确说明原因

### 7. 低速检测 + 断点续传 ✅
**实际实现**：
- `get_xorb_data_streaming()` (第 224-318 行):
  - 默认参数：50 KB/s, 10s 检查间隔, 30s 容忍时间 ✅
  - 速度恢复后重置计数 ✅
- `get_xorb_data_with_retry()` 中的断点续传 (第 462-479 行):
  - 调整 Range 从 `url_range.start + e.received` 继续 ✅

### 8. Session ID 跟踪 ✅
**实际实现** (`cas_client.py:84`):
```python
self.session_id = uuid.uuid4().hex[:16]
```
- ✅ 16 字符 hex 字符串
- ✅ 在 xorb 下载请求中添加 `X-Xet-Session-Id` header

---

## 🔍 需要注意的测试场景

### 测试目标 1：可用 ✅
- **仓库**: `mykor/granite-embedding-97m-multilingual-r2-GGUF`
- **文件**: `granite-embedding-97M-multilingual-r2-Q4_K_M.gguf`
- **大小**: 100.58 MB
- **Reconstruction API**: ✅ 返回 200（需 HF_TOKEN）
- **Terms 数**: 17
- **唯一 Xorb 数**: 10

### 测试目标 2：不可用 ❌
- **仓库**: `xet-team/xet-spec-reference-files`
- **Reconstruction API**: ❌ 返回 404
- **原因**: 仅上传了 shard/xorb 参考文件，未上传 reconstruction 数据至 CAS
- **用途**: 仅用于本地文件格式解析验证

---

## 🎯 实现完整性总结

| 特性 | 测试信息要求 | 实际实现 | 状态 |
|------|-------------|---------|------|
| Auth URL 格式 | `/api/{repo_type}s/{repo_id}/xet-read-token/{commit_hash}` | ✅ 完全匹配 | ✅ |
| CAS Endpoint | `https://cas-server.xethub.hf.co` | ✅ 正确处理 | ✅ |
| V2/V1 Fallback | 404/501 → V1 | ✅ 已实现 | ✅ |
| 401 处理 | 刷新 token + 重新获取 recon | ✅ 已实现 | ✅ |
| 403 处理 | 协调刷新 + 专用退避 | ✅ 已实现 | ✅ |
| Xorb 无 Auth | 不发送 Authorization | ✅ 显式 None | ✅ |
| 低速检测 | 50 KB/s, 30s 容忍 | ✅ 已实现 | ✅ |
| 断点续传 | 调整 Range 继续 | ✅ 已实现 | ✅ |
| Session ID | CloudFront 跟踪 | ✅ 已实现 | ✅ |

---

## ✅ 结论

**CAS 实现与测试信息完全对齐！**

所有关键特性均已正确实现：
1. ✅ Auth URL 格式正确
2. ✅ Xorb 下载不发送 Authorization（关键安全要求）
3. ✅ 401/403 高级处理
4. ✅ 低速检测 + 断点续传
5. ✅ URLRefreshCoordinator 和 ACC 集成
6. ✅ Session ID 跟踪

**可以直接使用测试目标 1 进行集成测试验证。**
