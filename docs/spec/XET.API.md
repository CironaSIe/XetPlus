# XET API 完整参考

> HuggingFace Hub API + CAS API 所有 XET 相关端点
> 整理日期: 2026-06-29
> 参考: Hub OpenAPI, IETF draft-denis-xet-04, huggingface.js XetBlob.ts, huggingface_hub

本文档涵盖两类 API：
1. **Hub API** — 通过 `https://huggingface.co` 提供，用于获取 token、文件元数据、文件操作
2. **CAS API** — 通过 `{casUrl}`（从 token 响应获取）提供，用于实际存储操作

---

## 1. Hub API: Token 端点

获取 XET CAS 的短期访问令牌。所有端点均使用 `Authorization: Bearer <hf_token>` 认证。

### 1.1 Read Token

```
GET /api/{repo_type}s/{namespace}/{repo}/xet-read-token/{revision}
GET /api/buckets/{namespace}/{repo}/xet-read-token
```

| 参数 | 说明 |
|------|------|
| `repo_type` | `model` / `dataset` / `space` |
| `namespace` | 用户/组织名 |
| `repo` | 仓库名 |
| `revision` | 分支/tag/commit hash（默认 `main`） |

响应头:
```
X-Xet-Cas-Url: https://cas-server.xethub.hf.co
X-Xet-Access-Token: xet_xxxx...
X-Xet-Token-Expiration: 1848535668
```

响应体:
```json
{
  "accessToken": "xet_xxxx...",
  "exp": 1848535668,
  "casUrl": "https://cas-server.xethub.hf.co"
}
```

### 1.2 Write Token

```
GET /api/{repo_type}s/{namespace}/{repo}/xet-write-token/{revision}
GET /api/buckets/{namespace}/{repo}/xet-write-token
```

参数、响应格式同上，但作用域为 `write`（可读写）。

### 1.3 Token 刷新行为

`huggingface.js`（XetBlob.ts）中的 JWT 缓存逻辑:
- 缓存大小上限 1000 个 token
- 过期前 60 秒提前刷新（`JWT_SAFETY_PERIOD`）
- 同一仓库的并发请求合并为一次 token 获取

### 1.4 端点矩阵

| repo_type | read token | write token | 带 revision |
|-----------|-----------|------------|-------------|
| `models`  | ✅ | ✅ | ✅ |
| `datasets` | ✅ | ✅ | ✅ |
| `spaces`  | ✅ | ✅ | ✅ |
| `buckets` | ✅ | ✅ | ❌ (无 revision) |

---

## 2. Hub API: 文件元数据端点

### 2.1 Resolve URL（获取 X-Xet-Hash）

```
GET /{namespace}/{repo}/resolve/{revision}/{path}
GET /spaces/{namespace}/{repo}/resolve/{revision}/{path}
GET /datasets/{namespace}/{repo}/resolve/{revision}/{path}
GET /buckets/{namespace}/{repo}/resolve/{path}
```

响应为 302 重定向（**不可 follow**，follow 后走旧 LFS 路径），关键响应头:

| Header | 说明 |
|--------|------|
| `X-Xet-Hash` | XET file ID (64 hex chars) |
| `X-Linked-ETag` | SHA256 校验和（带引号） |
| `X-Linked-Size` | 文件真实大小（字节） |
| `X-Repo-Commit` | Git commit hash |
| `Link` | 包含 `xet-auth` 和 `xet-reconstruction-info` URL |

`Link` 头格式:
```
<https://huggingface.co/api/models/{repo}/xet-read-token/{rev}>; rel="xet-auth",
<https://cas-server.xethub.hf.co/v1/reconstructions/{file_id}>; rel="xet-reconstruction-info"
```

`huggingface_hub` 内部将头部解析为 `XetFileData(file_hash, refresh_route)`:
```python
# huggingface_hub 内部结构
class XetFileData:
    file_hash: str       # XET file ID
    refresh_route: str   # token 刷新 URL（即 Link 中的 xet-auth URL）
```

### 2.2 缓存版 Resolve

