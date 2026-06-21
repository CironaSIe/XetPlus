# XET Core (Rust) 下载任务完整流程分析

> 基于 `~/xet` 目录的 Rust 原版代码深度分析

---

## 1. 下载流程架构

### 1.1 主要模块和组件层次

```
CLI/应用层
    ↓
FileDownloadSession (xet_data/processing/file_download_session.rs)
    ↓
FileReconstructor (xet_data/file_reconstruction/file_reconstructor.rs)
    ↓
ReconstructionTermManager (xet_data/file_reconstruction/reconstruction_terms/manager.rs)
    ↓
FileTerm + XorbBlock (xet_data/file_reconstruction/reconstruction_terms/)
    ↓
RemoteClient (xet_client/cas_client/remote_client.rs)
    ↓
ChunkCache (xet_client/chunk_cache/)
    ↓
CAS API / S3 Presigned URLs
```

### 1.2 核心组件职责

**FileDownloadSession**
- 管理下载会话，持有 CAS client 和 chunk cache
- 提供多种下载接口：文件、writer、stream、unordered stream
- 管理进度跟踪（GroupProgress）
- 控制全局文件下载信号量（避免过多并发文件下载）

**FileReconstructor**
- 单个文件的重建协调器
- 管理字节范围（byte range）下载
- 控制内存缓冲区（download buffer semaphore）
- 支持取消令牌（CancellationToken）
- 动态缓冲区扩展：`base + n * perfile`，最大 `limit`

**ReconstructionTermManager**
- 自适应预取管理器
- 维护预取队列（prefetch queue）
- 基于完成速率估算器（ExpWeightedMovingAvg）动态调整预取大小
- 初始预取两个小块以快速启动

**FileTerm & XorbBlock**
- FileTerm：文件的一个连续字节范围，映射到 xorb 的 chunk 范围
- XorbBlock：可下载的 xorb 块，支持多个不连续 chunk 范围（V2 multi-range）
- 单例飞行模式（single-flight）：第一个调用者下载，其他等待同一结果

**RemoteClient**
- HTTP 客户端包装器
- V2/V1 API 自动降级
- 自适应并发控制（AdaptiveConcurrencyController）
- 重试包装器（RetryWrapper）

**ChunkCache**
- 磁盘级 chunk 缓存
- LRU 随机驱逐策略
- 基于 (prefix, hash, chunk_range) 的键

---

## 2. URL 和鉴权机制

### 2.1 CAS API 端点设计

**重建 API 版本**

**V2（首选）**: `/v2/reconstructions/{file_hash}`
- 返回 `QueryReconstructionResponseV2`
- 支持 multi-range fetch（一个 URL 多个字节范围）
- 每个 xorb 通常 1 个 fetch entry，URL 长度限制时分割

**V1（降级）**: `/v1/reconstructions/{file_hash}`
- 返回 `QueryReconstructionResponse`
- 每个 chunk 范围一个独立的 presigned URL
- 客户端自动转换为 V2 格式

**自动降级机制**
```rust
// RemoteClient 跟踪检测到的 API 版本
detected_reconstruction_api_version: AtomicU32

// 首次尝试 V2，404/501 时降级到 V1
match self.get_reconstruction_v2(file_id, bytes_range).await {
    Ok(result) => { self.detected_reconstruction_api_version.store(2, ...); }
    Err(404|501) => { 
        let v1 = self.get_reconstruction_v1(...).await?;
        self.detected_reconstruction_api_version.store(1, ...);
        Ok(v1.map(Into::into))  // 转换为 V2 格式
    }
}
```

### 2.2 认证方式

**Token-based 认证**
```rust
pub struct AuthConfig {
    pub token: String,
    pub token_expiration: u64,  // Unix epoch seconds
    pub token_refresher: Arc<dyn TokenRefresher>,
}
```

**TokenProvider**
- 自动刷新：过期前 30 秒（`REFRESH_BUFFER_SEC`）
- `DirectRefreshRouteTokenRefresher`：通过 HTTP GET 获取新 JWT
- 返回 `(access_token, exp)` 元组

**HTTP 客户端层次**
- `http_client`: 无认证（用于 S3 presigned URLs）
- `authenticated_http_client`: 带 Bearer token（用于 CAS API）
- `shard_upload_http_client`: 无读取超时（用于大型 shard 上传）

### 2.3 Presigned URL 使用

