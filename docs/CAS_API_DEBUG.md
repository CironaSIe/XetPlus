# CAS API 调试参考

本文档记录 XET CAS (Content-Addressable Storage) API 的调用样本，包括输入、输出和错误情况，用于调试和测试。

---

## API 概览

XET CAS 系统提供以下核心 API：

1. **detect_xet_file** - 检测文件是否为 XET 格式
2. **get_reconstruction** - 获取文件重建信息
3. **get_xorb_data** - 下载 xorb 数据段

---

## 1. detect_xet_file

### 功能
检测 HuggingFace 上的文件是否为 XET 格式，并返回元数据。

### API 调用

```python
from xet.network.cas_client import CASClient

client = CASClient(
    endpoint="https://api.xethub.hf.co",
    token="hf_xxxxx"
)

result = client.detect_xet_file(
    repo_id="mykor/granite-embedding-97m-multilingual-r2-GGUF",
    filename="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf",
    repo_type="model"
)
```

### 成功响应示例

```json
{
  "is_xet": true,
  "xet_hash": "e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02",
  "size": 105467232,
  "repo_id": "mykor/granite-embedding-97m-multilingual-r2-GGUF",
  "filename": "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf",
  "repo_type": "model"
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_xet` | boolean | 是否为 XET 文件 |
| `xet_hash` | string | 文件的 MerkleHash（64 字符 hex） |
| `size` | integer | 文件大小（字节） |
| `repo_id` | string | 仓库 ID |
| `filename` | string | 文件名 |
| `repo_type` | string | 仓库类型（model/dataset） |

### 错误情况

#### 1. 文件不存在
```json
{
  "error": "File not found",
  "status_code": 404
}
```

#### 2. 非 XET 文件
```json
{
  "is_xet": false,
  "repo_id": "mykor/granite-embedding-97m-multilingual-r2-GGUF",
  "filename": "README.md"
}
```

#### 3. 认证失败
```json
{
  "error": "Unauthorized",
  "status_code": 401
}
```

---

## 2. get_reconstruction

### 功能
获取文件重建所需的完整信息，包括 terms 和 xorb fetch_info。

### API 调用

```python
recon = client.get_reconstruction(
    file_hash="e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02"
)
```

### 成功响应示例

```json
{
  "file_hash": "e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02",
  "offset_into_first_range": 0,
  "terms": [
    {
      "hash": "33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5",
      "range": {
        "start": 118,
        "end": 436
      },
      "unpacked_length": 20686492
    },
    {
      "hash": "edc32dd7fbd51b16c20b2fea7b1d6f23461e332f5be95e32b94ee40f05a13ba6",
      "range": {
        "start": 0,
        "end": 69
      },
      "unpacked_length": 4631229
    }
  ],
  "fetch_info": {
    "33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5": [
      {
        "url": "https://transfer.xethub.hf.co/xorbs/default/33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5?user_id=6a2d4a2e6bdc8e07b474e3fb&repo_id=69f2e9daf437a8f2dd967c21&X-Xet-Signed-Range=bytes%3D8115237-27159926%2C27826825-28647793&Expires=1782024737&Policy=...",
        "chunk_range": {
          "start": 118,
          "end": 409
        },
        "url_range": {
          "start": 8115237,
          "end": 27159926
        }
      },
      {
        "url": "https://transfer.xethub.hf.co/xorbs/default/33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5?...",
        "chunk_range": {
          "start": 419,
          "end": 436
        },
        "url_range": {
          "start": 27826825,
          "end": 28647793
        }
      }
    ],
    "edc32dd7fbd51b16c20b2fea7b1d6f23461e332f5be95e32b94ee40f05a13ba6": [
      {
        "url": "https://transfer.xethub.hf.co/xorbs/default/edc32dd7fbd51b16c20b2fea7b1d6f23461e332f5be95e32b94ee40f05a13ba6?...",
        "chunk_range": {
          "start": 0,
          "end": 69
        },
        "url_range": {
          "start": 0,
          "end": 4631229
        }
      }
    ]
  }
}
```

### 字段说明

#### terms (重建指令)
每个 term 描述"从哪个 xorb 的哪些 chunks 提取数据"：

| 字段 | 类型 | 说明 |
|------|------|------|
| `hash` | string | Xorb 的哈希值 |
| `range.start` | integer | 起始 chunk 索引 |
| `range.end` | integer | 结束 chunk 索引（不包含） |
| `unpacked_length` | integer | 解压后的数据长度（字节） |

#### fetch_info (下载信息)
每个 xorb 的下载 URL 和字节范围：

| 字段 | 类型 | 说明 |
|------|------|------|
| `url` | string | Presigned 下载 URL（CloudFront） |
| `chunk_range` | object | Xorb 中的 chunk 范围 |
| `url_range` | object | HTTP Range 请求的字节范围 |

### 注意事项

1. **URL 有效期**: Presigned URL 包含 `Expires` 参数，通常有效期 24 小时
2. **不需要认证**: 下载 xorb 时不发送 Authorization header（避免 CloudFront 403）
3. **Range 请求**: 使用 HTTP Range 请求下载 xorb 的部分数据

### 错误情况

#### 1. 文件哈希不存在
```json
{
  "error": "Reconstruction not found",
  "status_code": 404
}
```

#### 2. 服务器内部错误
```json
{
  "error": "Internal server error",
  "status_code": 500
}
```

---

## 3. get_xorb_data

### 功能
下载 xorb 的指定字节范围。

### API 调用

```python
segment_data = client.get_xorb_data(
    url="https://transfer.xethub.hf.co/xorbs/default/33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5?...",
    url_range=HttpRange(start=8115237, end=27159926)
)
```

