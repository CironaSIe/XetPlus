# XET.py (Python 旧版) 下载任务完整流程分析

> 基于 `~/xet.py` 目录的 Python 旧版代码深度分析

---

## 一、架构概览

Python 旧版实现采用**三层架构**：

```
CLI 层 (xet_dl.py)
    ↓
业务逻辑层 (auth.py, cas_client.py, reconstructor.py)
    ↓
基础设施层 (types.py, http_utils.py, xorb_deserializer.py)
```

**核心设计理念**：
- **流式处理**：边下载边写盘，控制内存占用
- **生产者-消费者模式**：下载线程池 + 写盘线程，通过队列解耦
- **分段下载**：大文件切分为多段独立处理，支持断点续传
- **自适应并发**：ACC (Adaptive Concurrency Controller) 动态调整下载线程数

---

## 二、完整下载流程（从 CLI 到文件重建）

### 阶段 0: 初始化与认证

**入口点**: `xet_dl.py::cmd_download()`

```python
# 1. 参数解析与环境检测
repo_id, repo_type, filename = resolve_path(args.path, proxy=proxy)
token = args.token or os.environ.get("HF_TOKEN", "")

# 2. 创建优化的 HTTP Session
session = create_robust_session(
    proxy=proxy,
    trust_env=False,  # 避免意外代理
    retries=5,        # 自动重试
    pool_connections=10  # 连接池
)

# 3. HOST 优选
if args.optimize_hosts:
    optimizer = HostOptimizer(proxy, cache_dir)
    mappings, _, _ = optimizer.optimize()
    # DoH 查询 IP → TCP/HTTP 双向测速 → 选最优路径
```

### 阶段 1: 文件元信息获取

**模块**: `cas_client.py::get_xet_file_info()`

```python
# HEAD 请求获取 X-Xet-* headers
resp = session.head(file_url, allow_redirects=False, timeout=30)

# 关键 headers:
# - X-Xet-Hash: 文件 MerkleHash
# - X-Linked-Size: 文件大小
# - X-Linked-Sha256: SHA256 校验和
# - X-Xet-Auth-Url: CAS token 获取端点
# - Location: Presigned URL (小文件可用)
```

### 阶段 2: CAS Token 认证

**模块**: `auth.py::XetAuth`

```python
# HuggingFace Token → CAS Access Token
auth = XetAuth(hf_token=token, session=session)
token_info = auth.get_token(repo_id, auth_url=xet_info.auth_url)
```

**Token 自动刷新机制**：
- 提前 600s (10 分钟) 主动刷新
- 收到 401 时强制刷新，带重试 + 指数退避
- 缓存机制避免重复请求

### 阶段 3: 模式选择

```python
STREAMING_THRESHOLD = 256 * 1024 * 1024  # 256MB

if mode == "auto":
    if xet_info.size < STREAMING_THRESHOLD and xet_info.location:
        → _download_direct()     # 方案 A: Presigned URL
    else:
        → _download_reconstruction()  # 方案 B: XET 协议
```

---

## 三、方案 A: Direct 模式（Presigned URL）

**适用场景**: 小文件 (<256MB) 且有 Location header

```python
# 1. 预分配文件
with open(target, "wb") as f:
    f.truncate(file_size)

# 2. 流式下载
resp = session.get(location, stream=True, timeout=(10, 120))

# 3. 边下边写
with open(target, "r+b") as f:
    for chunk in resp.iter_content(chunk_size=8*1024*1024):
        f.write(chunk)
        downloaded += len(chunk)

# 4. SHA256 校验
sha256 = calculate_file_sha256(str(target))
```

---

## 四、方案 B: XET Reconstruction 协议

### Step 1: 获取 Reconstruction 信息

**API**: `GET /v2/reconstructions/{file_hash}` (V2 优先) 或 `/v1/...` (回退)

**响应数据**: `QueryReconstructionResponse`

```python
@dataclass
class QueryReconstructionResponse:
    offset_into_first_range: int
    terms: List[CASReconstructionTerm]
    fetch_info: Dict[str, List[CASReconstructionFetchInfo]]
```

### Step 2: 分段策略

```python
seg_bytes = segment_size or (
    256 * MiB if file_size > 10 * GiB else
    64 * MiB if file_size > 1 * GiB else
    4 * MiB
)

# 每段独立请求 reconstruction
for seg_start in range(0, file_size, seg_bytes):
    recon = cas_client.get_reconstruction(
        file_hash,
        range_bytes=(seg_start, seg_end - 1)
    )
```

**断点续传**：
```python
# segments.json 记录已完成段
{
    "file_hash": "...",
    "completed": [
        {"start": 0, "end": 67108864},
        ...
    ]
}
```

### Step 3: StreamFileReconstructor 核心流程

**Pipeline 架构**：
```
主线程 (Term Loop)
    ↓ 提交下载
下载线程池 (max_workers=6)
    ↓ (offset, data)
写盘队列 Queue
    ↓
写盘线程 (daemon)
```