```
GET /api/resolve-cache/{repo_type}s/{namespace}/{repo}/{revision}/{path}
```

与 Resolve 相同但经过 CDN 缓存。返回 302 和相同头部集。

### 2.3 列出大文件 (Xet/LFS)

```
GET /api/{repo_type}s/{namespace}/{repo}/lfs-files
```

| 参数 | 说明 |
|------|------|
| `cursor` | 分页游标 |
| `limit` | 每页数量 |
| `xet` | 可选筛选（值未知，可尝试 `true` 或 `1`） |

响应: 返回 `LFSFileInfo` 数组，每个文件包含:
```json
{
  "oid": "sha256-hex",
  "size": 123456789,
  "pointerSize": 130
}
```

`huggingface_hub` 中对应 `HfApi.list_lfs_files()`。

### 2.4 获取目录/树

```
GET /api/{repo_type}s/{namespace}/{repo}/tree/{revision}/{path}
```

返回目录内容列表。对 XET 文件，响应包含 `xet_hash` 字段:

```json
{
  "path": "model.safetensors",
  "type": "file",
  "size": 123456789,
  "oid": "git-blob-sha...",
  "lfs": {
    "size": 123456789,
    "sha256": "lfs-oid...",
    "pointerSize": 130
  },
  "xet_hash": "e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02"
}
```

`huggingface_hub` 中映射为 `RepoFile` 的 `.xet_hash` 属性。非 XET 文件无此字段。

### 2.5 获取路径信息

```
POST /api/{repo_type}s/{namespace}/{repo}/paths-info/{revision}
```

请求体:
```json
{ "paths": ["model.safetensors", "tokenizer.json"] }
```

响应体结构与 tree endpoint 相同（含 `xet_hash`）。`expand=true` 会附加 `lastCommit` 和安全扫描信息。

### 2.6 树大小

```
GET /api/{repo_type}s/{namespace}/{repo}/treesize/{revision}/{path}
```

若文件通过 Xet/LFS 存储，则使用 LFS 文件大小计算。

---

## 3. Hub API: 文件操作端点

### 3.1 复制 XET 文件（通过 xet hash）

```
POST /api/{repo_type}s/{namespace}/{repo}/lfs-files/duplicate
```

**完全服务端操作，零数据传输。**

请求体:
```json
{
  "target": { "type": "model", "name": "target-repo" },
  "files": ["model.safetensors"]
}
```

`huggingface_hub` 中对应:
- `HfApi.copy_files()` — 支持跨仓库复制
- `HfApi.batch_bucket_files(copy=[...])` — 存储桶复制

### 3.2 删除 XET/LFS 文件

单文件删除:
```
DELETE /api/{repo_type}s/{namespace}/{repo}/lfs-files/{sha}
```

| 参数 | 说明 |
|------|------|
| `sha` | LFS OID (SHA256) |
| `rewriteHistory` | 可选查询参数 |

批量删除:
```
POST /api/{repo_type}s/{namespace}/{repo}/lfs-files/batch
```

请求体:
```json
{
  "deletions": {
    "sha": ["sha1", "sha2"],
    "rewriteHistory": false
  }
}
```

### 3.3 存储桶批量操作

```
POST /api/buckets/{namespace}/{repo}/batch
```

**NDJSON 格式**（每行一个 JSON 操作），非事务性（部分成功可能）。

```json
{"op": "add", "path": "model.bin", "xetHash": "e0aacd10...", "size": 123456789}
{"op": "copy", "fromPath": "src.bin", "toPath": "dst.bin", "xetHash": "e0aacd10..."}
{"op": "delete", "path": "old.bin"}
```

`huggingface_hub` 中对应 `HfApi.batch_bucket_files()`:
```python
api.batch_bucket_files(
    "my-bucket",
    add=[("model.bin", xet_hash, size)],
    copy=[("source-repo", "src.bin", "dst.bin", xet_hash)],
    delete=["old.bin"],
)
```

---

## 4. CAS API

所有端点相对于 `{casUrl}`（从 token 响应获取），使用 `Authorization: Bearer <xet_token>` 认证。

