# XET 协议规范

> 版本 1.0.0
> 基于 HuggingFace 官方 XET 文档整理
> 整理日期: 2026-06-29

**关键词约定**: 本文档中的"必须(MUST)"、"不得(MUST NOT)"、"必要(REQUIRED)"、"应该(SHOULD)"、"不应该(SHOULD NOT)"、"推荐(RECOMMENDED)"、"可选(MAY)" 遵循 BCP 14 [RFC2119](https://www.ietf.org/rfc/rfc2119.txt) 和 [RFC8174](https://www.ietf.org/rfc/rfc8174.txt) 的定义。

---

## 目录

1. [概述](#1-概述)
2. [内容定义分块 (CDC)](#2-内容定义分块-cdc)
3. [哈希方法](#3-哈希方法)
4. [Xorb 格式](#4-xorb-格式)
5. [文件重构](#5-文件重构)
6. [上传协议](#6-上传协议)
7. [下载协议](#7-下载协议)
8. [分片 (Shard) 格式](#8-分片-shard-格式)
9. [去重](#9-去重)
10. [认证与授权](#10-认证与授权)
11. [CAS API](#11-cas-api)
12. [从 Hub 获取 File ID](#12-从-hub-获取-file-id)
13. [哈希字符串编码规则](#13-哈希字符串编码规则)
14. [参考文件](#14-参考文件)

---

## 1. 概述

XET (Xet) 是一种内容寻址存储协议，支持端到端的数据分块、去重、传输和校验。本规范定义了 chunking、hashing、xorb/shard 对象格式、文件重构语义、认证以及 CAS API。

**核心目标**: 互操作性和确定性。独立实现必须产生相同的哈希值、对象和 API 行为。

### 1.1 对象类型

| 对象 | 描述 |
|------|------|
| **Chunk** | 数据分块，约 64 KiB，通过 CDC 算法确定边界 |
| **Xorb** | Chunk 序列的容器，压缩后上传，最大 64 MiB (~1024 chunks) |
| **Shard** | 文件重构信息和 xorb 元数据的序列化表示 |
| **File Reconstruction** | 描述文件如何从 xorbs 中的 chunk 范围重建的"配方" |

### 1.2 协议流程

```
上传: 文件 → CDC 分块 → hash 计算 → 去重 → xorb 打包 → 上传 xorbs → shard 上传
下载: file_id → reconstruction API → 解析 terms → 下载 xorbs → 解压 → 拼接文件
```

---

## 2. 内容定义分块 (CDC)

### 2.1 常量参数

| 参数 | 值 | 说明 |
|------|------|------|
| `target_chunk_size` | 64 KiB | 目标块大小 |
| `MIN_CHUNK_SIZE` | 8 KiB | 最小块大小（文件最后一块不受限） |
| `MAX_CHUNK_SIZE` | 128 KiB | 最大块大小 |
| `MASK` | `0xFFFF000000000000` | 16 个 1-bit → 边界概率 1/2^16 |
| `TABLE[256]` | 256 个 64-bit 常量 | Gearhash 查表 |

### 2.2 算法步骤

#### 状态
- `h`: 64-bit 哈希，初始化为 0
- `start_offset`: 当前块的起始偏移

#### 逐字节更新规则 (Gearhash)

```
h = (h << 1) + TABLE[b]   // 64-bit 包装算术
```

#### 边界判断

每个字节更新后，计算 `size = current_offset - start_offset + 1`:

- 若 `size < MIN_CHUNK_SIZE`: 跳过 MASK 测试，继续
- 若 `size >= MAX_CHUNK_SIZE`: 强制切分
- 若 `(h & MASK) == 0`: 在当前位置切分

切分时:
- 发出 chunk `[start_offset, current_offset + 1)`
- 设置 `start_offset = current_offset + 1`
- 重置 `h = 0`

#### 伪代码

```
if len(data) < MIN_CHUNK_SIZE:
  emit chunk [0, len(data))
  done

for i in range(0, len(data)):
  b = data[i]
  h = (h << 1) + TABLE[b]      // 64-bit 包装
  size = i + 1 - start_offset

  if size < MIN_CHUNK_SIZE:
    continue
  if size >= MAX_CHUNK_SIZE or (h & MASK) == 0:
    emit chunk [start_offset, i + 1)
    start_offset = i + 1
    h = 0

if start_offset < len(data):
  emit chunk [start_offset, len(data))
```

### 2.3 性能优化: Skip-ahead

由于 Gearhash 的 64 字节窗口效应，可以在每个 chunk 的前 `MIN_CHUNK_SIZE - 64 - 1` 字节跳过逐字节计算，不影响正确性。

### 2.4 特性

- **确定性**: 相同内容产生相同边界
- **局部性**: 小编辑只影响附近边界
- **线性时间、常数内存**: 单个 64-bit 状态

---

## 3. 哈希方法

### 3.1 Chunk Hash (DATA_KEY)

对每个 chunk 数据计算 blake3 keyed hash:

```python
DATA_KEY = bytes([
    102, 151, 245, 119, 91, 149, 80, 222,
    49, 53, 203, 172, 165, 151, 24, 28,
    157, 228, 33, 16, 155, 235, 43, 88,
    180, 208, 176, 75, 147, 173, 242, 41,
])

chunk_hash = blake3(chunk_data, key=DATA_KEY).digest()  # 32 bytes
```

### 3.2 Xorb Hash (Merkle 树)

Xorb hash 是 Merkle 树的根节点哈希。

#### 构建规则

1. **叶节点**: 每个 chunk 的 data_hash
2. **内部节点**: 对子节点序列按格式 `"{hash_hex} : {size}\n"` 拼接后，用 INTERNAL_NODE_KEY 做 keyed blake3

```
INTERNAL_NODE_KEY = bytes([
    1, 126, 197, 199, 165, 71, 41, 150,
    253, 148, 102, 102, 180, 138, 2, 230,
    93, 221, 83, 111, 55, 199, 109, 210,
    248, 99, 82, 230, 74, 83, 113, 63,
])
```

#### Merkle 树聚合算法 (BF=4)

```
1. 从 (hash, size) 对列表开始
2. 每次迭代:
   a. 从列表头部开始扫描
   b. 用 next_merge_cut 决定切分点:
      - 若 n <= 2: 全部合并
      - end = min(2 * BF + 1, n)
      - 在 [2, end) 中找 last_u64 % BF == 0 的位置
      - 若找到, 切分点在 i+1; 否则在 end
   c. 对每组计算 merged_hash_of_sequence
   d. 结果作为新列表
3. 重复直到只剩一个 hash
```

**merged_hash_of_sequence**: 将组内所有 (hash, size) 以 `"{hash_hex} : {size}\n"` 格式拼接，对拼接字节做 keyed blake3。

```
hash_hex : size\n
hash_hex : size\n
...
```

### 3.3 File Hash

File hash = Merkle 树根上再加一层 HMAC:

```
root_hex = aggregated_node_hash([(data_hash, size), ...])
root_bytes = hex_to_hash(root_hex)
file_hash = blake3(root_bytes, key=ZERO_SALT)  # ZERO_SALT = bytes(32)
```

### 3.4 Term Verification Hash

对 term 范围内的所有 chunk hash 做:

```
buffer = b''.join(term.xorb.chunk_hashes[start:end])  # 32B each
verification_hash = blake3(buffer, key=VERIFICATION_KEY)
```

```
VERIFICATION_KEY = bytes([
    127, 24, 87, 214, 206, 86, 237, 102,
    18, 127, 249, 19, 231, 165, 195, 243,
    164, 205, 38, 213, 181, 219, 73, 230,
    65, 36, 152, 127, 40, 251, 148, 195,
])
```

---

## 4. Xorb 格式

### 4.1 打包规则

- 将连续 chunk 收集到 xorb 中，总解压大小约 64 MiB
- 可跨文件打包 chunk（节省空间）
- 序列化后大小不得超过 64 MiB
- 每个 xorb 最多 8192 个 chunk
- Xorb 上传路径：`POST /v1/xorbs/default/{xorb_hash}`

### 4.2 二进制布局

```
┌─────────┬─────────────────────┬─────────┬─────────────────────┐
│ Header  │ Compressed Data #0  │ Header  │ Compressed Data #1  │ ...
│ (8B)    │                     │ (8B)    │                     │
└─────────┴─────────────────────┴─────────┴─────────────────────┘
  Chunk 0                          Chunk 1
```

### 4.3 Chunk Header (8 字节)

```
┌─────────┬─────────────────────┬──────────────┬─────────────────────┐
│ Version │  Compressed Size    │  Compression │  Uncompressed Size  │
│  1B     │       3B (LE)       │  Type 1B     │       3B (LE)       │
└─────────┴─────────────────────┴──────────────┴─────────────────────┘
0         1                     4              5                     8
```

| 字段 | 说明 |
|------|------|
| Version | 协议版本，当前为 0 |
| Compressed Size | 压缩后数据大小 (3 字节 LE) |
| Compression Type | 压缩方案 (见下表) |
| Uncompressed Size | 原始数据大小 (3 字节 LE) |

### 4.4 压缩方案

| 值 | 名称 | 描述 |
|-----|------|------|
| 0 | `None` | 无压缩 |
| 1 | `LZ4` | 标准 LZ4 压缩 (lz4 frame) |
| 2 | `ByteGrouping4LZ4` | 4 字节分组 + LZ4，优化浮点/结构化数据 |

#### ByteGrouping4LZ4

将数据按 4 字节交错分组（round-robin 分配到 group 0-3），再对分组数据做 LZ4:

```
原始:   [A1, A2, A3, A4, B1, B2, B3, B4, C1, C2, C3, C4, ...]
分组后: [A1, B1, C1, ..., A2, B2, C2, ..., A3, B3, C3, ..., A4, B4, C4, ...]
```

### 4.5 Xorb Footer（CasObjectInfo）

Serialized xorbs 末尾有一个可选的 footer 区域，用于存储元数据。布局如下:

```
┌─────────────────────────────────────────┐
│ Chunk Data Region                        │
│ [chunk header + compressed data] × N    │
├─────────────────────────────────────────┤
│ CasObjectInfo Footer (可变长)            │
├─────────────────────────────────────────┤
│ Info Length (4B LE, footer 长度)         │
└─────────────────────────────────────────┘
```

- 文件最后 4 字节为 `info_length`（仅 footer 部分的长度，不含这 4 字节自身）
- `info_length = 0` 表示无 footer（常见情况）
- Xorb 序列化后总大小不得超出 `MAX_XORB_SIZE = 65536` (64 GiB)，实际 HF 限 64 MiB

### 4.6 选择压缩方案

实现者自行决定策略，如：
- **暴力尝试**: 尝试所有方案，选择最优
- **预测**: xet-core 使用 KL 散度判断 BG4 是否有利

---

## 5. 文件重构

### 5.1 Term 格式

每个 term 是一个 (xorb_hash, chunk_range) 对:

```
Term {
    hash: xorb_hash (64 hex chars)
    range: [start, end)  // chunk 索引范围，左闭右开
    unpacked_length: 解压后总字节数
}
```

### 5.2 重构规则

1. 按 term 顺序处理
2. 对每个 term，从 xorb 中提取指定 chunk 范围
3. 解压 chunk 到原始字节
4. 按 term 顺序拼接

### 5.3 子范围下载

支持 HTTP Range 下载文件的一部分:
- `offset_into_first_range`: 跳过第一个 term 的前 N 字节
- 最后一个 term 可能需要截断尾部

---

## 6. 上传协议

### 6.1 步骤概览

1. **分块**: CDC 算法切分文件
2. **去重**: 检查 chunk 是否已存在（本地缓存 + 全局去重 API）
3. **Xorb 打包**: 收集连续 chunk 为 xorb，计算 xorb hash
4. **上传 Xorbs**: `POST /v1/xorbs/default/{hash}`
5. **构造 Shard**: 构建文件重构信息 + xorb 元数据
6. **上传 Shard**: `POST /v1/shards`

### 6.2 顺序约束

**所有 xorb 必须在引用它们的 shard 上传之前完成上传。**

### 6.3 去重流程

```
对每个 chunk（可选）:
  若 eligible（第一个 chunk 或 last_u64 % 1024 == 0）:
    GET /v1/chunks/default-merkledb/{chunk_hash}
    → 200: 获得 shard，内含 HMAC 保护的 chunk 列表
    → 404: chunk 不存在，需要上传
```

### 6.4 完整性

- Chunk hash 绑定内容 → 相同内容产生相同 hash
- Xorb hash 绑定 chunk 集合 → 相同 chunk 集合产生相同 xorb hash
- 上传端点是幂等的（按内容寻址键）

---

## 7. 下载协议

### 7.1 两阶段流程

#### Stage 1: Reconstruction API 查询

```
GET /v1/reconstructions/{file_id}
Authorization: Bearer <token>
可选: Range: bytes=<start>-<end>
```

响应: `QueryReconstructionResponse` JSON

#### Stage 2: 数据获取与组装

```
For each term in terms[]:
  1. 从 fetch_info 找到匹配的下载信息
  2. GET {url} with Range: bytes=<url_range.start>-<url_range.end>
  3. 解包 xorb，提取 chunk
  4. 裁剪到 term 范围
  5. 拼接结果
```

### 7.2 QueryReconstructionResponse

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

### 7.3 性能建议

- **Range 合并**: 多个 term 可能共享同一 fetch_info
- **并行下载**: term 可并行下载，按序组装
- **缓存**: 缓存已下载的 xorb 范围避免重复请求
- **重试**: 指数退避处理瞬时故障

---

## 8. 分片 (Shard) 格式

### 8.1 结构总览

```
┌─────────────────────────┐
│ Header (48B, 固定)       │
├─────────────────────────┤
│ File Info Section       │  ← 文件重构信息
├─────────────────────────┤
│ CAS Info Section        │  ← Xorb 元数据（含 chunk hash 列表）
├─────────────────────────┤
│ Footer (200B, 可选)     │  ← HMAC key + 偏移量
└─────────────────────────┘
```

### 8.2 Header (48 字节)

```
tag:       [u8; 32]  // Magic 标识
version:   u64       // 必须为 2
footer_sz: u64       // Footer 大小（0 表示无 footer）
```

### 8.3 File Info Section

每个文件对应一个 `FileDataSequenceHeader` + N 个 `FileDataSequenceEntry` + 可选的 `FileVerificationEntry` + 可选的 `FileMetadataExt`。以 bookend 结尾。

#### FileDataSequenceHeader (48 字节)

```
file_hash:    [u8; 32]  // 文件 hash
file_flags:   u32       // 标志位
num_entries:  u32       // term 数量
_unused:      [u8; 8]
```

标志位:
- `0x80000000`: 有 Verification Entries
- `0x40000000`: 有 Metadata Extension (SHA256)

#### FileDataSequenceEntry (48 字节) = 1 个 Term

```
cas_hash:              [u8; 32]  // xorb hash
cas_flags:             u32
unpacked_segment_bytes: u32      // term 解压后大小
chunk_index_start:     u32       // 起始 chunk 索引
chunk_index_end:       u32       // 结束 chunk 索引（不含）
```

#### FileVerificationEntry (48 字节)

```
range_hash:  [u8; 32]  // verification hash
_unused:     [u8; 16]
```

#### FileMetadataExt (48 字节)

```
sha256:   [u8; 32]  // 文件 SHA256
_unused:  [u8; 16]
```

### 8.4 CAS Info Section

每个 xorb 对应一个 `CASChunkSequenceHeader` + N 个 `CASChunkSequenceEntry`。以 bookend 结尾。

#### CASChunkSequenceHeader (48 字节)

```
cas_hash:          [u8; 32]  // xorb hash
cas_flags:         u32
num_entries:       u32       // 该 xorb 中的 chunk 数量
num_bytes_in_cas:  u32       // 所有 chunk 原始字节总数
num_bytes_on_disk: u32       // 序列化后 xorb 大小
```

#### CASChunkSequenceEntry (48 字节)

```
chunk_hash:            [u8; 32]  // chunk hash（可能被 HMAC 保护）
chunk_byte_range_start: u32
unpacked_segment_bytes: u32
_unused:               [u8; 8]
```

### 8.5 Footer (200 字节)

```
version:               u64    // 必须为 1
file_info_offset:      u64    // File Info Section 偏移
cas_info_offset:       u64    // CAS Info Section 偏移
_buffer:               [u8; 48]
chunk_hash_hmac_key:   [u8; 32]  // HMAC key
shard_creation_timestamp: u64  // 创建时间戳
shard_key_expiry:      u64       // 过期时间戳
_buffer2:              [u8; 72]
footer_offset:         u64       // Footer 起始偏移
```

### 8.6 Bookend

File Info 和 CAS Info 部分都以 bookend 结束：
- 32 字节全 `0xFF` + 16 字节全 `0x00`

### 8.7 反序列化算法

```
方法一（线性流式）:
  header = read_header()
  file_info = read_file_info_until_bookend()
  cas_info = read_cas_info_until_bookend()
  footer = read_footer()

方法二（seek + footer）:
  header = read_header()
  seek(end - footer_size)
  footer = read_footer()
  seek(footer.file_info_offset)
  file_info = read_file_info()
  seek(footer.cas_info_offset)
  cas_info = read_cas_info()
```

### 8.8 HMAC 保护

若 footer 中 `chunk_hash_hmac_key` 非零:
- CAS Info 中的 chunk_hash 已加密:
  `stored_hash = blake3(original_hash, key=hmac_key).digest()`
- 验证时: 对本地 data_hash 做同样计算后匹配

---

## 9. 去重

### 9.1 三级去重策略

| 级别 | 范围 | 机制 |
|------|------|------|
| Level 1: Session | 当前上传会话 | 内存 hash 表 |
| Level 2: 本地缓存 | 之前上传的本地 shard | 磁盘缓存 |
| Level 3: 全局去重 | 整个 XET 系统 | `GET /v1/chunks/default-merkledb/{hash}` |

### 9.2 全局去重资格条件

只有以下 chunk 可以查询全局去重:
1. **文件第一个 chunk**: 总是 eligible
2. **Hash 模式匹配**: `last 8 bytes of hash (LE u64) % 1024 == 0`

推荐每 ~4MB 数据发送一个去重请求。

### 9.3 全局去重流程

```
1. 计算 chunk hash
2. 若 eligible，异步发起 GET /v1/chunks/default-merkledb/{hash}
3. 收到 shard 响应:
   - CAS Info Section 包含若干 xorb 的 chunk 列表
   - chunk hash 经过 HMAC 加密
   - Footer 中包含 HMAC key
4. 客户端用 HMAC key 加密自己的 chunk hash
5. 在 shard 中搜索匹配
6. 匹配成功: 引用已有 xorb，无需上传
```

### 9.4 碎片化预防

推荐保持连续的 chunk 运行在同一个 xorb 中（如至少 8 个连续 chunk，或总长 >= 1MB），避免因过度去重导致文件碎片化。

---

## 10. 认证与授权

### 10.1 Token 获取

```
GET https://huggingface.co/api/{repo_type}s/{repo_id}/xet-{token_type}-token/{revision}
Authorization: Bearer <hf_token>
```

参数:
- `repo_type`: `model` | `dataset` | `space`
- `repo_id`: `namespace/repo-name`
- `token_type`: `read` | `write`
- `revision`: git revision (branch/tag/commit)

响应:
```json
{
  "accessToken": "xet_xxxx...",
  "exp": 1848535668,
  "casUrl": "https://cas-server.xethub.hf.co"
}
```

### 10.2 Token 作用域

| Scope | 可访问 API |
|-------|-----------|
| `read` | `GET /v1/reconstructions/{id}`、`GET /v1/chunks/{prefix}/{hash}` |
| `write` | 所有 read API + `POST /v1/xorbs/{prefix}/{hash}` + `POST /v1/shards` |

Token 有效期内建议提前 30 秒刷新。

---

## 11. CAS API

### 11.1 端点总表

| 方法 | 路径 | 作用 | 最少 Scope |
|------|------|------|-----------|
| `GET` | `/v1/reconstructions/{file_id}` | 获取文件重构信息 | read |
| `GET` | `/v1/chunks/{prefix}/{hash}` | 全局去重查询 | read |
| `POST` | `/v1/xorbs/{prefix}/{hash}` | 上传 xorb | write |
| `POST` | `/v1/shards` | 上传 shard | write |

### 11.2 错误码

| 状态码 | 含义 | 是否重试 |
|--------|------|---------|
| 400 | 请求参数无效 | 否 |
| 401 | Token 无效/过期 | 刷新后重试 |
| 403 | 权限不足 | 否 |
| 404 | 资源不存在 | 否 |
| 416 | Range 越界 | 否 |
| 429 | 限流 | 是（退避） |
| 500 | 服务端错误 | 是 |
| 503 | 服务不可用 | 是 |
| 504 | 网关超时 | 是 |

---

## 12. 从 Hub 获取 File ID

### 12.1 步骤

1. 构造 resolve URL:
   ```
   https://huggingface.co/{namespace}/{repo}/resolve/{branch}/{filepath}
   ```

2. 发送 GET 请求（不跟踪 redirect）:
   ```python
   resp = session.get(url, headers={"Authorization": "Bearer <token>"}, allow_redirects=False)
   ```

3. 从 `X-Xet-Hash` 响应头获取 file_id:
   ```
   X-Xet-Hash: e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02
   ```

4. 在 reconstruction API 中使用此值:
   ```
   GET {cas_url}/v1/reconstructions/{file_id}
   ```

### 12.2 其他响应头

| 头 | 说明 |
|----|------|
| `X-Xet-Hash` | XET file ID (file hash) |
| `X-Linked-ETag` | SHA256 (带引号) |
| `X-Linked-Size` | 文件真实大小 |
| `X-Repo-Commit` | Git commit hash |

---

## 13. 哈希字符串编码规则

### 13.1 32 bytes → 64 hex 字符

将 32 字节 hash 分为 4 组，每组 8 字节作为 LE u64:

```
bytes:  [0,1,2,3,4,5,6,7, 8,9,10,11,12,13,14,15, ...]
先反转每组字节顺序再 hex:
        [7,6,5,4,3,2,1,0, 15,14,13,12,11,10,9,8, ...]
```

等价于:
```python
def hash_to_hex(digest_32):
    u64s = struct.unpack('<4Q', digest_32)
    return ''.join(f'{u:016x}' for u in u64s)
```

### 13.2 示例

输入 bytes `[0..31]` 输出**不是** `0001020304050607...` 而是:
```
07060504030201000f0e0d0c0b0a0908171615141312111f1e1d1c1b1a1918
```

---

## 14. 参考文件

官方提供了参考文件数据集用于验证实现:
[xet-team/xet-spec-reference-files](https://huggingface.co/datasets/xet-team/xet-spec-reference-files)

包含:
- `Electric_Vehicle_Population_Data_20250917.csv` — 原始 CSV 文件
- `*.chunks` — 分块结果 (hash + size)
- `*.xorb` — 序列化 xorb
- `*.xet-file-hash` — 预期 file hash
- `*.xet-xorb-hash` — 预期 xorb hash
- `*.xorb.range-hash` — 预期 verification hash
- `*.shard.dedupe` — 去重查询响应 shard
- `*.shard.verification` — 上传用 shard（含 footer）
- `*.shard.verification-no-footer` — 上传用 shard（无 footer）
- `*.chunk` — 单 chunk 数据文件（文件名即为预期 chunk hash）

---

## 附录 A: 关键常量汇总

| 常量 | 值 |
|------|-----|
| DATA_KEY | 32 字节（见 §3.1） |
| INTERNAL_NODE_KEY | 32 字节（见 §3.2） |
| VERIFICATION_KEY | 32 字节（见 §3.4） |
| ZERO_SALT | `bytes(32)` |
| BRANCHING_FACTOR | 4 |
| MIN_CHUNK_SIZE | 8 KiB |
| MAX_CHUNK_SIZE | 128 KiB |
| TARGET_CHUNK_SIZE | 64 KiB |
| Xorb 大小上限 | 64 MiB |
| Chunk Header 大小 | 8 字节 |
| Shard Header 大小 | 48 字节 |
| Shard Footer 大小 | 200 字节 |
| HMAC key 长度 | 32 字节 |
| Hash 长度 | 32 字节 (256-bit) |

## 附录 B: 参考实现

### B.1 官方参考实现

| 实现 | 语言 | 仓库 |
|------|------|------|
| xet-core | Rust | `https://github.com/huggingface/xet-core` |
| hugginface.js (XetBlob.ts) | TypeScript | `packages/hub/src/utils/XetBlob.ts` |
| hf_xet（Python 绑定） | Rust → Python | 集成在 `huggingface_hub` |

### B.2 IETF 标准化

XET 协议已提交 IETF 标准化:
- Draft: `draft-denis-xet-04`（2026-06-14 发布, 2026-12 过期）
- 状态: Informational
- GitHub: `https://github.com/jedisct1/draft-denis-xet`

### B.3 本项目中 XET 协议的 Python 实现

| 文件 | 实现内容 |
|------|---------|
| `xet/storage/merkle_hash.py` | Merkle 哈希计算（data_hash, xorb_hash, file_hash） |
| `xet/storage/mdb_shard.py` | MDB Shard 二进制反序列化 |
| `xet/storage/xorb_deserializer.py` | Xorb 反序列化（含 CasObjectInfo footer 处理） |
| `xet/protocol/xorb_format.py` | Chunk 格式解析、解压 |
| `xet/protocol/types.py` | 协议数据结构定义（含 V1/V2 格式转换） |
| `xet/network/cas_client.py` | CAS API 客户端 |
