# 并行写入设计分析 - xet.py vs Rust vs xetplus

## 📋 背景

**目标**: 实现 `--parallel-write` 功能，支持多段并行写入同一文件，提升大文件下载性能 2-3 倍。

**参考实现**:
1. **xet.py** (Python): `StreamFileReconstructor._writer_parallel()`
2. **Rust**: `SequentialWriter` (顺序写) 和 `UnorderedWriter` (乱序写)

---

## 🔍 xet.py 的实现分析

### 核心实现：`_writer_parallel()` 

**文件**: `~/xet.py/xet/reconstructor.py:1208-1246`

**设计思路**:
```python
def _writer_parallel(self):
    """并行批量写盘模式 - 批量 seek 写入后统一 fsync。"""
    batch = []
    BATCH_SIZE = self.config.get_effective_concurrency()
    
    with _open_file_shared_write(str(self._target_path)) as f:
        while True:
            item = self._write_queue.get(timeout=30)
            
            if item is None:  # 结束标志
                if batch:
                    for offset, data in batch:
                        f.seek(offset)
                        f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                break
            
            batch.append(item)
            
            if len(batch) >= BATCH_SIZE:
                for offset, data in batch:
                    f.seek(offset)
                    f.write(data)
                f.flush()
                os.fsync(f.fileno())
                batch = []
```

### 关键技术点

#### 1. **共享文件句柄** - `_open_file_shared_write()`

**Windows 特殊处理**:
```python
if os.name == 'nt':
    # 使用 CreateFileW 打开，关键标志：FILE_SHARE_READ | FILE_SHARE_WRITE
    handle = ctypes.windll.kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,  # 🔑 允许其他线程读写
        None, OPEN_ALWAYS, 0, None
    )
    fd = msvcrt.open_osfhandle(handle, os.O_RDWR)
    return open(fd, 'r+b')
else:
    # Linux/macOS: 标准 open() 默认允许多进程/线程共享读写
    return open(path, 'r+b')
```

**问题背景**:
- Windows 上标准 `open('r+b')` 获取独占锁
- 并行模式下多个 writer 线程会阻塞在 `open()` 上
- 导致写队列填满，下载线程阻塞，进度停滞

**解决方案**:
- 使用 `CreateFileW` + `FILE_SHARE_WRITE` 允许多线程同时持有文件句柄
- Linux/macOS 无此问题，标准 `open()` 即可

#### 2. **批量 seek + write**

**优势**:
- 减少系统调用次数
- 批量 fsync，减少磁盘同步开销
- BATCH_SIZE = 并发数，自适应调整

**流程**:
1. 从队列获取 (offset, data) 元组
2. 累积到 batch
3. 达到 BATCH_SIZE 后，批量写入
4. 统一 flush + fsync

#### 3. **写队列** - `self._write_queue`

**特点**:
- 生产者：多个 term 处理线程，按顺序放入 (offset, data)
- 消费者：单个 writer 线程，批量取出并写入
- 解耦下载/解压和磁盘写入

---

## 🦀 Rust 的实现分析

### 1. SequentialWriter（顺序写）

**文件**: `~/xet/xet_data/src/file_reconstruction/data_writer/sequential_writer.rs`

**设计思路**:
```rust
// 使用 write_vectored() 批量写入
fn run_vectorized(mut self, mut writer: impl Write) -> Result<()> {
    let mut pending_writes: VecDeque<PendingWrite> = VecDeque::new();
    
    while !self.finished || !pending_writes.is_empty() {
        // 1. 非阻塞获取更多数据
        while let Some(write) = self.next_write(false)? {
            pending_writes.push_back(write);
        }
        
        // 2. 构建 IoSlice 向量（最多 24 个，避免 writev 限制）
        let io_slices: Vec<IoSlice<'_>> = pending_writes
            .iter()
            .take(WRITEV_MAX_SLICE)
            .map(|(data, _)| IoSlice::new(data))
            .collect();
        
        // 3. 批量写入
        let written = writer.write_vectored(&io_slices)?;
        
        // 4. 更新进度，释放已完成的 permit
        self.bytes_written.fetch_add(written as u64, Ordering::Relaxed);
        
        // 5. 处理部分写入（slice 剩余数据）
        // ...
    }
    
    writer.flush()?;
    Ok(())
}
```