### 4.1 哈希字符串编码

32 bytes → 64 hex 字符:

```python
# 4 组 8 bytes，每组作为 LE u64 hex 输出
u64s = struct.unpack('<4Q', digest_32)
hex_str = ''.join(f'{u:016x}' for u in u64s)
```

### 4.2 Get File Reconstruction

```
GET /v1/reconstructions/{file_id}
```

**IETF 草案路径**（与 HF 略有不同）: `/api/v1/reconstructions/{file_hash}`

| 参数 | 说明 |
|------|------|
| `file_id` | file hash 经编码的 64 hex 字符 |
| `Range` | 可选，`bytes={start}-{end}` (end 包含) |

**Scope**: `read`

**成功响应 200**:

```json
{
  "offset_into_first_range": 0,
  "terms": [
    {
      "hash": "<xorb_hash_64hex>",
      "unpacked_length": 263873,
      "range": { "start": 0, "end": 4 }
    }
  ],
  "fetch_info": {
    "<xorb_hash_64hex>": [
      {
        "range": { "start": 0, "end": 4 },
        "url": "https://transfer.xethub.hf.co/xorb/default/<hash>?presigned",
        "url_range": { "start": 0, "end": 131071 }
      }
    ]
  }
}
```

`url_range` 使用 HTTP Range 语义（**end 包含**），而其他 range 字段为 `[start, end)` 惯例。

**huggingface.js XetBlob.ts 实现确认**: 此接口完全匹配。XetBlob 调用 `#loadReconstructionInfo()` 获取此 JSON，然后流式处理。

**V2 格式**（xet-core PR #703, HuggingFace 扩展，IETF 草案尚未收录）:

客户端优先尝试:
```
GET /v2/reconstructions/{file_id}
```

V2 用 `xorbs` 字典替代 `fetch_info`，响应更小更快（69GB 文件: V1 60MB → V2 23MB）。

**错误**:
| 状态 | 说明 | 重试 |
|------|------|------|
| 400 | file_id 格式错误 | 否 |
| 401 | token 无效/过期 | 刷新后 |
| 404 | 文件不存在 | 否 |
| 416 | Range 不满足 | 否 |

### 4.3 Query Chunk Deduplication

```
GET /v1/chunks/default-merkledb/{hash}
```

**IETF 草案路径**: `/api/v1/chunks/{namespace}/{chunk_hash}`，其中 namespace = `default-merkledb`

| 参数 | 说明 |
|------|------|
| `prefix` | 必须为 `default-merkledb` |
| `hash` | chunk hash 经编码的 64 hex 字符 |

**Scope**: `read`

**成功响应 200**: `application/octet-stream` — Shard 二进制格式。

Dedup 响应 shard 的特点:
- File Info Section 为空（直接以 bookend 结尾）
- CAS Info Section 包含若干 xorb 的 chunk 列表
- chunk hash 经过 HMAC 加密（用 footer 中的 key）
- 参考文件: `xet-team/xet-spec-reference-files/*.shard.dedupe`

**错误**:
| 状态 | 说明 | 重试 |
|------|------|------|
| 400 | hash 格式错误 | 否 |
| 401 | token 无效 | 刷新后 |
| 404 | chunk 不存在 | 否 |

### 4.4 Upload Xorb

```
POST /v1/xorbs/default/{hash}
```

**IETF 草案路径**: `/api/v1/xorbs/{namespace}/{xorb_hash}`，其中 namespace = `default`

| 参数 | 说明 |
|------|------|
| `prefix` | 必须为 `default` |
| `hash` | xorb hash 经编码的 64 hex 字符 |

**Scope**: `write`

**请求体**: `application/octet-stream` — Xorb 二进制格式。

**约束**:
- 序列化大小不得超过 64 MiB
- 每个 xorb 最多 8192 个 chunk

**成功响应 200**:
```json
{
  "was_inserted": true
}
```
`was_inserted: false` 表示已存在（非错误）。

**错误**:
| 状态 | 说明 | 重试 |
|------|------|------|
| 400 | hash/body 不匹配、序列化错误 | 否 |
| 401 | token 无效 | 刷新后 |
| 403 | 权限不足（如 read token） | 否 |