**URL 结构**
```rust
pub struct TermBlockRetrievalURLs {
    pub file_hash: MerkleHash,
    pub byte_range: FileRange,
    // (acquisition_id, Vec<(url, http_ranges)>)
    pub xorb_block_retrieval_urls: RwLock<(UniqueId, Vec<(String, Vec<HttpRange>)>)>,
}
```

**URL 刷新机制**
- 403 错误触发 `refresh_url()`
- 使用 acquisition_id 实现单例飞行去重
- 重新获取整个 block 的 reconstruction 信息
- 验证返回范围匹配预期

**XorbURLProvider**
```rust
impl URLProvider for XorbURLProvider {
    async fn retrieve_url(&self) -> Result<(String, Vec<HttpRange>)> {
        let (unique_id, url, http_ranges) = 
            self.url_info.get_retrieval_url(self.xorb_block_index).await;
        *self.last_acquisition_id.lock().await = unique_id;
        Ok((url, http_ranges))
    }
    
    async fn refresh_url(&self) -> Result<()> {
        self.url_info.refresh_retrieval_urls(
            &self.ctx, self.client, *self.last_acquisition_id.lock().await
        ).await
    }
}
```

---

## 3. 核心设计机制

### 3.1 Xorb 下载和解压

**数据流**
```
HTTP Range Request (compressed bytes)
    ↓
DownloadProgressStream (进度跟踪)
    ↓
deserialize_chunks_to_writer_from_stream (流式解压)
    ↓
XorbBlockData { chunk_offsets, data: Bytes }
```

**Multi-range 支持**
- **单范围**：`Range: bytes=100-200`
- **多范围**：`Range: bytes=100-200,300-400,500-600`
- 响应类型：
  - 单范围：`Content-Type: application/octet-stream`
  - 多范围：`Content-Type: multipart/byteranges; boundary=...`

**Multipart 解析**
```rust
// parse_multipart_byteranges 解析 multipart/byteranges 响应
for part in multipart_parts {
    let (data, chunk_indices) = deserialize_chunks(&mut Cursor::new(part.data))?;
    append_chunk_segment(&mut all_decompressed, &mut all_chunk_indices, &data, &chunk_indices);
}
```

### 3.2 Chunk 缓存设计

**缓存键结构**
```rust
pub struct Key {
    pub prefix: String,  // e.g., "default"
    pub hash: MerkleHash,
}

// 缓存查找
cache.get(&cache_key, &chunk_range) -> Option<CacheRange>

pub struct CacheRange {
    pub offsets: Vec<u32>,  // chunk 字节偏移
    pub data: Vec<u8>,      // 解压后数据
}
```

**磁盘布局**
```
cache_root/
├── [ab]/                    # 前2字符分组 (base64)
│   ├── [key1_ab123...]/
│   │   ├── [range_0-100_len_hash]
│   │   ├── [range_102-300_len_hash]
│   │   └── [range_900-1024_len_hash]
```

**缓存操作**
- **Put**: 异步写入（`tokio::spawn`），不阻塞主流程
- **Get**: 同步读取，命中后报告进度（模拟网络下载进度）
- **Eviction**: 随机 LRU，驱逐到容量限制
- **Verification**: 使用 `VerificationCell<CacheItem>` 存储校验和

**限制**
- 当前只缓存第一个 ChunkRange（多范围块需要重新设计键）

### 3.3 Reconstruction 流程

**外层循环：预取块迭代**
```rust
loop {
    let maybe_file_terms = tokio::select! {
        biased;
        _ = run_state.cancelled() => { return Ok(0); }
        result = term_manager.next_file_terms() => result?
    };
    
    let Some(file_terms) = maybe_file_terms else { break; };
    
    // 内层循环：处理每个 file term
    for file_term in file_terms {
        // 1. 获取缓冲区许可
        let buffer_permit = acquire_permit(...).await?;
        
        // 2. 创建数据获取任务（单例飞行）
        let data_future = file_term.get_data_task(...).await?;
        
        // 3. 传递给 data writer
        data_writer.set_next_term_data_source(
            relative_byte_range, 
            Some(buffer_permit), 
            data_future
        ).await?;
    }
}

data_writer.finish().await?;
```

**FileReconstructor 配置选项**
- `byte_range`: 字节范围下载
- `progress_updater`: 进度回调
- `chunk_cache`: 可选磁盘缓存
- `config`: ReconstructionConfig
- `custom_buffer_semaphore`: 测试用
- `cancellation_token`: 取消支持

