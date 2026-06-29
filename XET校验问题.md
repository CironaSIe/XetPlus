# XET 校验问题记录

## 2026-06-24: Term Verification Hash 获取方式确认

### 问题

HuggingFace XET 协议中，每个 term 的验证 hash（`FileVerificationEntry.range_hash`）如何被下载客户端获取？

### 调查结论

**下载客户端无法通过重建 API 获取 term verification hash。**

### 详细说明

#### 上传时（客户端生成，存入 shard）

- 上传时，客户端为每个 term 计算 verification hash：
  ```
  buffer = concat(chunk_hashes[range.start : range.end])
  range_hash = blake3(buffer, key=VERIFICATION_KEY)
  ```
- 存入 shard 的 `FileVerificationEntry`（位于 `MDB_FILE_FLAG_WITH_VERIFICATION` 段）
- 验证目的是向服务器证明上传者确实持有数据

#### 下载时（服务器不返回）

- `GET /v1/reconstructions/{file_id}` 返回 `QueryReconstructionResponse`：
  - `terms[]` — 每个 term 含 `hash`(xorb_hash)、`range`、`unpacked_length`
  - `fetch_info{}` — xorb_hash → url 映射
  - **不包含** `FileVerificationEntry.range_hash`
- 下载协议只依赖：
  - MerkleHash（文件级 xet hash）作为不可变身份锚点
  - SHA256（可选，用于 git LFS 兼容）
  - 下载数据后解压 → 拼接 → 计算文件级 xet hash 或 SHA256

#### 对 xetplus 的影响

1. **Term 附带的 hash（xorb_hash）** 仍然有用——用于查找 `fetch_info` 和下载 xorb
2. **`FileVerificationEntry.range_hash`（协议 term 校验 hash）** 下载时不可得
3. **xetplus 的 `TermHashRecord.sha256`（本地计算）** 是正确的方案：
   - 组装时计算并持久化到 checkpoint
   - 续传时用于 per-term 完整性验证
   - 与 HuggingFace 协议无关，是 xetplus 自主的校验机制

### 参考文档

- https://huggingface.co/docs/xet/hashing（Term Verification Hashes 章节）
- https://huggingface.co/docs/xet/download-protocol（下载协议，无 verification 返回）
- https://huggingface.co/docs/xet/shard（Shard 格式，verification 仅上传时使用）
- https://huggingface.co/docs/xet/api（CAS API，reconstruction 接口定义）
- https://huggingface.co/docs/xet/file-reconstruction（Term 定义）
- https://huggingface.co/docs/xet/en/download-protocol（英文版下载协议）

## 2026-06-27: XET Hash Chain 校验总览

### 背景

整理 XET 协议中所有校验相关值的计算方式、上传/下载产生逻辑、以及下载端能否独立验证。

### XET 校验值全表

| 值 | 类型 | 计算公式 | 产生时机 | 出现在 API 中？ | 下载端能验？ |
|----|------|----------|---------|----------------|------------|
| **`chunk_hash`** | MerkleHash (32B) | `blake3(keyed=DATA_KEY, uncompressed_data)` | 上传分块时 (`chunk.rs:12-17`) | ❌ footer 被剥离 | ✅ 解压后可算，但无原始值对比 |
| **`xorb_hash`** | MerkleHash (32B) | `aggregated_node_hash([(chunk_hash, size)])` BF=4 Merkle tree | `RawXorbData::from_chunks()` (`raw_xorb_data.rs:41`) | `term.hash` + `fetch_info/xorbs` key | ✅ 需完整下载 xorb（跨文件共享可分摊） |
| **`file_hash`** | MerkleHash (32B) | `aggregated_node_hash(chunks).hmac(zero_salt)` | `file_deduplication.rs:407` | `files` key | ✅ 完整组装后验 |
| **`range_hash`** | MerkleHash (32B) | `blake3(keyed=VERIFICATION_KEY, concat(chunk_hashes[range]))` | `file_deduplication.rs:423-424` | ❌ 仅在 MDB shard 中 | ❌ API 不返回 |
| **`sha256`** | 32B | 标准 SHA256 | 上传时可选 | ❌ 仅在 MDB shard 中 | ❌ API 不返回 |