### 4.5 Upload Shard

```
POST /v1/shards
```

**Scope**: `write`

**请求体**: `application/octet-stream` — Shard 二进制格式。

上传 shard 的关键约束:
- **必须省略 Footer**（`footer_size = 0`）
- **必须包含 FileVerificationEntry**（上传用 shard 需要 verification hashes）
- 必须包含 `FileMetadataExt`（SHA256，Git 仓库必需）
- 所有引用的 xorb 必须先上传，否则服务端返回 400
- shard 序列化大小不超过 64 MiB，超限需拆分
- 参考文件: `xet-team/xet-spec-reference-files/*.shard.verification-no-footer`

**成功响应 200**:
```json
{
  "result": 0
}
```
- `0`: Shard 已存在（幂等）
- `1`: SyncPerformed — 已注册

任何 200 状态码都表示上传成功。

**错误**:
| 状态 | 说明 | 重试 |
|------|------|------|
| 400 | 序列化错误、verification 失败、引用的 xorb 不存在、shard 过大 | 否 |
| 401 | token 无效 | 刷新后 |
| 403 | 权限不足 | 否 |

---

## 5. 错误处理策略

### 不可重试

| 状态码 | 含义 |
|--------|------|
| 400 | 请求参数无效 |
| 401 | Token 无效/过期（刷新后可重试） |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 416 | Range 越界 |

### 可重试（退避）

| 状态码 | 含义 |
|--------|------|
| 429 | 限流（所有 API 都可能限流） |
| 500 | 服务端内部错误 |
| 503 | 服务暂不可用 |
| 504 | 网关超时 |
| - | 连接错误 |

---

## 6. 缓存策略

### Xorb 内容（不可变）

```
Cache-Control: public, immutable, max-age=<url_ttl_seconds>
ETag: "<xorb_hash>"
```

### Reconstruction 响应（易变，含 presigned URL）

```
Cache-Control: private, no-store
```

### 全局去重响应（用户特定）

```
Cache-Control: private, max-age=3600
Vary: Authorization
```

---

## 7. 端点分类汇总

| 类别 | Hub API | CAS API | 数量 |
|------|---------|---------|------|
| Token 获取 | 8 端点 | - | 8 |
| 文件解析 | 7 端点 | - | 7 |
| 文件列表/信息 | 6 端点 | - | 6 |
| 文件操作 | 6 端点 | - | 6 |
| 文件重构 | - | 1 端点 | 1 |
| 去重查询 | - | 1 端点 | 1 |
| Xorb 上传 | - | 1 端点 | 1 |
| Shard 上传 | - | 1 端点 | 1 |
| **总计** | **27 端点** | **4 端点** | **31** |

---

## 8. huggingface_hub 内部结构映射

| huggingface_hub 类型 | 对应 API/字段 |
|---------------------|-------------|
| `XetFileData(file_hash, refresh_route)` | X-Xet-Hash 头 + Link 中的 xet-auth URL |
| `HfFileMetadata.xet_file_data` | get_hf_file_metadata() 返回 |
| `XetReadToken(accessToken, casUrl, exp)` | Token 响应 JSON |
| `RepoFile.xet_hash` | Tree/paths-info 响应中的 `xet_hash` 字段 |
| `BlobLfsInfo(sha256, size, pointerSize)` | LFS 文件信息 |
| `LFSFileInfo(oid, size, pointerSize)` | lfs-files 列表响应 |

---

## 9. 认证数据流（含 JWT 缓存）

