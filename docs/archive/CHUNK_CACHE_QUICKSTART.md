# Chunk 缓存快速启用指南

## 📋 概述

本文档说明如何启用 chunk-level 缓存功能。当前实现已完成核心功能和集成框架，只需简单修改即可启用。

---

## 🔧 启用步骤

### 1. 修改 `download.py` 命令（约 10 行代码）

**文件**: `xet/cli/commands/download.py`

**位置**: `reconstruct_file_pipeline()` 函数

**当前代码** (使用 xorb 缓存):
```python
def reconstruct_file_pipeline(...):
    # 初始化 xorb 缓存
    xorb_cache = None
    if cache_dir and not args.no_cache:
        xorb_cache = XorbDiskCache(
            cache_root=cache_dir,
            capacity_bytes=cache_capacity_bytes
        )
    
    # 创建重建器
    reconstructor = FileReconstructor(
        cas_client=cas_client,
        output_path=output_path,
        xorb_cache=xorb_cache,
        ...
    )
```

**修改后** (启用 chunk 缓存):
```python
def reconstruct_file_pipeline(...):
    # 初始化缓存
    from xet.pipeline.chunk_disk_cache import ChunkDiskCache
    
    xorb_cache = None
    chunk_cache = None
    
    if cache_dir and not args.no_cache:
        # 选项 A: 只使用 chunk 缓存（推荐）
        chunk_cache = ChunkDiskCache(
            cache_root=cache_dir / "chunks",
            capacity_bytes=cache_capacity_bytes
        )
        
        # 选项 B: 同时使用 xorb + chunk 缓存（渐进迁移）
        # xorb_cache = XorbDiskCache(
        #     cache_root=cache_dir / "xorbs",
        #     capacity_bytes=cache_capacity_bytes // 2
        # )
        # chunk_cache = ChunkDiskCache(
        #     cache_root=cache_dir / "chunks",
        #     capacity_bytes=cache_capacity_bytes // 2
        # )
    
    # 创建重建器（保持向后兼容）
    reconstructor = FileReconstructor(
        cas_client=cas_client,
        output_path=output_path,
        xorb_cache=xorb_cache,
        chunk_cache=chunk_cache,  # ← 新增参数
        ...
    )
```

### 2. 修改 `FileReconstructor` 构造函数

**文件**: `xet/pipeline/file_reconstructor.py`

**添加参数**:
```python
def __init__(
    self,
    cas_client: CASClient,
    output_path: Path,
    temp_dir: Optional[Path] = None,
    checkpoint_path: Optional[Path] = None,
    max_workers: int = 4,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    stop_event: Optional[threading.Event] = None,
    xorb_cache: Optional[XorbDiskCache] = None,
    chunk_cache: Optional[ChunkDiskCache] = None,  # ← 新增
    max_memory_mb: int = 200,
    prefetch_low_mb: int = 48,
    prefetch_high_mb: int = 192,
):
    self.cas_client = cas_client
    self.output_path = output_path
    self.temp_dir = temp_dir or Path.cwd() / ".xet_temp"
    self._stop_event = stop_event or threading.Event()
    self.xorb_cache = xorb_cache
    self.chunk_cache = chunk_cache  # ← 新增
    ...
```

### 3. 修改 `ChunkAssembler` 调用

**文件**: `xet/pipeline/file_reconstructor.py`

**修改 `reconstruct_file()` 方法**:
```python
def reconstruct_file(self, file_hash: str, expected_size: int = 0, resume: bool = True):
    ...
    # 创建缓存适配器
    from xet.pipeline.chunk_cache_adapter import ChunkCacheAdapter
    cache_adapter = ChunkCacheAdapter(
        chunk_cache=self.chunk_cache,  # ← 传入 chunk 缓存
        xorb_cache=self.xorb_cache
    )
    
    # 组装文件
    self.assembler.assemble_file_with_prefetch(
        recon=recon,
        cas_client=self.cas_client,
        output_path=self.output_path,
        file_hash=file_hash,
        progress_tracker=self.progress_tracker,
        cache_adapter=cache_adapter,  # ← 传入适配器
        stop_event=self._stop_event,
    )
```

### 4. 修改 `ChunkAssembler.assemble_file_with_prefetch()`

**文件**: `xet/pipeline/chunk_assembler.py`

**当前代码**:
```python
def assemble_file_with_prefetch(
    self,
    recon: QueryReconstructionResponse,
    cas_client,
    output_path: Path,
    file_hash: str,
    progress_tracker: Optional[ProgressTracker] = None,
    xorb_cache: Optional[XorbDiskCache] = None,
    stop_event: Optional[threading.Event] = None,
):
    ...
    # 创建缓存适配器（暂时只使用 xorb 缓存）
    cache_adapter = ChunkCacheAdapter(
        chunk_cache=None,  # TODO: 后续集成 chunk 缓存
        xorb_cache=xorb_cache
    )
```

**修改后**:
```python
def assemble_file_with_prefetch(
    self,
    recon: QueryReconstructionResponse,
    cas_client,
    output_path: Path,
    file_hash: str,
    progress_tracker: Optional[ProgressTracker] = None,
    cache_adapter: Optional[ChunkCacheAdapter] = None,  # ← 改为接受适配器
    stop_event: Optional[threading.Event] = None,
):
    ...
    # 不再在这里创建适配器，由调用方传入
```