### HTTP 请求

```http
GET /xorbs/default/33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5?... HTTP/1.1
Host: transfer.xethub.hf.co
Range: bytes=8115237-27159926
```

### HTTP 响应

```http
HTTP/1.1 206 Partial Content
Content-Type: application/octet-stream
Content-Length: 19044690
Content-Range: bytes 8115237-27159926/61189429

<binary data>
```

### 返回值
- **类型**: `bytes`
- **长度**: `url_range.end - url_range.start + 1`
- **内容**: 压缩的 xorb segment 数据

### 错误情况

#### 1. Range 超出范围
```http
HTTP/1.1 416 Range Not Satisfiable
Content-Range: bytes */61189429
```

#### 2. URL 过期
```http
HTTP/1.1 403 Forbidden
<Error>
  <Code>AccessDenied</Code>
  <Message>Request has expired</Message>
</Error>
```

#### 3. 网络超时
```python
requests.exceptions.ConnectTimeout: 
  HTTPSConnectionPool(host='transfer.xethub.hf.co', port=443): 
  Max retries exceeded with url: ... 
  (Caused by ConnectTimeoutError(<HTTPSConnection object>, 
  'Connection to transfer.xethub.hf.co timed out. (connect timeout=30)'))
```

---

## 完整下载流程示例

### 示例：下载 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf

#### Step 1: 检测文件
```python
xet_info = client.detect_xet_file(
    repo_id="mykor/granite-embedding-97m-multilingual-r2-GGUF",
    filename="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf",
    repo_type="model"
)
```

**输出**:
```json
{
  "is_xet": true,
  "xet_hash": "e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02",
  "size": 105467232
}
```

#### Step 2: 获取重建信息
```python
recon = client.get_reconstruction(
    file_hash="e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02"
)
```

**输出**:
- `terms`: 17 个
- `fetch_info`: 10 个唯一 xorbs
- 总 segments: 14 个

#### Step 3: 下载 xorbs
```python
for xorb_hash, fetch_infos in recon.fetch_info.items():
    segments = []
    for fi in fetch_infos:
        segment_data = client.get_xorb_data(
            url=fi.url,
            url_range=fi.url_range
        )
        segments.append(segment_data)
    
    # 组装 xorb
    xorb_data = b"".join(segments)
    
    # 解压 xorb
    from xet.storage.xorb_deserializer import XorbDeserializer
    deserializer = XorbDeserializer()
    chunks = deserializer.deserialize(xorb_data)
```

#### Step 4: 按 terms 组装文件
```python
with open("output.gguf", "wb") as f:
    for term in recon.terms:
        # 从对应的 xorb 提取 chunks
        xorb_chunks = xorb_cache[term.hash]
        
        # 提取指定范围的数据
        start_chunk = term.range.start
        end_chunk = term.range.end
        
        data = extract_data(xorb_chunks, start_chunk, end_chunk)
        
        # 写入文件
        f.write(data)
```

---

## 性能指标

### 测试文件: granite-embedding-97M-multilingual-r2-Q4_K_M.gguf

| 指标 | 值 |
|------|-----|
| 文件大小 | 100.6 MB (105,467,232 bytes) |
| Terms 数量 | 17 |
| Xorbs 数量 | 10 |
| Segments 数量 | 14 |
| 下载时间 | ~60-90 秒（4 并发，代理） |
| 平均速度 | ~1.2 MB/s |

### 下载分布
```
Xorb 分布:
- 33d17623... : 2 segments, 19.9 MB
- edc32dd7... : 3 segments, 10.6 MB
- d81566d5... : 1 segment,  51.4 MB
- f52ace46... : 2 segments, 6.7 MB
- ... (其他 6 个 xorbs)

Term 分布:
- 第 1 个 term: 20.7 MB
- 第 2 个 term: 4.6 MB
- 第 3 个 term: 1.7 MB
- ... (其他 14 个 terms)
```

---

## 错误处理建议

### 1. 网络重试
```python
from xet.network.retry import retry_on_network_error

@retry_on_network_error(max_retries=3, backoff=2.0)
def download_segment(url, url_range):
    return client.get_xorb_data(url, url_range)
```

### 2. Checkpoint 保存
```python
# 每下载完一个 xorb 就保存 checkpoint
checkpoint_manager.mark_xorb_completed(
    file_hash=file_hash,
    xorb_hash=xorb_hash
)
```

### 3. 超时处理
```python
# 设置合理的超时时间
session.get(url, timeout=(30, 60))  # (connect, read)
```

---

## 调试技巧

### 1. 查看完整 HTTP 请求
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 保存中间数据
```python
# 保存 reconstruction 响应
import json
with open("recon_debug.json", "w") as f:
    json.dump(recon.to_dict(), f, indent=2)

# 保存下载的 xorb segment
with open(f"xorb_{xorb_hash[:8]}_seg{idx}.bin", "wb") as f:
    f.write(segment_data)
```

### 3. 验证数据完整性
```python
import hashlib

# 验证 xorb hash
actual_hash = hashlib.sha256(xorb_data).hexdigest()
assert actual_hash == xorb_hash, f"Hash mismatch: {actual_hash} != {xorb_hash}"
```

---

## 相关文档

- [XET 架构分析](./XET_ARCHITECTURE_REFERENCE.md)
- [Pipeline 分析](./XET_PIPELINE_ANALYSIS.md)
- [测试计划](./TESTING_PLAN.md)

---

**维护者**: Claude & User  
**最后更新**: 2026-06-21
