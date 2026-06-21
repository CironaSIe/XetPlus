# Chunk-Level 缓存重构计划

## 📋 概述

将 XET+ 的缓存机制从 **Xorb-level**（整个 xorb 文件）重构为 **Chunk-level**（chunk 范围粒度），对齐 Rust 原版实现，实现更高效的缓存复用和空间节省。

---

## 🔍 Rust 实现分析

### 1. 核心数据结构

#### CacheRange (返回值)
```rust
pub struct CacheRange {
    pub offsets: Vec<u32>,      // chunk → byte 偏移映射 (长度 = num_chunks + 1)
    pub data: Vec<u8>,          // 解压后的数据
    pub range: ChunkRange,      // 覆盖的 chunk 范围 [start, end)
}
```

#### CacheItem (元数据)
```rust
struct CacheItem {
    range: ChunkRange,          // chunk 范围 [start, end)
    len: u64,                   // 文件大小（header + data）
    checksum: u32,              // CRC32 校验和
}
```

#### ChunkRange (范围表示)
```rust
pub type ChunkRange = Range<u32, _C>;  // [start, end) 左闭右开
```

### 2. ChunkCache Trait 接口

```rust
#[async_trait]
pub trait ChunkCache {
    async fn get(&self, key: &Key, range: &ChunkRange) 
        -> Result<Option<CacheRange>, ChunkCacheError>;
    
    async fn put(&self, key: &Key, range: &ChunkRange, 
                 chunk_byte_indices: &[u32], data: &[u8])
        -> Result<(), ChunkCacheError>;
}
```

**关键约束**:
- `chunk_byte_indices.len() == range.end - range.start + 1`
- `chunk_byte_indices[0] == 0` (第一个 chunk 从 0 开始)
- `chunk_byte_indices.last() == data.len()` (最后一个索引 = 数据末尾)
- 索引严格递增

### 3. 文件布局

```
cache_root/
├── [ab]/                           # 前缀目录（key 的前 2 个字符）
│   ├── [key1_base64]/              # xorb hash (base64 编码)
│   │   ├── [0-100_16777216_12345]  # range_start-range_end_len_checksum (base64)
│   │   ├── [102-300_8388608_67890]
│   │   └── [900-1024_4194304_11111]
│   └── [key2_base64]/
│       └── [0-1020_33554432_22222]
├── [cd]/
│   └── [key3_base64]/
│       ├── [30-31_1048576_33333]
│       └── [400-405_2097152_44444]
```

**文件名编码**:
- Base64(range_start || range_end || len || checksum)
- 所有数字小端序 u32/u64

**文件内容**:
```
[Header]
  u32: chunk_byte_indices.len()
  u32[]: chunk_byte_indices (每个 chunk 的起始字节偏移)
[Data]
  bytes: 解压后的 chunk 数据
```

### 4. 缓存查找逻辑

```rust
fn find_match(&self, key: &Key, range: &ChunkRange) -> Option<CacheItem> {
    let items = self.inner.get(key)?;
    for item in items.iter() {
        // 查找包含请求范围的缓存项
        if item.range.start <= range.start && range.end <= item.range.end {
            return Some(item.clone());
        }
    }
    None
}
```

**特性**:
- 支持**部分范围命中**：缓存 [0, 100) 可以满足请求 [10, 50)
- 一个 key 可以有**多个 CacheItem**（不同的 chunk 范围）
- 查找时返回第一个包含请求范围的项

### 5. 驱逐策略

```rust
fn evict_to_capacity(&mut self, max_total_bytes: u64) -> Result<Vec<...>> {
    while self.total_bytes > max_total_bytes {
        let (key, idx) = self.random_item()?;  // 随机选择一个 item
        let items = self.inner.get_mut(&key)?;
        let cache_item = items.swap_remove(idx);
        // 更新统计 + 删除文件
    }
}
```

**特性**:
- **随机驱逐**（Rust 实现），非 LRU
- 按 item 粒度驱逐（不是按 key）
- 如果 key 下所有 item 都被驱逐，则删除 key 目录