### Step 4: 预取机制

**水位线控制**：
```python
config = XetStreamConfig(
    prefetch_low=48,   # 低水位 (MB)
    prefetch_high=192, # 高水位 (MB)
)

# 当前缓存 < 低水位时触发补充
if current_cache_bytes < prefetch_low * 1024 * 1024:
    submit_download(next_xorb_hash)
```

### Step 5: Xorb 下载与反序列化

```python
# 1. 支持 multipart（一个 xorb 多个 HTTP 范围）
for fi in sorted_infos:
    part_bytes = cas_client.get_xorb_data_with_retry(
        fi.url, fi.url_range, xorb_hash, file_hash
    )

# 2. 合并反序列化
for base_chunk_start, raw_bytes in all_pieces:
    piece = XorbDeserializer.deserialize(raw_bytes)  # LZ4 解压
    # 全局重映射
    global_chunk_idx = base_chunk_start + local_idx
```

### Step 6: URL 自动刷新机制

```python
for attempt in range(retry_max):
    try:
        data = get_xorb_data(url, url_range)
        return data
    except HTTPError as e:
        if e.status_code == 403:  # URL 过期
            if url_coordinator.acquire_refresh():
                recon = get_reconstruction(file_hash)  # 重新获取
        elif e.status_code == 401:  # Token 过期
            _force_refresh_token()
```

**URLRefreshCoordinator 设计**：
- 全局去重：同一时间只允许 1 个线程刷新
- 冷却期：两次刷新间隔至少 20s
- 快速失败：连续 3 次失败后放弃

### Step 7: Term 数据重建

```python
# 1. 获取起始 chunk 的字节偏移
start_chunk_idx = term.range.start
start_byte = chunk_offset_dict[start_chunk_idx]

# 2. 使用 unpacked_length 计算结束位置
end_byte = start_byte + term.unpacked_length

# 3. 提取数据
chunk_data = xorb_data.data[start_byte:end_byte]

# 4. 第一个 term 的偏移补偿
if term_index == 0 and offset_into_first_range > 0:
    chunk_data = chunk_data[offset_into_first_range:]
```

---

## 五、并发控制机制

### 1. AdaptiveConcurrencyController (ACC)

```python
class AdaptiveConcurrencyController:
    def __init__(self, initial=4, min=1, max=64):
        self._semaphore = Semaphore(initial)
        self._ewma_success_rate = 1.0
```

**调整策略**：
- 成功率 > 80% → 并发 +1
- 成功率 < 50% → 并发 //2
- 最小间隔 500ms

### 2. RetryCoordinator（全局重试协调）

```python
def should_stop_retrying(self):
    # 所有活跃下载都在重试 + 超过宽限期 → 全局停止
    if self._active_downloads == self._retrying_downloads:
        if time.time() - self._last_success > 120:
            return True
```

---

## 六、与 Rust 版本的关键差异

### 1. 并发模型

| 特性 | Rust (xet-core) | Python (xet.py) |
|------|----------------|-----------------|
| 异步框架 | Tokio | ThreadPoolExecutor |
| 下载并发 | async/await | 线程池 |
| 写盘模式 | 异步 I/O | 同步 I/O + 独立线程 |

### 2. 断点续传粒度

| 类型 | Rust | Python |
|------|------|--------|
| 文件级 | ✅ | ✅ |
| 段级 | ✅ | ✅ (segments.json) |
| Term 级 | ✅ | ✅ (每 10 terms) |
| Xorb 级 | ❌ | ✅ (磁盘缓存) |

**Python 版本的 xorb 磁盘缓存是亮点**，段间自动复用。

### 3. 错误处理

| 场景 | Rust | Python |
|------|------|--------|
| Token 401 | 3 次重试 | 3 次重试 + 强制刷新 |
| URL 403 | URL Provider 刷新 | URLRefreshCoordinator 去重 |
| 低速超时 | ❌ | ✅ (LowSpeedTimeoutError) |
| 全局协调 | ❌ | ✅ (RetryCoordinator) |

---

## 七、关键设计亮点

1. **水位线预取**: 低水位 48MB、高水位 192MB
2. **全局单 Writer**: 并行多段共享一个写盘线程
3. **磁盘缓存 range-aware**: 避免 multipart 冲突
4. **低速持续检测**: 滑动窗口计算区间速度
5. **.part 文件设计**: 显示真实进度

---

## 八、已知限制

1. **GIL 瓶颈**: Python GIL 限制 CPU 密集型并行
2. **内存拷贝**: bytearray 拼接多次拷贝
3. **HTTP/1.1**: requests 不支持 HTTP/2
4. **BLAKE3 性能**: 纯 Python 实现慢

---

**文档创建日期**: 2026-06-21  
**分析基于**: ~/xet.py (Python 旧版代码)  
**维护者**: XET+ Team