### Hash 链公式（Python/Rust 已验证）

**chunk_hash**:
```
chunk_hash = blake3.keyed_hash(DATA_KEY, uncompressed_data)
```

**xorb_hash** (Merkle tree, BF=4):
```
write_hash_entry(buf, h[0].to_le(), ..., h[3].to_le(), size)  → "{:016x}{:016x}{:016x}{:016x} : {size}\n"
merged_hash_of_sequence = blake3.keyed_hash(INTERNAL_NODE_HASH, buf)
is_natural_cut(h) = (h[3] % 4 == 0)  # 第4个 u64 LE
next_merge_cut: start at index 2, find is_natural_cut or MAX_GROUP
aggregated_node_hash: 迭代合并直到剩1个
```

**file_hash**:
```
file_hash = aggregated_node_hash(chunks).hmac([0; 32])
           = blake3.keyed_hash(zero_salt, aggregated_node_hash_bytes)
```

**range_hash**:
```
range_hash = blake3.keyed_hash(VERIFICATION_KEY, concat(chunk_hashes[range]))
```

### 关键常量

| 常量 | 值 | 位置 |
|------|-----|------|
| DATA_KEY | `[102,151,245,119,91,149,80,222,49,53,203,172,165,151,24,28,157,228,33,16,155,235,43,88,180,208,176,75,147,173,242,41]` | `data_hash.rs:288-291` |
| INTERNAL_NODE_HASH | `[1,126,197,199,165,71,41,150,253,148,102,102,180,138,2,230,93,221,83,111,55,199,109,210,248,99,82,230,74,83,113,63]` | `data_hash.rs:294-297` |
| VERIFICATION_KEY | `[127,24,87,214,206,86,237,102,18,127,249,19,231,165,195,243,164,205,38,213,181,219,73,230,65,36,152,127,40,251,148,195]` | `chunk_verification.rs:4-7` |
| ZERO_SALT | `[0; 32]` | `aggregated_hashes.rs:194` |
| BF | 4 | `aggregated_hashes.rs:3` |

### 上传流程

```
文件 → [Chunk::new] → chunk_hash = compute_data_hash(chunk_data)
     → [RawXorbData::from_chunks] → xorb_hash = aggregated_node_hash([(chunk_hash, size)])
     → [SerializedXorbObject::from_xorb] → serialized_data (压缩chunks, 无footer)
     → [upload_xorb] → CAS 以 xorb_hash 为键存储 serialized_data
     → [finalize] → file_hash = aggregated_node_hash(all_chunks).hmac(zero_salt)
                  → range_hash = blake3(keyed=VERIFICATION_KEY, concat(segment_chunk_hashes))
                  → 写入 MDB shard: { file_header { file_hash }, segments[{ xorb_hash, ... }], verifications[{ range_hash }] }
```

### 下载流程

```
file_hash（入口）→ GET /v2/reconstructions/{file_hash}
     → 返回 BatchQueryReconstructionResponse
       files: { file_hash → [{ hash: xorb_hash, range, unpacked_length }] }
       fetch_info/xorbs: { xorb_hash → [{ url, ranges: [{ chunks, bytes }] }] }
     → 按 url + Range header 下载 xorb 字节
     → 解析 chunk header → 解压 chunk → 获取 uncompressed_data
     → [可选验证]
       file_hash: 收集所有 (chunk_hash, size) → aggregated_node_hash → hmac(zero) → 对比入口 file_hash
       xorb_hash: 收集一个 xorb 内所有 (chunk_hash, size) → aggregated_node_hash → 对比 fetch_info key
```

### 实际可行的校验策略

由于以下限制：
- **Footer 被剥离**：xorb transfer URL 只返回 chunk data（不包含 boundaries footer 中的 `chunk_hashes` 列表）
- **跨文件共享 xorb**：同一个 xorb 可能被多个文件引用，校验时只需下载一次
- **API 限制**：BATCH/V2 重建 API 只返回当前请求文件引用的 xorb chunk，无法下载完整 xorb（除非所有文件一起请求）