---

## 🎯 Python 设计方案

### 1. 新增数据结构

#### `xet/pipeline/chunk_disk_cache.py`

```python
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

@dataclass
class ChunkRange:
    """Chunk 范围 [start, end) 左闭右开"""
    start: int  # u32
    end: int    # u32
    
    def contains(self, other: "ChunkRange") -> bool:
        """检查是否包含另一个范围"""
        return self.start <= other.start and other.end <= self.end
    
    def length(self) -> int:
        return self.end - self.start

@dataclass
class CacheRange:
    """缓存查询返回值"""
    offsets: List[int]      # chunk → byte 偏移映射 (u32)
    data: bytes             # 解压后的数据
    range: ChunkRange       # 覆盖的 chunk 范围

@dataclass
class CacheItem:
    """缓存项元数据（文件名编码）"""
    range: ChunkRange
    len: int                # u64: 文件大小（header + data）
    checksum: int           # u32: CRC32 校验和
    
    def file_name(self) -> str:
        """编码为 base64 文件名"""
        # pack: range.start, range.end, len, checksum
        # base64 编码
        pass
    
    @classmethod
    def parse(cls, file_name: str) -> "CacheItem":
        """从文件名解码"""
        pass

class ChunkDiskCache:
    """Chunk-level 磁盘缓存"""
    
    def __init__(self, cache_root: Path, capacity_bytes: int):
        self.cache_root = cache_root
        self.capacity = capacity_bytes
        self.enabled = capacity_bytes > 0
        
        # 内存索引: {xorb_hash: [CacheItem, ...]}
        self._state: Dict[str, List[CacheItem]] = {}
        self._total_bytes = 0
        self._lock = threading.Lock()
    
    def get(self, xorb_hash: str, chunk_range: ChunkRange) 
            -> Optional[CacheRange]:
        """查询缓存（支持部分范围命中）"""
        pass
    
    def put(self, xorb_hash: str, chunk_range: ChunkRange,
            chunk_byte_indices: List[int], data: bytes) -> None:
        """写入缓存"""
        pass
    
    def _find_match(self, xorb_hash: str, chunk_range: ChunkRange) 
            -> Optional[CacheItem]:
        """查找包含请求范围的缓存项"""
        pass
    
    def _evict_to_capacity(self, required_bytes: int) -> None:
        """驱逐缓存项直到有足够空间"""
        pass
```

### 2. 修改 XorbDeserializer

#### `xet/storage/xorb_deserializer.py`

```python
class XorbBlockData:
    """解压后的 xorb 数据"""
    chunk_offsets: List[Tuple[int, int]]  # [(chunk_idx, byte_offset), ...]
    data: bytes
    
    # 新增：提取 chunk_byte_indices 用于缓存
    def get_chunk_byte_indices(self) -> List[int]:
        """返回 [0, offset1, offset2, ..., len(data)]"""
        indices = [0]
        for _, byte_offset in sorted(self.chunk_offsets):
            indices.append(byte_offset)
        if indices[-1] != len(self.data):
            indices.append(len(self.data))
        return indices

class XorbDeserializer:
    @staticmethod
    def deserialize(merged_data: bytes, chunk_ranges: List[ChunkRange]) 
            -> XorbBlockData:
        """解压 xorb，返回数据 + chunk 偏移"""
        # 现有逻辑 + 新增 chunk_ranges 参数
        pass
```

### 3. 重构 ChunkAssembler

#### `xet/pipeline/chunk_assembler_helpers.py`