**关键技术**:
- **write_vectored()**: 系统调用 `writev()`，一次写入多个缓冲区
- **WRITEV_MAX_SLICE = 24**: 避免超过系统限制（Linux IOV_MAX = 1024）
- **permit 管理**: 每个数据块关联一个 permit，写入完成后释放（背压控制）

**优势**:
- 零拷贝：直接传递多个缓冲区指针给内核
- 减少系统调用：一次 `writev()` 替代多次 `write()`
- 自动处理部分写入

### 2. UnorderedWriter（乱序写）

**文件**: `~/xet/xet_data/src/file_reconstruction/data_writer/unordered_writer.rs`

**设计思路**:
```rust
pub struct UnorderedWriter {
    result_tx: UnboundedSender<Result<CompletedTerm>>,
    task_set: JoinSet<Result<u64>>,
    // ...
}

async fn set_next_term_data_source(
    &mut self,
    byte_range: FileRange,
    permit: Option<AdjustableSemaphorePermit>,
    data_future: DataFuture,
) -> Result<()> {
    // 1. 增加进度计数
    self.progress.terms_in_progress.fetch_add(1, Ordering::Relaxed);
    self.progress.bytes_in_progress.fetch_add(expected_size, Ordering::Relaxed);
    
    // 2. 异步任务：等待 data_future 完成
    self.task_set.spawn(async move {
        let data = data_future.await?;
        
        // 3. 发送到结果通道（乱序）
        result_tx.send(Ok(CompletedTerm {
            byte_range,
            data,
            permit,
        }))?;
        
        // 4. 减少进度计数
        progress.terms_in_progress.fetch_sub(1, Ordering::Release);
        
        Ok(data.len() as u64)
    });
    
    Ok(())
}
```

**特点**:
- **乱序交付**: term 完成顺序可能与提交顺序不同
- **无阻塞**: 不等待前面的 term
- **配合 UnorderedDownloadStream**: 消费者负责排序和 seek 写入

**适用场景**:
- 多段并行下载（segment-based reconstruction）
- 每段独立写入不同文件位置
- 需要消费者实现顺序保证

---

## 🎯 xetplus 当前架构分析

### 现有组件

**文件**: `xet/pipeline/chunk_assembler.py`

**当前流程**:
```python
def assemble_file_with_prefetch(self, ...):
    # 按 term 顺序处理
    with open(part_path, 'wb') as f:
        for term_idx, term in enumerate(recon.terms):
            # 1. 确保 xorb 已解压到内存
            self._ensure_xorb_ready(term.hash, ...)
            
            # 2. 从内存提取数据
            xorb_data = self._xorb_cache[term.hash]
            segment = xorb_data.data[start_byte:end_byte]
            
            # 3. 顺序写入
            f.write(segment)
            total_written += len(segment)
            
            # 4. 更新进度
            progress_tracker.increment_assembled(len(segment))
```

**特点**:
- ✅ 顺序写入，简单可靠
- ✅ 预取机制避免内存溢出
- ❌ 单线程写入，无法利用 SSD 并行写性能
- ❌ 每个 term 一次 `write()` 调用，系统调用频繁

### 性能瓶颈

**测试场景**: 89MB 文件（17 terms）
- 当前速度: ~3.5 MB/s（写入受限）
- 预期提升: 2-3x（并行写 + 批量 fsync）

**瓶颈分析**:
1. **频繁系统调用**: 17 次 `write()` → 可优化为 1-2 次批量写入
2. **单线程写入**: 无法利用 SSD 多队列并行写
3. **fsync 开销**: 每次 term 写入后隐式 flush

---

## 💡 xetplus 并行写入设计方案

### 方案选择：混合模式

**借鉴 xet.py**: 批量 seek + write + 共享文件句柄  
**借鉴 Rust**: write_vectored 思想（Python 无直接支持，但可模拟）

### 核心设计

#### 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    ChunkAssembler                            │
│  (主线程，按 term 顺序处理)                                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (offset, data) 元组
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                  WriteQueue (queue.Queue)                    │
│  - 多生产者（未来可扩展为多段并行）                          │
│  - 单消费者（GlobalWriter 线程）                             │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│             GlobalWriter (单独线程)                          │
│  1. 批量获取 write items                                     │
│  2. 按 offset 排序                                           │
│  3. 批量 seek + write                                        │
│  4. 统一 fsync                                               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
                  目标文件 (.part)
