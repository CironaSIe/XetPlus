# Shard API 规范确认与全局去重规则修正

## 2026-06-29: 官方 API 完整规范确认

### XET CAS 端点总表

| 端点 | 作用 | 认证 | 响应 |
|------|------|------|------|
| `GET /api/{repo_type}s/{repo}/xet-read-token/main` | 获取 CAS JWT（15 min 过期） | HF Token `Bearer` | `{casUrl, accessToken}` |
| `GET {casUrl}/v1/chunks/default-merkledb/{api_path}` | 全局去重分片查询 | CAS JWT `Bearer` | 二进制 MDB shard（`application/octet-stream`） |
| `POST /v1/xorbs/default/{hash}` | 上传 xorb | CAS JWT | 成功/失败 |
| `POST /v1/shards` | 上传元数据 shard | CAS JWT | 0=已存在, 1=新同步 |

### 全局去重规则修正（关键发现）

**错误：本地代码** 取 hash 的 `first 8 bytes` 转 LE u64 做 mod 1024
```python
# 当前（错）
first_u64 = struct.unpack('<Q', hb[:8])[0]
if first_u64 % 1024 == 0:
```

**正确：官方规范** 取 hash 的 `last 8 bytes` 转 LE u64 做 mod 1024
```python
# 正确
last_u64 = struct.unpack('<Q', hb[-8:])[0]
if last_u64 % 1024 == 0:
```

来源：https://huggingface.co/docs/xet/en/deduplication
> "Chunks are eligible if: the last 8 bytes of the hash interpreted as a little-endian 64 bit integer % 1024 == 0."

**额外规则：文件第一个 chunk 无条件命中**，不经过 mod 检查。

### MDB Shard 二进制格式确认（与 Rust xet-core 完全对齐）

`xet/storage/mdb_shard.py` 解析器已验证与官方规范完全一致：

- **Header 48B**: 32B magic tag（常量 `HFRepoMetaData...`）+ u64 version(=2) + u64 footer_offset
- **Footer 200B**: u64 version(=1) + 7 个 offset/length 字段 + HMAC key(32B) + timestamp + expiry + 保留 48B + 6 个 u64 统计值
- **File Info Section**: 以 bookend(`0xFF*32`) 结尾，每个 FileDataSequenceHeader 含 file_hash(32B) + flags(u32) + num_entries(u32)，后续 entries 为 xorb_hash + flag + unpacked_bytes + chunk_range
- **CAS Info Section**: 以 bookend 结尾，每个 CASChunkSequenceHeader 含 xorb_hash(32B) + flags(u32) + num_entries(u32) + num_bytes(u32) + num_bytes_disk(u32)，后续 entries 为 chunk_hash(32B) + byte_start(u32) + unpacked_size(u32) + flags(u32) + unused(u32)

支持 HMAC keyed hash 自适应比对：
- 若 HMAC key 为全零 → 直接比 raw chunk_hash
- 若 HMAC key 非零 → 需对计算出的 data_hash 做 `blake3.keyed_hash(hmac_key, data_hash_bytes)` 后再比对

### 哈希 → API path 编码规则确认

```python
# 32 bytes hash → 4 组 8 bytes
# 每组 8 bytes 视为 LE u64，hex 编码
for j in range(4):
    group = raw[j*8:(j+1)*8]        # 取第 j 组 8 bytes
    reversed_group = group[::-1]      # byte 反转（与 API 格式一致）
    val = int.from_bytes(reversed_group, 'little')
    parts.append(f"{val:016x}")
```

## 2026-06-29: Rust xet-core 源码对照确认

### Rust 源码关键片段

**API path 编码**（`xet_core_structures/src/merklehash/data_hash.rs:156-171`）：
```rust
pub fn hex(&self) -> String {
    format!(
        "{:016x}{:016x}{:016x}{:016x}",
        self.0[0].to_le(), self.0[1].to_le(),
        self.0[2].to_le(), self.0[3].to_le()
    )
}
```
→ Python `struct.unpack('<4Q', digest)` + `f'{u:016x}'` 完全等价 ✅

**URL 构建**（`xet_client/src/cas_types/key.rs:17-21`）：
```rust
impl Display for Key {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}/{:x}", self.prefix, self.hash)
    }
}
```
→ URL path `{cas_url}/v1/chunks/{prefix}/{hex_hash}`

**服务端路由**（`xet_client/.../local_server/server.rs:172-184`）：
```rust
.route("/chunks/{prefix}/{hash}", get(handlers::get_dedup_info_by_chunk))
```

**Handler**（`handlers.rs:490-504`）返回逻辑：
```rust
match query_for_global_dedup_shard(&key.prefix, &key.hash).await {
    Ok(Some(data)) => (StatusCode::OK, data).into_response(),
    Ok(None) => (StatusCode::NOT_FOUND, "Shard not found").into_response(),
    Err(e) => error_to_response(e),
}
```

**重要发现：测试代码使用 `"default"` 而非 `"default-merkledb"`**（约 15 处测试调用，如 `client_unit_testing.rs:659` 等）。