### 3.4 断点续传机制

**不是传统意义的断点续传**

XET 设计中没有 `.part` 文件或断点续传状态持久化。重新下载会：
1. 重新获取 reconstruction info
2. 可能命中 chunk cache（跨文件去重）
3. 重新开始流式写入

**Range 下载支持**
```rust
// 支持任意字节范围
reconstructor.with_byte_range(FileRange::new(1024, 4096))

// 并发分片下载到同一文件（不截断）
for shard in shards {
    let reconstructor = FileReconstructor::new(...)
        .with_byte_range(shard.range);
    reconstructor.reconstruct_to_file(&path, None, false).await?;
}
```

### 3.5 错误处理和重试策略

**RetryWrapper 配置**
```rust
RetryWrapper::new(ctx, api_tag)
    .with_429_no_retry()           // 429 不重试
    .with_expected_404()           // 404 静默
    .with_expected_416()           // 416 Range Not Satisfiable
    .with_retry_on_403()           // 403 触发 URL 刷新
    .with_connection_permit(permit, None)
    .log_errors_as_info()
    .run(|| client.get(url).send())
    .await?
```

**重试策略**
- 指数退避：初始 100ms，最大 5s
- 最大重试次数：5 次（可配置）
- 可重试错误：网络错误、5xx、408、429
- 不可重试：4xx（除 429/403）、解析错误

**403 特殊处理**
```rust
if response.status() == StatusCode::FORBIDDEN {
    url_info.refresh_url().await?;  // 刷新 presigned URL
}
```

### 3.6 回退设计

**V2 → V1 API 降级**
```rust
match get_reconstruction_v2(...).await {
    Ok(v2) => Ok(v2),
    Err(404|501) if not_forced => {
        let v1 = get_reconstruction_v1(...).await?;
        Ok(v1.map(Into::into))  // 转换为 V2 格式
    }
}
```

**Multi-range → Single-range 降级**
```rust
// enable_multirange_fetching = false 时
// 每个 XorbRangeDescriptor 创建独立 XorbBlock
for range in &fetch_entry.ranges {
    xorb_blocks.push(XorbBlock {
        chunk_ranges: vec![range.chunks],  // 单范围
        // ...
    });
    xorb_block_retrieval_urls.push((url, vec![range.bytes]));
}
```

**Chunk Cache Miss → 网络下载**
```rust
if let Some(cache_range) = cache.get(&key, &chunk_range).await? {
    return Ok(Arc::new(XorbBlockData { ... }));
}

// Cache miss - 下载
let permit = client.acquire_download_permit().await?;
let (data, chunk_byte_offsets) = client.get_file_term_data(...).await?;
```

---

## 4. 性能优化

### 4.1 并发控制

**自适应并发控制器（ACC）**
```rust
pub struct AdaptiveConcurrencyController {
    state: Mutex<ConcurrencyControllerState>,
    semaphore: Arc<AdjustableSemaphore>,
    // ...
}
```

**双信号跟踪**

1. **RTT/带宽预测**（在线线性回归）
   - 跟踪 (transmission_size, observed_rtt)
   - 预测公式：`rtt = a + b * size + c * concurrency`

2. **成功率跟踪**（指数加权移动平均）
   - 成功：RTT < 预测 RTT + margin && RTT < 60s
   - 失败：RTT > 90s
   - 成功率 > 0.8 → 增加并发
   - 成功率 < 0.5 → 减少并发

**动态调整**
```rust
if success_ratio > 0.8 && predicted_rtt < target_max_rtt {
    increase_permits();  // +1
} else if success_ratio < 0.5 || observed_rtt > max_tolerated_rtt {
    decrease_permits();  // -1
}
```

**分离的上传/下载控制器**
- `upload_concurrency_controller`: 用于 xorb/shard 上传
- `download_concurrency_controller`: 用于 xorb 下载

### 4.2 内存管理

**下载缓冲区信号量**
```rust
// 全局共享，按活跃下载数动态扩展
let target = base + n * perfile;
let target = target.clamp(base, limit);

// 配置示例
download_buffer_size = "16MB"     // base
download_buffer_perfile_size = "8MB"
download_buffer_limit = "128MB"   // 最大

// 3 个并发下载
target = 16MB + 3 * 8MB = 40MB
```

