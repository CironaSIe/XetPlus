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