```python
def _download_xorb_sync(
    self,
    xorb_hash: str,
    fetch_infos: list,
    cas_client,
    file_hash: str,
    progress_tracker=None,
    chunk_cache: Optional[ChunkDiskCache] = None,
) -> Tuple[bytes, List[int]]:
    """下载 xorb，返回 (压缩数据, chunk_byte_indices)"""
    
    # 1. 计算需要的 chunk 范围
    chunk_ranges = [fi.chunk_range for fi in fetch_infos]
    merged_range = ChunkRange(
        start=min(cr.start for cr in chunk_ranges),
        end=max(cr.end for cr in chunk_ranges)
    )
    
    # 2. 尝试从 chunk 缓存读取
    if chunk_cache and chunk_cache.enabled:
        cache_hit = chunk_cache.get(xorb_hash, merged_range)
        if cache_hit:
            logger.debug(f"[Cache] Chunk 缓存命中: {xorb_hash[:16]}...")
            # 返回空压缩数据（因为已经解压了）+ chunk_byte_indices
            return (b"", cache_hit.offsets)
    
    # 3. 缓存未命中，下载所有 segments
    if progress_tracker:
        progress_tracker.start_xorb_download(xorb_hash)
    
    segments = []
    for fi in sorted(fetch_infos, key=lambda x: x.chunk_range.start):
        segment_data = cas_client.get_xorb_data(...)
        segments.append(segment_data)
        if progress_tracker:
            progress_tracker.increment_segments(1)
    
    compressed_data = b''.join(segments)
    
    # 4. 解压并提取 chunk_byte_indices
    from xet.storage.xorb_deserializer import XorbDeserializer
    xorb_data = XorbDeserializer.deserialize(compressed_data, chunk_ranges)
    chunk_byte_indices = xorb_data.get_chunk_byte_indices()
    
    # 5. 写入 chunk 缓存
    if chunk_cache and chunk_cache.enabled:
        chunk_cache.put(xorb_hash, merged_range, chunk_byte_indices, xorb_data.data)
    
    if progress_tracker:
        progress_tracker.complete_xorb_download(xorb_hash)
    
    return (compressed_data, chunk_byte_indices)
```

---

## 🔧 修改清单

### Phase 1: 新增核心组件

1. **创建 `xet/pipeline/chunk_disk_cache.py`**
   - `ChunkRange` 类
   - `CacheRange` 类
   - `CacheItem` 类
   - `ChunkDiskCache` 类

2. **修改 `xet/storage/xorb_deserializer.py`**
   - `XorbBlockData.get_chunk_byte_indices()` 方法
   - `XorbDeserializer.deserialize()` 增加 `chunk_ranges` 参数

### Phase 2: 重构缓存调用

3. **修改 `xet/pipeline/chunk_assembler_helpers.py`**
   - `_download_xorb_sync()` 支持 chunk 缓存
   - 返回 `(compressed_data, chunk_byte_indices)`

4. **修改 `xet/pipeline/chunk_assembler.py`**
   - `_ensure_xorb_ready()` 处理缓存命中情况
   - `_load_from_disk_cache()` 使用 chunk 缓存

5. **修改 `xet/pipeline/file_reconstructor.py`**
   - 传递 `ChunkDiskCache` 而不是 `XorbDiskCache`

### Phase 3: 命令行集成

6. **修改 `xet/cli/commands/download.py`**
   - 用 `ChunkDiskCache` 替换 `XorbDiskCache`
   - 保留 `--cache-dir`, `--keep-cache`, `--no-cache` 参数

### Phase 4: 清理旧代码

7. **移除 `xet/pipeline/xorb_disk_cache.py`**（或标记为 deprecated）

---

## ⚡ 性能优化点

### 1. 部分范围复用
- **场景**: 文件 A 需要 xorb1[0, 100)，文件 B 需要 xorb1[50, 150)
- **旧实现**: 两次完整下载 xorb1
- **新实现**: 
  - 文件 A 下载 [0, 100) 并缓存
  - 文件 B 只需下载 [100, 150)，复用缓存的 [50, 100)

### 2. 多文件共享
- **场景**: 10 个文件引用同一 xorb 的不同部分
- **旧实现**: 每个文件独立缓存完整 xorb → 10x 空间
- **新实现**: 每个 chunk 范围只缓存一次 → 去重