```

#### 新建文件：`xet/pipeline/global_writer.py`

```python
import os
import queue
import threading
import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

class GlobalWriter:
    """并行批量写入器 - 支持多段并行写入同一文件。
    
    设计思路：
    1. 单独线程消费写队列
    2. 批量获取 (offset, data) 元组
    3. 按 offset 排序后批量写入
    4. 减少系统调用和 fsync 次数
    
    Windows 兼容性：
    - 使用 CreateFileW + FILE_SHARE_WRITE 允许多线程写入
    - Linux/macOS 使用标准 open()
    
    参考：
    - xet.py: StreamFileReconstructor._writer_parallel()
    - Rust: SequentialWriter.run_vectorized()
    """
    
    def __init__(
        self,
        output_path: Path,
        batch_size: int = 8,
        progress_callback: Optional[Callable[[int], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        """初始化 GlobalWriter。
        
        Args:
            output_path: 输出文件路径
            batch_size: 批量写入大小（默认 8）
            progress_callback: 进度回调函数
            stop_event: 停止信号
        """
        self.output_path = output_path
        self.batch_size = batch_size
        self.progress_callback = progress_callback
        self.stop_event = stop_event or threading.Event()
        
        # 写队列：(offset, data) 元组
        self._write_queue = queue.Queue(maxsize=batch_size * 2)
        
        # Writer 线程
        self._writer_thread = None
        self._writer_exception = None
        self._bytes_written = 0
        
    def start(self):
        """启动 writer 线程。"""
        if self._writer_thread is not None:
            raise RuntimeError("GlobalWriter 已启动")
        
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="GlobalWriter",
            daemon=True,
        )
        self._writer_thread.start()
        logger.debug(f"[GlobalWriter] 线程已启动: {self.output_path}")
    
    def put(self, offset: int, data: bytes, timeout: float = 10.0):
        """放入写队列（阻塞）。
        
        Args:
            offset: 文件偏移量
            data: 数据内容
            timeout: 超时时间（秒）
        
        Raises:
            RuntimeError: writer 线程异常
            queue.Full: 队列已满
        """
        # 检查 writer 线程是否异常
        if self._writer_exception is not None:
            raise RuntimeError(f"GlobalWriter 线程异常: {self._writer_exception}")
        
        self._write_queue.put((offset, data), timeout=timeout)
    
    def finish(self, timeout: float = 60.0) -> int:
        """完成写入，等待线程结束。
        
        Args:
            timeout: 等待超时（秒）
        
        Returns:
            已写入字节数
        
        Raises:
            RuntimeError: writer 线程异常
            TimeoutError: 等待超时
        """
        # 发送结束标志
        self._write_queue.put(None)
        
        # 等待线程结束
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=timeout)
            if self._writer_thread.is_alive():
                raise TimeoutError(f"GlobalWriter 线程等待超时: {timeout}s")
        
        # 检查异常
        if self._writer_exception is not None:
            raise RuntimeError(f"GlobalWriter 线程异常: {self._writer_exception}")
        
        logger.info(
            f"[GlobalWriter] 写入完成: {self.output_path}, "
            f"{self._bytes_written} bytes"
        )
        
        return self._bytes_written
    
    def _open_file_shared_write(self, path: str):
        """以允许并发读写的模式打开文件（Windows 兼容）。
        
        参考：xet.py/xet/reconstructor.py:_open_file_shared_write()
        """
        if os.name == 'nt':
            import ctypes
            import msvcrt
            
            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_ALWAYS = 4
            INVALID_HANDLE_VALUE = -1
            
            # 使用 CreateFileW（支持中文路径）
            handle = ctypes.windll.kernel32.CreateFileW(
                path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,  # 🔑 关键
                None, OPEN_ALWAYS, 0, None
            )
            
            if handle == INVALID_HANDLE_VALUE or (handle & 0xFFFFFFFF) == 0xFFFFFFFF:
                error = ctypes.GetLastError()
                raise OSError(f"CreateFileW 失败 (error={error}): {path}")
            
            # 转换为 Python file object
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR)
            return open(fd, 'r+b', buffering=0)  # 无缓冲
        else:
            # Linux/macOS: 标准 open()
            return open(path, 'r+b', buffering=0)
    
    def _writer_loop(self):
        """Writer 线程主循环（批量写入模式）。"""
        try:
            batch = []
            
            with self._open_file_shared_write(str(self.output_path)) as f:
                while True:
                    try:
                        item = self._write_queue.get(timeout=30)
                        
                        # 结束标志
                        if item is None:
                            if batch:
                                self._flush_batch(f, batch)
                            break
                        
                        batch.append(item)
                        
                        # 达到 batch_size，批量写入
                        if len(batch) >= self.batch_size:
                            self._flush_batch(f, batch)
                            batch = []
                    
                    except queue.Empty:
                        # 超时但非停止信号，继续等待
                        if self.stop_event.is_set():
                            break
                        continue
            
            logger.debug(f"[GlobalWriter] 线程正常退出")
        
        except Exception as e:
            logger.error(f"[GlobalWriter] 线程异常: {e}", exc_info=True)
            self._writer_exception = e
    
    def _flush_batch(self, f, batch):
        """批量写入一批数据。
        
        Args:
            f: 文件对象
            batch: [(offset, data), ...] 列表
        """
        if not batch:
            return
        
        # 按 offset 排序（确保顺序写入）
        batch.sort(key=lambda x: x[0])
        
        # 批量 seek + write
        for offset, data in batch:
            f.seek(offset)
            f.write(data)
        
        # 统一 fsync
        f.flush()
        os.fsync(f.fileno())
        
        # 更新进度
        total = sum(len(d) for _, d in batch)
        self._bytes_written += total
        
        if self.progress_callback:
            self.progress_callback(total)
        
        logger.debug(
            f"[GlobalWriter] 批量写入: {len(batch)} items, {total} bytes, "
            f"total: {self._bytes_written} bytes"
        )