**虚拟许可（seed permit）**
```rust
// 下载启动时获取虚拟许可，避免等待 FIFO 队列
let seed_permit = semaphore.increment_permits_to_target(target);

// 优先从虚拟许可分割
let permit = seed_permit.split(term_size).unwrap_or_else(|| {
    semaphore.acquire_many(term_size).await?
});
```

**按 term 大小获取许可**
- 每个 file term 根据其解压后大小获取相应字节数的许可
- 写入完成后释放许可
- 防止内存耗尽

### 4.3 预取机制

**ReconstructionTermManager 自适应预取**

**初始化**
```rust
// 预取两个小块快速启动
prefetch_block(min_reconstruction_fetch_size).await?;
prefetch_block(2 * min_reconstruction_fetch_size).await?;
```

**动态调整**
```rust
// 完成速率估算器
let completion_rate = completion_rate_estimator.value();  // bytes/sec

// 目标预取缓冲区
let target_prefetch_buffer = target_completion_time * completion_rate;
let prefetch_buffer_size = max(target_prefetch_buffer, min_prefetch_buffer);

// 下一块大小
let next_block_size = (prefetch_buffer_size - current_buffer_size)
    .clamp(min_fetch_size, max_fetch_size);
```

**配置参数**
- `min_reconstruction_fetch_size`: 最小预取块（默认 100KB）
- `max_reconstruction_fetch_size`: 最大预取块（默认 8MB）
- `min_prefetch_buffer`: 最小预取缓冲区（默认 800KB）
- `target_block_completion_time`: 目标块完成时间（默认 60s）
- `completion_rate_estimator_half_life`: 估算器半衰期（默认 3）

### 4.4 缓存策略

**Chunk Cache 设计原则**
1. **跨文件去重**: 相同 chunk 范围在不同文件间共享
2. **LRU 驱逐**: 随机选择驱逐项（不维护严格 LRU 链表）
3. **异步写入**: 不阻塞下载主流程
4. **容量管理**: 配置最大磁盘使用量

**缓存读取优先级**
```rust
// 1. 尝试缓存
if let Some(cache_range) = cache.get(&key, &chunk_range).await? {
    updater.report_transfer_progress(transfer_bytes);  // 报告"传输"
    return Ok(XorbBlockData { ... });
}

// 2. 网络下载
let permit = client.acquire_download_permit().await?;
let (data, offsets) = client.get_file_term_data(...).await?;

// 3. 异步写入缓存（best-effort）
tokio::spawn(async move {
    cache.put(&key, &chunk_range, &offsets, &data).await?;
});
```

---

## 5. 关键数据结构

### 5.1 Reconstruction 相关类型

**QueryReconstructionResponseV2**
```rust
pub struct QueryReconstructionResponseV2 {
    pub offset_into_first_range: u64,
    pub terms: Vec<XorbReconstructionTerm>,
    pub xorbs: HashMap<HexMerkleHash, Vec<XorbMultiRangeFetch>>,
}

pub struct XorbReconstructionTerm {
    pub hash: HexMerkleHash,
    pub unpacked_length: u32,
    pub range: ChunkRange,  // [start, end)
}

pub struct XorbMultiRangeFetch {
    pub url: String,
    pub ranges: Vec<XorbRangeDescriptor>,
}

pub struct XorbRangeDescriptor {
    pub chunks: ChunkRange,  // [start, end) chunk indices
    pub bytes: HttpRange,    // [start, end] inclusive HTTP range
}
```

### 5.2 Xorb/Chunk 数据结构

**XorbBlock**
```rust
pub struct XorbBlock {
    pub xorb_hash: MerkleHash,
    pub chunk_ranges: Vec<ChunkRange>,  // 支持多个不连续范围
    pub xorb_block_index: usize,
    pub references: Vec<XorbReference>,
    pub uncompressed_size_if_known: Option<usize>,
    pub data: OnceCell<Arc<XorbBlockData>>,  // 单例飞行
}

pub struct XorbBlockData {
    pub chunk_offsets: Vec<(usize, usize)>,  // (chunk_idx, byte_offset)
    pub data: Bytes,                         // 连接的解压数据
}

pub struct XorbReference {
    pub term_chunks: ChunkRange,
    pub uncompressed_size: usize,
}
```