### 3. 节省磁盘空间
- **估算**: 大型仓库多文件下载场景
- **预期**: 磁盘空间节省 **20-40%**
- **原因**: chunk 级别去重 + 不缓存不需要的部分

---

## 🧪 测试计划

### 单元测试 (`tests/test_chunk_disk_cache.py`)

```python
def test_cache_hit():
    """测试缓存命中"""
    cache = ChunkDiskCache(temp_dir, 100 * 1024 * 1024)
    
    # 写入 [0, 100)
    cache.put("xorb1", ChunkRange(0, 100), indices, data)
    
    # 查询 [0, 100) → 完全命中
    result = cache.get("xorb1", ChunkRange(0, 100))
    assert result is not None
    
def test_partial_range_hit():
    """测试部分范围命中"""
    cache.put("xorb1", ChunkRange(0, 100), indices, data)
    
    # 查询 [10, 50) → 部分命中（缓存覆盖）
    result = cache.get("xorb1", ChunkRange(10, 50))
    assert result is not None
    assert result.range.start == 0  # 返回缓存的完整范围
    assert result.range.end == 100
    
def test_cache_miss():
    """测试缓存未命中"""
    cache.put("xorb1", ChunkRange(0, 100), indices, data)
    
    # 查询 [150, 200) → 未命中
    result = cache.get("xorb1", ChunkRange(150, 200))
    assert result is None
    
def test_eviction():
    """测试缓存驱逐"""
    cache = ChunkDiskCache(temp_dir, 10 * 1024)  # 10KB 限制
    
    # 写入 20KB 数据
    cache.put("xorb1", ChunkRange(0, 100), indices1, data1)  # 15KB
    cache.put("xorb2", ChunkRange(0, 50), indices2, data2)   # 8KB
    
    # 应该驱逐一些项
    assert cache._total_bytes <= 10 * 1024
```

### 集成测试

```bash
# 1. 下载文件 A，填充缓存
xet download user/repo/fileA.bin --cache-dir /tmp/chunk_cache

# 2. 下载文件 B（共享 xorb），验证缓存复用
xet download user/repo/fileB.bin --cache-dir /tmp/chunk_cache

# 3. 检查缓存大小 < 两个文件的 xorb 总和
```

---

## 📊 预期收益

| 指标 | Xorb-level | Chunk-level | 提升 |
|------|-----------|-------------|------|
| **多文件下载性能** | 基准 | +30-50% | ⬆️ |
| **磁盘空间占用** | 基准 | -20-40% | ⬇️ |
| **部分范围复用** | ❌ | ✅ | ✨ |
| **架构对齐** | ❌ | ✅ Rust 原版 | 🎯 |

---

## ⚠️ 兼容性注意

### 1. 缓存目录不兼容
- **旧**: `~/.xet/cache/xorbs/{xorb_hash}.xorb`
- **新**: `~/.xet/cache/chunks/{prefix}/{xorb_hash}/{range_len_checksum}`

**解决方案**: 
- 重构时自动清理旧缓存目录
- 或：保留旧缓存，用 `--cache-version 2` 切换

### 2. 断点续传兼容
- Checkpoint 机制不受影响（记录的是 xorb hash，不涉及缓存格式）

### 3. 性能回归风险
- **单文件下载**: chunk 缓存可能略慢（多一次 header 解析）
- **缓解**: 增加缓存验证的快速路径（CRC32 校验缓存）

---

## 🚀 实施顺序

1. ✅ **分析 Rust 实现**（当前任务）
2. 📝 **设计 Python 接口**（Task #11）
3. 🔧 **实现 ChunkDiskCache**（Phase 1）
4. 🔄 **重构下载流程**（Phase 2）
5. 🔗 **集成到命令行**（Phase 3）
6. 🧪 **测试验证**（Task #13）
7. 📚 **更新文档**

---

**预计工作量**: 2-3 天
**优先级**: v0.5.0 特性
**依赖**: 当前 v0.4.1 所有功能稳定运行