```
Client                          HuggingFace Hub                   CAS Server
  │                                  │                                │
  │ 1. GET xet-read-token/{rev}      │                                │
  │ ──────────────────────────────►  │                                │
  │ 2. {casUrl, accessToken, exp}    │                                │
  │ ◄──────────────────────────────  │                                │
  │ (缓存到 jwts map, 60s 安全缓冲)   │                                │
  │                                  │                                │
  │ 3. GET /v1/reconstructions/{file_id}                              │
  │    Authorization: Bearer <accessToken>                            │
  │ ──────────────────────────────────────────────────────────────►  │
  │ 4. QueryReconstructionResponse                                    │
  │ ◄──────────────────────────────────────────────────────────────  │
  │                                  │                                │
  │ 5. GET {presigned_url} with Range                                │
  │ ──────────────────────────────────────────────────────────────►  │
  │ 6. Xorb binary data (206 Partial Content)                        │
  │ ◄──────────────────────────────────────────────────────────────  │
  │                                  │                                │
  │ (Token 过期前 60s 自动刷新)        │                                │
  │ 7. GET xet-read-token/{rev}      │                                │
  │ ──────────────────────────────►  │                                │
  │ 8. New token                     │                                │
  │ ◄──────────────────────────────  │                                │
  │                                  │                                │
  │ (403 on presigned URL → token 或签名已过期)                        │
  │ 9. 重新拉取 reconstruction → 新 presigned URL                     │
  │ ──────────────────────────────────────────────────────────────►  │
```

---

## 10. 实践确认状态

标注各端点和响应结构在本项目中的实测状态。

| 端点/结构 | 实测状态 | 说明 |
|-----------|---------|------|
| Token 获取 (read) | ✅ 已实测 | mykor/granite-embedding-97m-multilingual-r2-GGUF |
| Token 获取 (write) | ❌ 未测 | |
| Resolve URL 302 + X-Xet-Hash | ✅ 已实测 | 从 info 命令流程验证 |
| Link 头解析 (xet-auth, recon) | ✅ 已实测 | 代码中实现 |
| Reconstruction V1 响应 | ✅ 已实测 | Q4_K_M.gguf, 完整解析 |
| Reconstruction V2 响应 (xorbs) | ⚠️ 有转换代码 | 从未真正见过 V2 响应 |
| Shard 反序列化（含 Footer） | ✅ 已实测 | dedup API 返回的 shard |
| Shard 上传（无 Footer） | ❌ 未测 | 未上传过 shard |
| Xorb 下载/反序列化 | ✅ 已实测 | f52ace46... 和 edc32dd7... |
| Xorb 上传 | ❌ 未测 | |
| Chunk Dedup 查询 | ✅ 已实测 | Q4_K_M 第一个 chunk 200，其余 404 |
| HMAC 验证 | ✅ 已实测 | shard entries vs locally computed |
| DataHash 计算 | ✅ 已实测 | vs Rust xet-core 对齐 |
| Merkle 聚合 (xorb_hash) | ✅ 已实测 | vs Rust xet-core 对齐 |
| File hash 计算 | ✅ 已实测 | vs Rust xet-core 对齐 |
| Tree/Paths-info xet_hash 字段 | ❌ 未测 | 尚未调用过 tree/paths-info API |
| LFS 文件列表 xet 筛选 | ❌ 未测 | |
| 文件复制 (duplicate) | ❌ 未测 | |
| 存储桶批量操作 | ❌ 未测 | |
| Xorb footer (CasObjectInfo) | ✅ 已验证 | xorb_deserializer.py 有处理逻辑 |

### 符号说明

| 符号 | 含义 |
|------|------|
| ✅ 已实测 | 在真实 API 上验证过，或有完整测试覆盖 |
| ⚠️ 有转换代码 | 有实现代码但未经真实 API 验证 |
| ❌ 未测 | 未实现也未测试 |

---

## 参考

- [XET 协议规范](XET.SPEC.md) — 完整协议细节
- Hub OpenAPI: `https://huggingface.co/.well-known/openapi.json`
- XET Protocol Docs: `https://huggingface.co/docs/xet/en/api`
- IETF draft-denis-xet-04: `https://datatracker.ietf.org/doc/html/draft-denis-xet-04`
- huggingface.js XetBlob.ts: `https://github.com/huggingface/huggingface.js/blob/main/packages/hub/src/utils/XetBlob.ts`
- xet-core PR #703: V2 reconstruction support
- Xet 参考文件: `https://huggingface.co/datasets/xet-team/xet-spec-reference-files`