校验能力矩阵（2026-06-29 实测）：
| 层级 | 验证对象 | 能否做 | 依赖 | 实测结果 |
|------|---------|-------|------|---------|
| chunk | data_hash 逐条比对 | ❌ 无法比对 | xorb footer 中的 `chunk_hashes` 列表 | transfer URL 不包含 footer |
| chunk | data_hash 间接验证 | ✅ 通过 xorb_hash/Merkle 聚合 | 完整 xorb | 906/906 chunk 通过 ✅ |
| term | merkle_hash 验证 | ✅ 可做 | 完整 xorb | — |
| xorb | xorb_hash | ✅ 数据完整可做 | 该 xorb 所有 chunk | 1/17 完整 xorb 通过 ✅ |
| file | file_hash | ✅ 始终可做 | 所有 term | Q4_K_M 通过 ✅ |

**关键发现（2026-06-29）**：
1. 完整 xorb（`142d6e57...`）：906 个 chunk 全部通过 `compute_data_hash` → `xorb_hash` 校验 ✅
2. 16/17 个 xorb 存在 gap（chunk 不连续），但**所有文件的 term 引用均不在 gap 中** — 不影响 file_hash 验证
3. **逐 chunk data_hash 验证不可行**：xorb 的传输格式不包含 `chunk_hashes` footer，无法获取期望的 per-chunk hash
4. **跨文件补全不可行**：BATCH API 只返回当前请求文件引用的 chunk，无法通过公开 API 获取完整 xorb

可行的方案是 **file_hash 端到端验证**（已验通）：
1. 下载所有 xorbs（跨文件去重，只下载一次共享 xorb）
2. 解压所有 chunk，按 term.range 组装文件
3. 收集所有 `(chunk_hash, uncompressed_size)` 对
4. 计算 `aggregated_node_hash(pairs)` → `blake3.keyed_hash(zero_salt, root_bytes)` → 对比入口 `file_hash`

xorb_hash 校验可选但有限制：只能对完整 xorb（当前文件所有 term 恰好覆盖全部 chunk）做验证。

### 重建响应结构确认

```rust
// xorb_utils.rs:146-150
terms.push(XorbReconstructionTerm {
    hash: segment.xorb_hash.into(),      // xorb_hash（从 MDB segment 读取）
    unpacked_length: segment.unpacked_segment_bytes,
    range: chunk_range,
});
// fetch_info 的 key 也是 segment.xorb_hash
```

term 的 `hash` = xorb_hash（来自 MDB 的 `segment.xorb_hash`），不是 range_hash。

## 2026-06-24: HostOptimizer 测速"卡"的根因

### 根因：Windows + Python 3.11 的 `SSLConnection.getresponse()` 可无限阻塞

在 `_cas_api_test` 直连模式下：
```python
conn = _http_client.HTTPConnection(ip, 443, timeout=6)
conn.connect()
conn.sock = ctx.wrap_socket(conn.sock, server_hostname=domain)
conn.request("GET", cas_path, headers=headers)
resp = conn.getresponse()  # ← 内部调用 sock.makefile("rb")
```

`getresponse()` 底层调 `sock.makefile("rb")` 创建 `BufferedReader`。
在 **Windows + SSL socket** 上，`makefile()` 创建的缓冲读取器可能**不传播底层 socket 超时异常**，
导致 `getresponse()` 无限阻塞——这解释了为何日志停在"获取 presigned URL: xxx (直连)"不推进。

### 修复（host_optimizer.py）

1. **`_cas_api_test` 直连 timeout: 6s → 3s**，同时外层用 `ThreadPoolExecutor + 8s` 线程超时兜底
2. **`_tcp_rtt` 直连 timeout: 3s → 2s**（用户要求直连 2s 内没连上就别等了）
3. **`_http_transfer_test` / `_data_throughput_test` 直连 timeout: 10s → 3s**（同理）
4. **重排流程：RTT → 证书验证 → HTTP Transfer**（原先证书验证在 HTTP 测速之后，浪费大量时间测被拦截/伪造的 IP）
5. **取消候选 IP 截断**（用户指出并发能处理，不需要 Top N 限制）
6. **增加进度输出**——证书验证开始/完成、CAS API 测速进度等