### Shard 内 chunk hash 存储格式

来自官方文档（https://huggingface.co/docs/xet/en/shard）：
> Chunk hashes in the CAS Info section are stored as **HMAC(original_chunk_hash, chunk_hash_hmac_key)** — the key is in the shard footer, comes from dedup API responses.

即：
- URL path 中的 hash = raw data_hash（明文）
- Shard 响应内的 chunk_hash = HMAC(key, data_hash)（keyed）

### 已知限制

1. `/v1/chunks/default-merkledb/{hash}` 端点**是上传去重专用接口**，不是下载校验接口
   - **200 OK** = chunk 在全局索引中，返回 shard（含 HMAC-keyed chunk hash 列表）
   - **404 NOT_FOUND** = chunk 不在索引中（正常，表示需要上传新数据）
2. 全局去重索引只在 **XET 上传流程**（POST /v1/shards）中填充
   - 通过镜像/转换引入的 repo（如从 hf-mirror 同步）可能没有走上传流程→ chunk 不在索引中
   - 这解释了为何我们的 repo 全部返回 404
3. 即使查到 shard，里面的 chunk hash 是 HMAC-keyed 的，需要 footer 中的 key 做逆运算
4. 只有 ~1/1024 chunk 有资格被索引，无法覆盖全量

### 核心结论：下载场景的正确校验方案

对下载/只读场景，无法通过 `/v1/chunks/` 获取全量 per-chunk expected hash。

## 2026-06-29: 实际 shard API 验证结果

### 成功获取 shard 的条件

用 TheBloke/Mixtral-8x7B-Instruct-v0.1-GGUF 的 file_hash + reconstruction API + xorb 下载，提取第一个 chunk 的 data_hash，查询 shard API：

```
GET /v1/chunks/{hash}  →  HTTP 200  (11.7MB shard)
```

**使用 prefix `"default"` 而非 `"default-merkledb"`**（与 Rust 测试代码一致）。

### Shard 内容分析

| 属性 | 值 |
|------|-----|
| 文件数 | 0（全局去重查询 shard 无 File Info Section） |
| Xorb 数 | 234 |
| 总 chunk 数 | 242,867 |
| HMAC key | **存在（非零）**，32 字节 |

### HMAC 验证流程

```
computed_raw_hash = compute_data_hash_bytes(chunk_data)  # 32B
keyed_hash = blake3.keyed_hash(hmac_key, computed_raw_hash)  # 32B
match = (keyed_hash == shard_entry.chunk_hash)
```

## 2026-06-29: Q4_K_M 实测 — 全局索引存在但 shard 不精确匹配

### 实测结果

用 Q4_K_M.gguf 的第一个 chunk（xorb `f52ace46...`, chunk #0）查询：

| 属性 | 值 |
|------|-----|
| prefix | `default`（非 `default-merkledb`）|
| HTTP 状态 | **200 OK** |
| Shard 大小 | 146,696 bytes |
| 含 xorb 数 | 4 |
| 总 chunk 数 | 3,045 |
| HMAC key | 存在（16 字节） |

**关键发现：query chunk 的 HMAC 后的 hash 不在 shard 的 3,045 个 chunk 中。**

### 根本原因

Shard API 是**上传去重优化接口**，不是精确查询接口：
1. 客户端上传时用 eligible chunk hash 查询 → 服务器 200 = "存在"
2. 返回的 shard 包含**locality 相关**的 xorb（邻近 chunk 所在的 xorb）
3. 这为了帮助客户端批量引用已有 xorb，减少查询次数
4. **不保证**返回的 shard 包含查询 chunk 自身所属的 xorb

### 对 D1 校验的最终结论

| 尝试过的方案 | 结果 | 原因 |
|-------------|------|------|
| `/v1/chunks/` 直接查询 | HTTP 200 但 shard 不含目标 xorb | locality 优化，非精确匹配 |
| 镜像导入 repo chunk | 404 | 未走 XET 上传流程 |
| 原生 XET repo chunk | 200 但 shard xorbs 不匹配 | locality 优化，chunk 本身也不在 shard 中 |

**D1 聚合校验（906/906 ✅）是用下载数据进行 chunk 级完整性验证的唯一可靠方案。**

验证链路：
```
presigned URL → xorb 二进制 → deserialize → 逐 chunk 解压
    → compute_data_hash → 收集 (hash, size) 对
    → Merkle 聚合 (aggregated_node_hash) → xorb_hash
    → 对比 reconstruction API 返回的 xorb_hash
```

不需要 shard API，不需要全局去重索引，适用于任何 XET 仓库的下载验证。
```
xorb 二进制 → 拆 chunk → 解压 → compute_data_hash
    → 收集 (data_hash, size) 对
    → Merkle 聚合 (aggregated_node_hash)
    → 得到 xorb_hash
    → 对比 reconstruction API 返回的 xorb_hash
```

这在**不需要 shard API** 的前提下完成了 100% chunk 级完整性验证。