```

#### 修改：`xet/pipeline/chunk_assembler.py`

**新增方法**:
```python
def assemble_file_with_parallel_write(
    self,
    recon: QueryReconstructionResponse,
    cas_client,
    output_path: Path,
    file_hash: str,
    progress_tracker=None,
    cache_adapter: Optional[ChunkCacheAdapter] = None,
    stop_event: Optional[threading.Event] = None,
    checkpoint_manager=None,
    parallel_write: bool = False,  # 🔑 新参数
):
    """使用并行写入模式组装文件。"""
    
    if parallel_write:
        # 使用 GlobalWriter
        from xet.pipeline.global_writer import GlobalWriter
        
        writer = GlobalWriter(
            output_path=output_path.with_suffix(output_path.suffix + ".part"),
            batch_size=self.max_concurrent_downloads,
            progress_callback=lambda n: progress_tracker.increment_assembled(n) if progress_tracker else None,
            stop_event=stop_event,
        )
        writer.start()
        
        try:
            # 计算每个 term 的文件偏移量
            current_offset = 0
            if recon.offset_into_first_range > 0:
                current_offset = -recon.offset_into_first_range
            
            for term_idx, term in enumerate(recon.terms):
                # 确保 xorb 已解压
                self._ensure_xorb_ready(term.hash, ...)
                
                # 提取数据
                xorb_data = self._xorb_cache[term.hash]
                segment = ...  # 提取逻辑同现有
                
                # 计算文件偏移量
                if term_idx == 0 and recon.offset_into_first_range > 0:
                    write_offset = 0
                else:
                    write_offset = current_offset
                
                # 放入写队列（异步）
                writer.put(write_offset, segment)
                
                current_offset += len(segment)
                
                # Term 级 checkpoint
                if checkpoint_manager:
                    checkpoint_manager.mark_term_completed(...)
            
            # 完成写入
            total_written = writer.finish()
            
            # 重命名 .part -> 目标文件
            part_path = output_path.with_suffix(output_path.suffix + ".part")
            part_path.rename(output_path)
            
            logger.info(f"[ChunkAssembler] 并行写入完成: {output_path}")
        
        except Exception as e:
            logger.error(f"[ChunkAssembler] 并行写入失败: {e}")
            raise
    
    else:
        # 使用现有顺序写入
        self.assemble_file_with_prefetch(...)