---

## 🧪 测试启用

### 快速测试
```bash
# 1. 启用 chunk 缓存下载文件
python -m xet.cli.commands.download user/repo/model.gguf \
    --cache-dir /tmp/test_cache

# 2. 验证缓存目录结构
ls -R /tmp/test_cache/chunks/

# 3. 再次下载相同文件（应该从缓存命中）
python -m xet.cli.commands.download user/repo/model.gguf \
    --cache-dir /tmp/test_cache

# 4. 下载共享 xorb 的其他文件（验证部分范围命中）
python -m xet.cli.commands.download user/repo/model2.gguf \
    --cache-dir /tmp/test_cache
```

### 性能对比测试
```bash
# 对比 xorb vs chunk 缓存性能
# 场景：下载多个共享 xorb 的文件

# 测试 1: xorb 缓存（旧）
rm -rf /tmp/cache_xorb
time python -m xet.cli.commands.download user/repo/fileA.bin --cache-dir /tmp/cache_xorb
time python -m xet.cli.commands.download user/repo/fileB.bin --cache-dir /tmp/cache_xorb
du -sh /tmp/cache_xorb

# 测试 2: chunk 缓存（新）
rm -rf /tmp/cache_chunk
time python -m xet.cli.commands.download user/repo/fileA.bin --cache-dir /tmp/cache_chunk
time python -m xet.cli.commands.download user/repo/fileB.bin --cache-dir /tmp/cache_chunk
du -sh /tmp/cache_chunk

# 比较：
# - 第二次下载时间（缓存命中率）
# - 磁盘空间占用（去重效果）
```

---

## 📊 预期效果

### 缓存命中日志
启用后，日志中会出现：
```
[CacheAdapter] Chunk-level 缓存已启用
[CacheAdapter] Chunk 缓存命中: abc123... 范围 ChunkRange(0, 100)
[CacheAdapter] 写入 chunk 缓存: abc123... 范围 ChunkRange(0, 100), 5.2MB
[Cache] 从磁盘加载 3 个 xorb (15.6MB)
```

### 缓存文件结构
```
~/.xet/cache/chunks/
├── ab/                         # prefix
│   └── YWJjMTIzNDU2Nzg5/      # xorb_hash (base64)
│       ├── AAAAAAAAAAB...     # range [0,100), 1MB, checksum
│       └── AABAAAAAAAAB...    # range [100,200), 0.8MB, checksum
└── cd/
    └── Y2QxMjM0NTY3ODk/
        └── AAAAAAAAAAB...
```

---

## 🔍 调试技巧

### 1. 启用详细日志
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 检查缓存统计
```python
cache = ChunkDiskCache(cache_root, capacity)
print(f"Total cached: {cache._total_bytes / 1024 / 1024:.1f}MB")
print(f"Number of xorbs: {len(cache._state)}")
for xorb_hash, items in cache._state.items():
    print(f"  {xorb_hash[:16]}... : {len(items)} ranges")
```

### 3. 手动清理缓存
```bash
# 清理 chunk 缓存
rm -rf ~/.xet/cache/chunks/

# 只清理特定 xorb
rm -rf ~/.xet/cache/chunks/ab/YWJj*/
```

---

## ⚠️ 注意事项

### 向后兼容性
- 新旧缓存目录不兼容：`xorbs/` vs `chunks/`
- 建议：启用 chunk 缓存时清理旧的 xorb 缓存
- 适配器支持两种缓存并存（渐进迁移）

### 磁盘空间
- Chunk 缓存可能比 xorb 缓存占用**更多**短期空间
- 原因：缓存多个部分范围 vs 完整 xorb
- 长期：通过去重节省空间（多文件场景）

### 性能权衡
- 单文件下载：chunk 缓存略慢（多一次 header 解析）
- 多文件下载：chunk 缓存更快（部分范围复用）
- 推荐：大规模下载场景启用

---

## 📝 TODO 清单

在启用前，确保：
- [ ] 运行单元测试：`pytest tests/test_chunk_disk_cache.py -v`
- [ ] 添加命令行参数：`--chunk-cache` / `--no-chunk-cache`
- [ ] 更新用户文档
- [ ] 准备性能对比数据
- [ ] 准备回滚方案（如果出现问题）

---

## 🆘 故障排查

### 问题 1: 缓存未命中率高
**可能原因**: chunk 范围不匹配  
**解决方案**: 检查 `fetch_info` 的 chunk_range 是否正确

### 问题 2: 磁盘空间增长过快
**可能原因**: 驱逐策略不生效  
**解决方案**: 检查 `capacity_bytes` 设置，验证驱逐逻辑

### 问题 3: CRC32 校验失败
**可能原因**: 数据损坏或并发写入  
**解决方案**: 检查文件系统完整性，确认线程安全

### 问题 4: 导入错误
**可能原因**: 循环导入  
**解决方案**: 使用 `TYPE_CHECKING` 和字符串类型注解

---

**编写日期**: 2026-06-21  
**适用版本**: v0.5.0+  
**维护者**: XET+ Team
