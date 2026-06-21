# XET 缓存设计分析：Chunk vs Xorb vs Term

## 三种缓存策略对比

### 1. Chunk-level 缓存（Rust 原版实现）

**实现位置**: `~/xet/xet_client/src/chunk_cache/`

**设计**:
- 缓存粒度: **ChunkRange**（chunk 索引范围）
- 缓存键: `(xorb_hash, chunk_range)`
- 支持部分范围缓存：一个 xorb 可以缓存多个不连续的 chunk 范围

**接口**:
```rust
trait ChunkCache {
    async fn get(&self, key: &Key, range: &ChunkRange) 
        -> Result<Option<CacheRange>>;
    
    async fn put(&self, key: &Key, range: &ChunkRange, 
                 chunk_byte_indices: &[u32], data: &[u8]) 
        -> Result<()>;
}
```

**优点**:
- ✅ **最灵活**: 支持部分范围复用（multipart 场景）
- ✅ **节省空间**: 不同文件可能共享同一 xorb 的不同 chunk 范围
- ✅ **V2 API 友好**: 天然支持多范围合并请求
- ✅ **去重效率高**: 多个文件引用同一 xorb 的不同部分时，每个部分只下载一次

**缺点**:
- ⚠️ **实现复杂**: 需要维护 chunk_offsets 映射
- ⚠️ **查询开销**: 需要检查范围重叠

**适用场景**:
- 大型模型仓库（多个文件共享 xorb）
- V2 多范围 API（一次请求多个不连续范围）
- 生产环境（需要最优缓存复用率）

---

### 2. Xorb-level 缓存（xet.py 实现）

**实现位置**: `~/xet.py/xet/reconstructor.py`

**设计**:
- 缓存粒度: **完整 xorb**（下载后的压缩数据）
- 缓存键: `xorb_hash` + `cache_suffix`（range-aware）
- 一个 xorb 一个缓存文件

**实现**:
```python
def _load_from_disk_cache(xorb_hash, cache_suffix='', min_expected_size=0):
    path = cache_dir / f'{xorb_hash}{cache_suffix}.pkl'
    if path.exists():
        data = pickle.load(path)
        if len(data.data) >= min_expected_size:
            return data
    return None

def _save_to_disk_cache(xorb_hash, data: XorbBlockData, cache_suffix=''):
    path = cache_dir / f'{xorb_hash}{cache_suffix}.pkl'
    pickle.dump(data, path)
```

**优点**:
- ✅ **实现简单**: 直接序列化整个 xorb 数据
- ✅ **查询快速**: 文件名即索引，O(1) 查找
- ✅ **兼容 V1 API**: 每个 xorb 一次请求

**缺点**:
- ❌ **空间浪费**: 多个文件引用同一 xorb 的不同范围时，每个范围都要缓存完整 xorb
- ❌ **不支持部分复用**: multipart 场景无法复用已缓存的部分
- ⚠️ **cache_suffix 复杂**: 需要处理 range-aware 的缓存键

**适用场景**:
- 单文件下载（不共享 xorb）
- V1 API（每个 xorb 一次完整请求）
- 快速原型实现

---

### 3. Term-level 缓存（理论方案，未见实现）

**设计**:
- 缓存粒度: **Reconstruction Term**（文件中的逻辑块）
- 缓存键: `(file_hash, term_index)`
- 每个 term 独立缓存

**优点**:
- ✅ **文件级去重**: 完全相同的文件可以复用所有 term
- ✅ **断点续传友好**: term 是重建的最小单位

**缺点**:
- ❌ **去重率低**: 不同文件很少共享完全相同的 term
- ❌ **缓存碎片**: 大量小文件（每个 term 一个文件）
- ❌ **元数据开销**: 需要维护 file_hash → term 映射
- ❌ **不适合 xorb 共享**: 无法利用多文件共享同一 xorb 的优势

**适用场景**:
- ❌ **不推荐**: 在 XET 架构中几乎没有优势

---

## 推荐方案：分阶段实现