```

#### 修改：`xet/cli/commands/download.py`

**新增参数**:
```python
parser.add_argument(
    "--parallel-write",
    action="store_true",
    default=False,
    help="启用并行批量写入（大文件性能提升 2-3 倍，实验性功能）",
)
```

**传递参数**:
```python
reconstructor = FileReconstructor(
    # ... 现有参数 ...
    parallel_write=args.parallel_write,
)
```

---

## 📊 预期效果

### 性能提升

| 场景 | 当前速度 | 并行写速度 | 提升 |
|------|---------|-----------|------|
| 小文件 (<100MB) | 3.5 MB/s | 7-10 MB/s | 2-3x |
| 大文件 (>1GB) | 3.5 MB/s | 10-15 MB/s | 3-4x |
| SSD 环境 | 受限 | 充分利用 | 显著 |

### 优势

1. ✅ **批量写入**: 减少系统调用次数
2. ✅ **统一 fsync**: 减少磁盘同步开销
3. ✅ **Windows 兼容**: CreateFileW + FILE_SHARE_WRITE
4. ✅ **可扩展**: 未来支持多段并行（segment-based）
5. ✅ **向后兼容**: 默认关闭，通过 `--parallel-write` 启用

### 风险

1. ⚠️ **复杂度增加**: 多线程写入，调试难度上升
2. ⚠️ **内存占用**: 写队列缓冲额外内存
3. ⚠️ **Windows 测试**: 需要充分测试 CreateFileW 兼容性
4. ⚠️ **异常处理**: 需要确保 writer 线程异常能正确传播

---

## 🎯 实施计划

### Phase 1: 核心实现（~185 行代码）

1. ✅ **设计分析**（本文档）
2. ⬜ **实现 GlobalWriter** (~150 行)
   - `_open_file_shared_write()` - Windows 兼容
   - `_writer_loop()` - 批量写入循环
   - `put()` / `finish()` - 队列接口

3. ⬜ **集成到 ChunkAssembler** (~30 行)
   - `assemble_file_with_parallel_write()` - 新方法
   - 偏移量计算逻辑
   - 异常处理

4. ⬜ **CLI 参数** (~5 行)
   - `--parallel-write` 参数
   - 传递到 FileReconstructor

### Phase 2: 测试验证

1. ⬜ **单元测试**
   - `test_global_writer.py` - GlobalWriter 基础功能
   - 异常处理测试
   - 批量写入正确性

2. ⬜ **集成测试**
   - 小文件 (<100MB) 完整性验证
   - 大文件 (>1GB) 性能测试
   - 断点续传兼容性

3. ⬜ **Windows 测试**
   - CreateFileW 兼容性
   - 中文路径支持

### Phase 3: 文档和优化

1. ⬜ **用户文档**
   - 使用说明
   - 性能对比
   - 故障排查

2. ⬜ **性能优化**
   - batch_size 自适应调整
   - 内存占用监控

---

## 🤔 待决策问题

### 1. 是否支持多段并行？

**当前设计**: 单段（single segment），主线程按 term 顺序提交

**未来扩展**: 多段（multi-segment），每段独立线程并行下载+提交

**建议**: 
- Phase 1 先实现单段，验证 GlobalWriter 稳定性
- Phase 2 再扩展多段（需要大幅改动 ChunkAssembler）

### 2. batch_size 如何确定？

**选项**:
- A. 固定值（8）
- B. 等于并发数（`max_concurrent_downloads`）
- C. 根据内存限制动态调整

**建议**: 
- Phase 1 使用选项 B（简单直观）
- Phase 2 根据测试结果优化

### 3. 是否默认启用？

**风险**:
- 新功能，稳定性未验证
- Windows 兼容性需要充分测试
- 用户可能遇到意外问题

**建议**:
- Phase 1: 默认关闭，通过 `--parallel-write` 启用
- Phase 2: 稳定后考虑默认启用（或根据文件大小自动决策）

---

## 📚 参考资料

1. **xet.py 实现**:
   - `~/xet.py/xet/reconstructor.py:29-78` (_open_file_shared_write)
   - `~/xet.py/xet/reconstructor.py:1208-1246` (_writer_parallel)

2. **Rust 实现**:
   - `~/xet/xet_data/src/file_reconstruction/data_writer/sequential_writer.rs` (SequentialWriter)
   - `~/xet/xet_data/src/file_reconstruction/data_writer/unordered_writer.rs` (UnorderedWriter)

3. **系统 API**:
   - Windows: CreateFileW + FILE_SHARE_WRITE
   - Linux: writev() (Python 无直接支持)

---

**文档创建时间**: 2026-06-21  
**作者**: Claude Code  
**状态**: 设计阶段 - 待审查