**FileTerm**
```rust
pub struct FileTerm {
    pub byte_range: FileRange,           // 文件中的字节范围
    pub xorb_chunk_range: ChunkRange,   // xorb 中的 chunk 范围
    pub xorb_block_start_index: usize,  // chunk_offsets 中的起始索引
    pub offset_into_first_range: u64,   // 第一个 chunk 内的偏移
    pub xorb_block: Arc<XorbBlock>,
    pub url_info: Arc<TermBlockRetrievalURLs>,
}
```

### 5.3 缓存元数据

**CacheItem**
```rust
pub struct CacheItem {
    pub range: ChunkRange,
    pub len: u64,
    pub checksum: u64,
    pub path: PathBuf,
}

pub struct VerificationCell<T> {
    inner: T,
    // 用于验证缓存完整性
}

// 缓存文件头
pub struct CacheFileHeader {
    pub version: u32,
    pub range: ChunkRange,
    pub data_length: u64,
    pub checksum: u64,
}
```

**CacheState（内存索引）**
```rust
struct CacheState {
    inner: HashMap<Key, Vec<VerificationCell<CacheItem>>>,
    num_items: usize,
    total_bytes: u64,
}
```

---

## 6. 流程时序图

```
用户请求
   │
   ├──> FileDownloadSession::download_file(file_info, path)
   │       │
   │       ├──> FileReconstructor::new(ctx, client, file_hash)
   │       │       .with_byte_range(range)
   │       │       .with_chunk_cache(cache)
   │       │       .reconstruct_to_file(path)
   │       │
   │       └──> FileReconstructor::run()
   │               │
   │               ├──> ReconstructionTermManager::new()
   │               │       ├──> client.get_reconstruction(file_hash, range)
   │               │       │       ├──> [Try V2] GET /v2/reconstructions/{hash}
   │               │       │       └──> [Fallback V1] GET /v1/reconstructions/{hash}
   │               │       │
   │               │       └──> prefetch_block(min_size) × 2  // 初始预取
   │               │
   │               └──> loop {
   │                       ├──> term_manager.next_file_terms()
   │                       │       ├──> retrieve_file_term_block()
   │                       │       │       ├──> parse V2 response
   │                       │       │       ├──> build XorbBlocks (dedup by hash+range)
   │                       │       │       └──> build FileTerms
   │                       │       │
   │                       │       └──> check_prefetch_buffer()
   │                       │               └──> prefetch_block(adaptive_size)
   │                       │
   │                       └──> for each file_term {
   │                               ├──> acquire buffer_permit
   │                               │
   │                               ├──> file_term.get_data_task()
   │                               │       └──> xorb_block.retrieve_data()
   │                               │               ├──> [Try Cache] cache.get(key, range)
   │                               │               │       └──> return cached data
   │                               │               │
   │                               │               └──> [Cache Miss]
   │                               │                       ├──> client.acquire_download_permit()
   │                               │                       │       └──> ACC 并发控制
   │                               │                       │
   │                               │                       ├──> client.get_file_term_data()
   │                               │                       │       ├──> url_provider.retrieve_url()
   │                               │                       │       ├──> HTTP GET with Range header
   │                               │                       │       │       └──> [403] refresh_url()
   │                               │                       │       └──> deserialize_chunks()
   │                               │                       │
   │                               │                       └──> cache.put() [async]
   │                               │
   │                               └──> data_writer.set_next_term_data_source()
   │                           }
   │                   }
   │
   └──> data_writer.finish()
           └──> 写入完成
```

---

## 7. 关键设计亮点

1. **V2 Multi-range 优化**: 减少 presigned URL 数量，降低签名开销
2. **自适应并发控制**: 基于 RTT 和成功率动态调整并发度
3. **单例飞行模式**: XorbBlock 下载去重，避免重复请求
4. **渐进式预取**: 根据完成速率自适应调整预取块大小
5. **动态内存管理**: 按活跃下载数扩展缓冲区，避免 OOM
6. **跨文件去重**: Chunk cache 在文件级别共享
7. **零拷贝设计**: 使用 `Bytes` 共享底层数据
8. **优雅降级**: V2→V1 API、multi-range→single-range
9. **URL 自动刷新**: 403 触发，单例飞行去重刷新请求
10. **进度跟踪**: 分离传输字节和解压字节，精确报告

---

**文档创建日期**: 2026-06-21  
**分析基于**: ~/xet (Rust 原版代码)  
**维护者**: XET+ Team