### 阶段 1: Xorb-level 缓存（当前优先）

**原因**:
1. XET+ 当前使用 V1 API（每个 xorb 一次完整请求）
2. 实现简单，快速上线
3. 覆盖 90% 的使用场景（单文件下载）

**实现要点**:
```python
class XorbDiskCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir / "xorbs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get(self, xorb_hash: str, expected_size: int = 0) -> Optional[bytes]:
        """加载缓存的 xorb 数据。"""
        path = self.cache_dir / f"{xorb_hash}.xorb"
        if not path.exists():
            return None
        
        # 验证文件大小（防止部分下载污染）
        if expected_size > 0 and path.stat().st_size < expected_size:
            logger.warning(f"缓存文件不完整，删除: {xorb_hash[:16]}...")
            path.unlink()
            return None
        
        return path.read_bytes()
    
    def put(self, xorb_hash: str, data: bytes) -> None:
        """保存 xorb 到缓存。"""
        path = self.cache_dir / f"{xorb_hash}.xorb"
        path.write_bytes(data)
    
    def cleanup(self, xorb_hashes: List[str]) -> None:
        """清理指定的缓存文件（下载完成后）。"""
        for xorb_hash in xorb_hashes:
            path = self.cache_dir / f"{xorb_hash}.xorb"
            if path.exists():
                path.unlink()
```

**集成点**:
- `DownloadScheduler._download_single_xorb_multipart()`: 下载前检查缓存
- `CASClient.download_xorb_range()`: 下载后保存到缓存

**参数**:
- `--cache-dir`: 缓存目录（默认 `~/.xet/cache`）
- `--keep-cache`: 下载完成后保留缓存（默认 False）
- 分段模式自动禁用缓存（避免冲突）

---

### 阶段 2: Chunk-level 缓存（未来优化）

**时机**: V2 多范围 API 集成后

**原因**:
1. V2 API 支持一次请求多个不连续范围
2. 大型模型仓库需要最优缓存复用
3. 生产环境优化空间利用率

**实现**:
- 参考 Rust 原版 `ChunkCache` trait
- 支持 `get(xorb_hash, chunk_ranges)` 部分范围查询
- 支持 `put(xorb_hash, chunk_ranges, offsets, data)` 部分范围存储

**挑战**:
- 需要维护 chunk → byte offset 映射
- 需要处理范围重叠和合并
- 缓存失效策略更复杂（LRU on chunk level）

---

## 决策建议

### 当前阶段（v0.3.0 → v0.4.0）

✅ **实现 Xorb-level 缓存**

**理由**:
1. 简单快速（1-2 天实现）
2. 覆盖主要场景（单文件下载）
3. 与 xet.py 一致（便于对比测试）
4. 为分段下载提供加速

**不实现 Term-level 缓存**:
- ❌ 在 XET 架构中没有优势
- ❌ 缓存碎片问题严重
- ❌ 无法利用 xorb 共享

---

### 未来优化（v0.5.0+）

🔄 **迁移到 Chunk-level 缓存**

**时机**:
- V2 多范围 API 集成完成
- 大规模用户反馈需要更好的缓存复用

**价值**:
- 多文件下载场景性能提升 30-50%
- 磁盘空间节省 20-40%（大型仓库）
- 与 Rust 原版架构对齐

---

## 总结

| 缓存策略 | 实现复杂度 | 空间效率 | 复用率 | 当前优先级 |
|---------|-----------|---------|--------|-----------|
| **Chunk-level** | 高 | 最优 | 最高 | 🟡 未来 |
| **Xorb-level** | 低 | 中等 | 中等 | ✅ **当前** |
| **Term-level** | 中 | 差 | 低 | ❌ 不推荐 |

**最终建议**: 
1. **v0.3.0**: 实现 Xorb-level 缓存（快速上线）
2. **v0.5.0+**: 迁移到 Chunk-level 缓存（生产优化）
3. **永不实现**: Term-level 缓存（架构不匹配）
