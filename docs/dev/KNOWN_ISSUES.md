# XET+ 代码审查与问题跟踪

## 📅 最后审查: 2026-06-21

---

## ✅ 已修复问题

### 10. 进度条速度显示问题 [中优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 37772d6

**问题描述**:
下载进度条一直显示 `0.0 B/s`，无法显示实际下载速度和 ETA。

**代码位置**: `xet/pipeline/chunk_assembler_helpers.py:364`

**问题分析**:
```python
# 下载每个 segment 后
segment_data = cas_client.get_xorb_data(...)
segments.append(segment_data)
total_size += len(segment_data)

# ✅ 更新了 segment 计数
if progress_tracker:
    progress_tracker.increment_segments(1)

# ❌ 没有更新下载字节数
# 缺少: progress_tracker.increment_downloaded(len(segment_data))
```

**影响**:
- 速度计算公式: `speed = _downloaded_bytes / elapsed`
- `_downloaded_bytes` 一直为 0
- 导致速度显示 0.0 B/s，ETA 显示 0s

**修复方案**:
在下载每个 segment 后添加字节数更新：
```python
if progress_tracker:
    progress_tracker.increment_downloaded(len(segment_data))  # 新增
    progress_tracker.increment_segments(1)
```

**测试验证**:
- ✅ 速度正常显示: 883.7 KB/s → 6.6 MB/s
- ✅ ETA 正常显示: 2m → 1m → 0s
- ✅ 文件大小正确: 105,467,232 bytes

**修改文件**:
- `xet/pipeline/chunk_assembler_helpers.py`: 添加 1 行

---

## ✅ 已修复问题

### 9. **CRITICAL**: for 循环缩进错误 [最高优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: ad52dfe

**问题描述**:
`_assemble_with_sequential_write` 方法中 for 循环的循环体缩进错误，导致只处理第一个 term 就退出。

**代码位置**: `xet/pipeline/chunk_assembler.py:506-598`

**问题分析**:
```python
# line 506-509: for 循环和 continue（正确缩进 4 空格）
for term_idx, term in enumerate(recon.terms):
    if term_idx < start_term_idx:
        continue

# line 512-598: 后续所有代码（错误缩进 0 空格，在循环外！）
if self._stop_event.is_set():  # ❌ 0 空格缩进
    logger.info("[ChunkAssembler] 检测到中断信号")
    raise KeyboardInterrupt("用户中断")

# 确保 xorb 已加载
self._ensure_xorb_ready(...)  # ❌ 0 空格缩进

# ... 后续 80+ 行代码全部在循环外
```

**影响**:
- **严重性**: CRITICAL - 导致文件重建完全失败
- 只处理第一个 term，下载约 800KB
- 应该处理全部 17 terms，下载 100.6 MB
- 文件大小不匹配：实际 821126 bytes, 期望 105467232 bytes
- 用户看到错误: "文件大小不匹配"

**为什么之前的测试没发现**:
这是一个非常隐蔽的 bug：
1. 语法正确 - Python 不会报错
2. 逻辑看起来合理 - 第一个 term 能正常处理
3. 只有在实际下载测试时才会暴露

**修复方案**:
```python
# 将 line 512-598 全部添加 4 空格缩进，放入 for 循环内
for term_idx, term in enumerate(recon.terms):
    if term_idx < start_term_idx:
        continue

    if self._stop_event.is_set():  # ✓ 4 空格缩进
        logger.info("[ChunkAssembler] 检测到中断信号")
        raise KeyboardInterrupt("用户中断")

    # 确保 xorb 已加载
    self._ensure_xorb_ready(...)  # ✓ 4 空格缩进
    
    # ... 后续所有代码都在循环内
```

**修改范围**:
- 71 行代码缩进修改（从 0 空格改为 4 空格）

**测试验证**:
下载 HuggingFace 文件 granite-embedding-97M-multilingual-r2-Q4_K_M.gguf:
- ✅ 处理全部 17 terms（之前只处理 1 个）
- ✅ 下载全部 10 xorbs, 14 segments
- ✅ 文件大小正确: 105,467,232 bytes
- ✅ 下载成功，无错误

**修改文件**:
- `xet/pipeline/chunk_assembler.py`: 71 行缩进修改

---

### 5. 参数传递链不完整 [高优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 711d7fb

**问题描述**:
从 `assemble_file_with_prefetch` 到 `_assemble_with_prefetch` 再到写入方法的参数传递链不完整。

**代码位置**: 
- `xet/pipeline/chunk_assembler.py:400-411` (方法签名)
- `xet/pipeline/chunk_assembler.py:167-170` (调用点)

**问题分析**:
```python
# assemble_file_with_prefetch (line 125) 有参数:
stop_event: Optional[threading.Event] = None

# 但是调用 _assemble_with_prefetch 时 (line 167-170):
self._assemble_with_prefetch(
    recon, cas_client, output_path, file_hash,
    progress_tracker, cache_adapter, checkpoint_manager
)  # 缺少 stop_event 和 parallel_write

# _assemble_with_prefetch 内部 (line 473, 480) 使用了这些参数:
self._assemble_with_parallel_write(..., stop_event, ...)
self._assemble_with_sequential_write(..., stop_event, ...)
```

**影响**:
- NameError: name 'stop_event' is not defined at line 473, 480
- NameError: name 'parallel_write' is not defined at line 467

**修复方案**:
```python
# 1. 添加参数到方法签名 (line 400-411)
def _assemble_with_prefetch(
    self,
    recon: QueryReconstructionResponse,
    cas_client,
    output_path: Path,
    file_hash: str,
    progress_tracker: Optional[ProgressTracker],
    cache_adapter,
    checkpoint_manager=None,
    stop_event: Optional[threading.Event] = None,  # 新增
    parallel_write: bool = False,  # 新增
) -> None:

# 2. 更新调用点传递参数 (line 167-170)
self._assemble_with_prefetch(
    recon, cas_client, output_path, file_hash,
    progress_tracker, cache_adapter, checkpoint_manager,
    stop_event, parallel_write  # 新增
)
```

**修改文件**:
- `xet/pipeline/chunk_assembler.py`: +2 行参数定义, +1 行调用传参

---

### 6. 缺少 time 模块导入 [高优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 711d7fb

**问题描述**:
`chunk_assembler.py` 使用 `time.time()` 但未导入 time 模块。

**代码位置**: 
- `xet/pipeline/chunk_assembler.py:10` (导入部分)
- `xet/pipeline/chunk_assembler.py:603` (使用点)

**影响**:
- NameError: name 'time' is not defined at line 603
- 导致下载进度统计失败

**修复方案**:
```python
# 在文件开头添加
import time
```

**修改文件**:
- `xet/pipeline/chunk_assembler.py`: +1 行 import

---

### 7. 变量作用域错误 [中优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 711d7fb

**问题描述**:
`file_reconstructor.py` 在 `__init__` 日志中使用局部变量而非实例变量。

**代码位置**: `xet/pipeline/file_reconstructor.py:144`

**问题分析**:
```python
# 错误: 使用局部变量 parallel_write
f"parallel_write={'enabled' if parallel_write else 'disabled'}"

# 但是 parallel_write 是 __init__ 的参数，非 self 属性
# self.parallel_write 才是存储的实例属性
```

**影响**:
- NameError: name 'parallel_write' is not defined
- 初始化日志输出失败

**修复方案**:
```python
# 使用 self.parallel_write
f"parallel_write={'enabled' if self.parallel_write else 'disabled'}"
```

**修改文件**:
- `xet/pipeline/file_reconstructor.py`: 1 行修改

---

### 8. 多余参数传递 [高优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 711d7fb

**问题描述**:
`cas_client.get_xorb_data()` 被传递了不存在的 `file_hash` 参数。

**代码位置**: 
- `xet/pipeline/chunk_assembler_helpers.py:355-359`
- `xet/network/cas_client.py:342` (方法定义)

**问题分析**:
```python
# 调用点 (chunk_assembler_helpers.py:355-359)
segment_data = cas_client.get_xorb_data(
    url=fi.url,
    url_range=fi.url_range,
    file_hash=file_hash,  # 多余参数
)

# 方法定义 (cas_client.py:342)
def get_xorb_data(self, url: str, url_range: HttpRange) -> bytes:
    # 只接受 url 和 url_range 两个参数
```

**影响**:
- TypeError: CASClient.get_xorb_data() got an unexpected keyword argument 'file_hash'
- 导致 xorb 下载失败

**修复方案**:
```python
# 移除 file_hash 参数
segment_data = cas_client.get_xorb_data(
    url=fi.url,
    url_range=fi.url_range,
)
```

**修改文件**:
- `xet/pipeline/chunk_assembler_helpers.py`: -1 行

---

### 1. GlobalWriter 线程安全问题 [低优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 274c9c2

**问题描述**:
`_bytes_written` 在多个线程之间访问时缺少锁保护。

**影响分析**:
- `_flush_batch()` 在 writer 线程中执行 `self._bytes_written += total`
- `finish()` 在主线程中读取 `self._bytes_written`
- 虽然 Python 中整数赋值是原子的，但 `+=` 操作不是原子的
- 可能导致在 `finish()` 中读取到不完整的值（概率很低）

**修复方案**:
```python
# xet/pipeline/global_writer.py:83
self._bytes_lock = threading.Lock()  # 保护 _bytes_written

# _flush_batch() 中
with self._bytes_lock:
    self._bytes_written += total

# finish() 中
with self._bytes_lock:
    final_bytes = self._bytes_written
```

**修改文件**:
- `xet/pipeline/global_writer.py`: +12 行

---

### 2. ChunkAssembler 偏移量计算不一致 [中优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 274c9c2

**问题描述**:
checkpoint 恢复时的偏移量计算逻辑不一致。

**代码位置**: `xet/pipeline/chunk_assembler.py:663, 670`

**问题分析**:
```python
# 第 663 行：初始化为负数
if start_term_idx == 0 and recon.offset_into_first_range > 0:
    current_offset = -recon.offset_into_first_range

# 第 670 行（修复前）：跳过 term 时使用 max(0, ...)
if term_idx == 0 and recon.offset_into_first_range > 0:
    current_offset += max(0, term.unpacked_length - recon.offset_into_first_range)
```

**为什么不一致**:
1. 初始化时允许负数偏移（-offset_into_first_range）
2. 累加时使用 max(0, ...) 强制非负
3. 当 `offset_into_first_range > term.unpacked_length` 时会出错

**修复方案**:
```python
# 移除 max(0, ...)，统一使用可能为负的偏移
current_offset += term.unpacked_length - recon.offset_into_first_range
```

**修改文件**:
- `xet/pipeline/chunk_assembler.py`: -1 行

**验证**:
- ✅ 与 segment slicing 逻辑一致（line 499: `segment_data[offset:]`）
- ✅ checkpoint 恢复边界条件正确

---

### 3. GlobalWriter 资源清理机制 [中优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: 274c9c2

**问题描述**:
如果 `finish()` 未被调用（程序异常退出），writer 线程会一直运行。

**影响分析**:
1. 文件句柄可能未正确关闭
2. 队列中的数据可能丢失
3. 虽然设置了 `daemon=True`，但无法保证清理

**修复方案**:
添加上下文管理器支持：
```python
# xet/pipeline/global_writer.py:165-187
def __enter__(self):
    self.start()
    return self

def __exit__(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
        # 正常退出，完成写入
        try:
            self.finish()
        except Exception as e:
            logger.error(f"[GlobalWriter] 完成写入失败: {e}")
            return False
    else:
        # 异常退出，设置停止信号并等待线程退出
        logger.warning(f"[GlobalWriter] 异常退出: {exc_type.__name__}: {exc_val}")
        self.stop_event.set()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=5)
    return False  # 不抑制异常
```

**使用方式**:
```python
# 推荐用法（自动清理）
with GlobalWriter(output_path) as writer:
    writer.put(offset, data)
```

**修改文件**:
- `xet/pipeline/global_writer.py`: +23 行

---

### 4. OnlineRegression None 返回值处理 [低优先级] - 已验证正确
**发现日期**: 2026-06-21  
**状态**: ✅ 当前代码已正确处理

**问题描述**:
`predict()` 方法在样本不足时返回 `(None, None)`，调用方可能未检查。

**代码分析**:
```python
# xet/network/online_regression.py:72-110
def predict(self, x0: float) -> Tuple[Optional[float], Optional[float]]:
    delta = self.sw * self.sxx - self.sx * self.sx
    if abs(delta) < 1e-12:
        return (None, None)  # 可能导致 None 被使用
```

**当前使用情况**:
```python
# xet/network/adaptive_concurrency.py:xxx
predicted_rtt = self._rtt_predictor.predicted_rtt(...)
if predicted_rtt is not None and predicted_rtt > self._target_max_rtt:
    return  # ✅ 已正确检查 None
```

**结论**: 当前集成代码已正确处理 None，无需修复。

---

## 📋 代码审查总结

### 审查范围
- `xet/pipeline/global_writer.py` (335 行)
- `xet/pipeline/chunk_assembler.py` (800+ 行)
- `xet/network/online_regression.py` (264 行)
- `xet/network/adaptive_concurrency.py` (200+ 行)

### 问题统计
- **发现**: 4 个问题
- **已修复**: 3 个问题
- **已验证正常**: 1 个问题

### 优先级分布
- **中优先级**: 2 个（偏移量计算、资源清理）
- **低优先级**: 2 个（线程安全、None 检查）

### 代码质量评价
✅ **优秀**
- 模块化架构清晰
- 类型注解完整
- 错误处理完善
- 日志记录详细
- 文档注释规范

### 修复影响
- **功能正确性**: 偏移量计算修复确保 checkpoint 恢复正确
- **健壮性**: 上下文管理器增强异常处理
- **线程安全**: 锁机制消除潜在竞争条件
- **代码质量**: 无破坏性变更，向后兼容

---

## 🔍 未来代码审查建议

### 1. 定期审查重点
- 多线程代码的锁保护
- 边界条件处理（offset、range、index）
- 资源清理逻辑（文件句柄、线程、网络连接）
- Optional 类型的 None 检查

### 2. 测试覆盖强化
- 并发场景单元测试
- checkpoint 恢复边界条件测试
- 异常退出资源清理测试
- 内存泄漏检测

### 3. 代码规范
- ✅ 继续使用类型注解
- ✅ 继续完善文档注释
- ✅ 继续使用上下文管理器管理资源
- ✅ 继续使用 threading.Lock 保护共享状态

---

## 📊 测试验证

### 已完成测试
1. ✅ **GlobalWriter 基础功能测试**
   ```python
   writer = GlobalWriter(output_path, batch_size=4)
   writer.start()
   writer.put(0, b"hello")
   writer.put(5, b"world")
   total = writer.finish()
   ```

2. ✅ **上下文管理器测试**
   ```python
   with GlobalWriter(output_path) as writer:
       writer.put(0, b"test")
   ```

3. ✅ **线程安全测试**
   - 多线程并发 put() 操作
   - 主线程调用 finish() 获取字节数
   - 无竞争条件发生

4. ✅ **偏移量计算验证**
   - checkpoint 恢复场景
   - offset_into_first_range 边界条件
   - 与 segment slicing 逻辑一致

### 建议增加测试
- [ ] GlobalWriter 异常场景测试（writer 线程崩溃）
- [ ] ChunkAssembler 极端边界条件测试
- [ ] OnlineRegression 样本不足场景测试
- [ ] 并发压力测试（1000+ 并发写入）

---

## 🎯 待改进项（P3 低优先级）

### 性能优化
1. **GlobalWriter 批量大小自适应**
   - 当前固定 batch_size=8
   - 可根据磁盘 I/O 速度动态调整
   - 预期提升: 5-10% 写入性能

2. **ChunkAssembler 预取策略优化**
   - 当前基于固定水位线
   - 可集成完成速率估算器（CompletionRateEstimator）
   - 预期提升: 低速网络下减少内存占用 20-30%

3. **OnlineRegression 样本权重衰减**
   - 当前使用固定衰减因子
   - 可根据网络稳定性自适应调整
   - 预期提升: RTT 预测准确率 +5%

### 代码质量
1. **增加单元测试覆盖率**
   - 目标: 80%+ 覆盖率
   - 重点: 边界条件、并发场景、异常处理

2. **增加集成测试**
   - 端到端下载测试
   - 断点续传测试
   - 缓存复用测试

3. **性能基准测试**
   - 建立性能基线
   - 持续监控回归

---

## 📝 相关文档

- **代码审查报告**: `CODE_REVIEW_2026-06-21.md`
- **修复提交**: commit 274c9c2
- **设计文档**: 
  - `docs/XET_PIPELINE_ANALYSIS.md` - Pipeline 架构分析
  - `docs/XETPLUS_COMPARISON.md` - 三方对比分析

---

## ✅ 已修复问题

### 11. Chunk 缓存支持不连续 ranges [中优先级] - 已完全修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已完全修复  
**Commit**: c88a58f (部分修复 70%), 4e24709 (完整修复 100%)

**问题描述**:
部分 xorb (约 30%) 在写入 chunk 缓存时因"长度不匹配"而失败。

**根本原因**:
- Xorb 可以包含不连续的全局 chunk 范围（如 [0-40, 104-154]）
- Xorb 内部 chunks 是连续存储的（92 个）
- chunk_byte_indices 对应 xorb 内部连续索引（93 个偏移）
- 旧 API 假设单个 merged_range 可以表示整个 xorb
- 对不连续 ranges：merged_range.length() ≠ 实际 chunks 数量

**代码位置**: 
- `xet/pipeline/chunk_cache_adapter.py:124-193` (完整修复)
- `xet/protocol/types.py:60-77` (添加 contains 方法)

**修复方案**:

**阶段 1 - 部分修复 (commit c88a58f)**:
- 修复检查逻辑：用 `sum(cr.length())` 代替 `merged_range.length()`
- 正确识别不连续 ranges，从误报改为正确跳过
- 成果：70% xorbs 成功缓存（连续 ranges）

**阶段 2 - 完整修复 (commit 4e24709)**:
- 为每个连续 range 分别缓存
- 维护全局 chunk 编号到 xorb 内部索引的映射
- 读取时从多个缓存段重组数据
- 成果：100% xorbs 成功缓存

**技术细节**:
```python
# 全局 chunk 编号: [0-40, 104-154] (不连续，92 个)
# Xorb 内部索引:   [0-91] (连续，92 个)

# 映射关系：
# - 全局 0-40   → xorb 内部 0-40
# - 全局 104-154 → xorb 内部 41-91

# 分段缓存：
for chunk_range in sorted_ranges:
    # 提取对应的 indices 和 data 子集
    sub_indices = chunk_byte_indices[start_idx:end_idx]
    sub_data = decompressed_data[data_start:data_end]
    cache.put(xorb_hash, chunk_range, sub_indices, sub_data)
```

**测试验证**:
- ✅ 离线测试：3/3 不连续 xorbs 通过
- ✅ 集成测试：10/10 xorbs 成功缓存
- ✅ Cache 命中率：100%

**修复进度**:
- 修复前: 0/10 (0%)
- 部分修复: 7/10 (70%)
- 完整修复: 10/10 (100%)

**影响**:
- ✅ 所有 xorbs 都能正常缓存
- ✅ Cache 命中率提升 100%
- ✅ 不影响下载功能
- ✅ 性能显著提升

**修改文件**:
- `xet/pipeline/chunk_cache_adapter.py`: 重构 put/get 方法
- `xet/protocol/types.py`: 添加 ChunkRange.contains() 方法
- `debug_materials/test_non_contiguous.py`: 测试脚本

---

## 🔧 待优化项（非关键）

**已删除**: 问题 #11 已完全修复，不再是待优化项

---

### 12. XET 文件检测缺少 revision 参数支持 [中优先级] - 已修复
**发现日期**: 2026-06-21  
**修复状态**: ✅ 已修复  
**Commit**: f3e5538

**问题描述**:
`detect_xet_file()` 函数硬编码使用 `main` 分支，无法检测特定 commit 上的 XET 文件。

**代码位置**: 
- `xet/cli/commands/download.py:347-430` (detect_xet_file 函数)
- `xet/cli/commands/download.py:48-56` (命令行参数)
- `xet/cli/commands/download.py:853, 874, 910` (调用点)

**问题分析**:
```python
# 旧代码硬编码 main 分支
if repo_type == "dataset":
    file_url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{filename}"
else:
    file_url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
```

**影响**:
- 无法下载特定 commit 上的文件
- 文件在非 main 分支时错误显示 "不是 XET 格式"
- 用户必须手动切换到 main 分支才能下载

**实际案例**:
```bash
# 文件在 commit 45ce642d... 上
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf

# 错误: WARNING: 文件不是 XET 格式
# 原因: 代码尝试访问 main 分支而非实际 commit
```

**修复方案**:
```python
# 1. 添加命令行参数
parser.add_argument(
    "-r", "--revision",
    help="Git revision (分支名或 commit hash，默认: main)",
    default="main",
)

# 2. 函数添加 revision 参数
def detect_xet_file(
    repo_id: str,
    repo_type: str,
    filename: str,
    token: str,
    session: requests.Session,
    revision: str = "main",  # 新增
) -> Optional[dict]:
    # 使用 revision 构造 URL
    file_url = f"https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"

# 3. 更新所有调用点
xet_info = detect_xet_file(repo_id, repo_type, filename, hf_token, session, revision=args.revision)
```

**测试验证**:
```bash
# 测试 1: 使用 commit hash
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --revision 45ce642d3fab2033d167ec09641a159010f7d9d9
# ✅ 检测成功

# 测试 2: 使用默认 main
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
# ✅ 检测成功（使用 main 分支）

# 测试 3: 使用分支名
xet download user/repo/file.gguf --revision develop
# ✅ 支持任意分支
```

**修改文件**:
- `xet/cli/commands/download.py`: +6 行参数定义, +1 行函数签名, +2 行 URL 构造, +3 行调用更新

**用户体验改进**:
- ✅ 支持下载任意 commit/branch 上的文件
- ✅ 向后兼容（默认 main 分支）
- ✅ 错误信息更清晰
- ✅ 符合 git 工作流习惯

---

---

---

## ✅ 新功能：HF_ENDPOINT 镜像站支持 [已实现]

**实现日期**: 2026-06-21  
**状态**: ✅ 已完成

### 功能说明

CLI 现已支持通过 `--hf-endpoint` 参数或 `HF_ENDPOINT` 环境变量替换 HuggingFace 端点，允许使用国内镜像站（如 hf-mirror.com）进行直连下载。

### 使用方式

**方式 1: 命令行参数**
```bash
python -m xet.cli.main download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --hf-endpoint https://hf-mirror.com \
    --token YOUR_TOKEN \
    -o output.gguf
```

**方式 2: 环境变量**
```bash
export HF_ENDPOINT=https://hf-mirror.com
python -m xet.cli.main download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --token YOUR_TOKEN \
    -o output.gguf
```

**方式 3: 配合 IP 优选**
```bash
python -m xet.cli.main download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --hf-endpoint https://hf-mirror.com \
    --optimize-hosts \
    --token YOUR_TOKEN \
    -o output.gguf
```

### 实现细节

**修改的文件**:
- `xet/cli/commands/download.py`: 添加 `--hf-endpoint` 参数和 URL 替换逻辑
- `xet/network/host_optimizer.py`: 添加 `check_hf_endpoint_xet_support()` 函数

**修改的函数**:
- `list_hf_files()`: 添加 `hf_endpoint` 参数
- `detect_xet_file()`: 添加 `hf_endpoint` 参数
- `download_file_direct()`: 添加 `hf_endpoint` 参数
- `download_single_file()`: 添加 `hf_endpoint` 参数

**新增的函数**:
- `check_hf_endpoint_xet_support()`: 检测端点的 XET 支持和可达性
  - 测试 XET 特征头（x-linked-etag, x-linked-size, x-repo-commit）
  - 测试 XET Link 头（rel="xet-auth", rel="xet-reconstruction-info"）
  - 返回可达性、支持状态、响应时间等信息

### 集成 IP 优选

当启用 `--optimize-hosts` 时，CLI 会自动检测自定义 HF_ENDPOINT 的 XET 支持：

```
🚀 正在执行 HOST 优选（DoH 查询 + 测速）...
   检测 https://hf-mirror.com 的 XET 支持...
   ✅ https://hf-mirror.com 支持 XET 协议（响应时间: 0.23s）
      x-linked-etag: 355f1f30ac3bdad0...
```

### 验证结果

✅ **哈希值一致性验证**:
- huggingface.co 和 hf-mirror.com 返回的 x-linked-etag 完全一致
- 两个端点的文件大小（x-linked-size）完全一致
- 两个端点的 commit hash（x-repo-commit）完全一致

✅ **完整流程测试**:
- ✅ hf-mirror.com 直连下载成功（无需代理）
- ✅ 认证和元数据获取可完全直连
- ✅ 仅 segment 数据下载需要代理（us.aws.cdn.hf.co）

### 相关文档

- 完整流程验证: 见上方 "🌐 直连方案：hf-mirror.com 作为 XET 入口"
- 测试脚本: `test_hf_endpoint.sh`

---

## 🌐 直连方案：hf-mirror.com 作为 XET 入口 [已验证]

**验证日期**: 2026-06-21  
**状态**: ✅ 完整流程测试通过

### 测试结论

**hf-mirror.com 完全支持 XET 协议**，可作为直连下载的入口点，实现混合架构：
- **认证/元数据**: 走直连（hf-mirror.com + cas-server.xethub.hf.co）
- **数据下载**: 走代理（us.aws.cdn.hf.co/xorbs）

### 完整流程（4步）

```
步骤 1: HEAD hf-mirror.com/<repo>/<file>  [直连 ✅]
  ↓ 返回 XET Link 头和特征头
  
步骤 2: GET xet-auth endpoint  [直连 ✅]
  ↓ 返回 {"accessToken": "..."}
  
步骤 3: GET cas-server.xethub.hf.co/v1/reconstructions/<hash>  [直连 ✅]
  ↓ 携带 Authorization: Bearer <token>
  ↓ 返回重建信息: {terms: [...], fetch_info: {...}}
  
步骤 4: GET us.aws.cdn.hf.co/xorbs/default/<hash>  [需要代理 ⚠️]
  ↓ 下载实际 segment 数据（支持 HTTP Range）
```

### 重建响应结构

```json
{
  "offset_into_first_range": 0,
  "terms": [
    {
      "hash": "f52ace46e9559367a345b3c5a6ad6261391dae66197857915fa7d6a1ca27c812",
      "unpacked_length": 3301792,
      "range": {"start": 0, "end": 41}
    }
  ],
  "fetch_info": {
    "f52ace46e9559367a345b3c5a6ad6261391dae66197857915fa7d6a1ca27c812": [
      {
        "range": {"start": 0, "end": 41},
        "url": "https://us.aws.cdn.hf.co/xorbs/default/f52ace46e...",
        "url_range": {"start": 0, "end": 1668043}
      }
    ]
  }
}
```

**字段说明**:
- `terms`: 文件重建的 term 列表，每个 term 对应一个 xorb（segment）
  - `hash`: segment 的哈希值（xorb ID）
  - `unpacked_length`: 解压后的数据长度
  - `range`: 在目标文件中的字节位置
- `fetch_info`: 以 segment hash 为 key 的下载信息字典
  - `range`: 在 term 内的字节范围
  - `url`: 实际的 segment 下载 URL
  - `url_range`: 该 URL 返回的字节范围

### XET 特征头（防投毒）

hf-mirror.com 返回的 XET 特征头：
```
x-linked-etag: "355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"
x-linked-size: 105467232
x-repo-commit: 45ce642d3fab2033d167ec09641a159010f7d9d9
```

**用途**: 验证这些头的存在可以防止 DNS 劫持/假网站投毒。

### 域名可达性要求

| 域名 | 用途 | 是否需要代理 | 备注 |
|------|------|-------------|------|
| hf-mirror.com | XET 入口 + 认证 | ❌ 直连 | 完全支持 XET 协议 |
| cas-server.xethub.hf.co | 获取重建信息 | ❌ 直连 | 返回 segment URL 列表 |
| us.aws.cdn.hf.co | 下载 segment 数据 | ✅ 需要代理 | 大流量操作 |

**验证方式**:
```python
# 检查 XET 头是否存在
resp = requests.head(f"https://hf-mirror.com/{repo}/resolve/{commit}/{file}")
has_xet = all(k in resp.headers for k in ['x-linked-etag', 'x-linked-size'])
```

### 实现建议

1. **域名验证逻辑**:
   - 如果 huggingface.co 不可达 → 尝试 hf-mirror.com
   - 如果 hf-mirror.com 可达且返回 XET 头 → 使用混合模式
   - 如果 us.aws.cdn.hf.co 不可达 → 要求配置代理

2. **混合下载模式**:
   ```python
   # 认证和元数据（直连）
   auth_resp = requests.get(auth_url)  # hf-mirror.com，无代理
   recon_resp = requests.get(recon_url, headers={"Authorization": f"Bearer {token}"})  # cas-server，无代理
   
   # 数据下载（代理）
   segment_resp = requests.get(segment_url, proxies=proxies)  # us.aws.cdn.hf.co，需要代理
   ```

3. **错误处理**:
   - 如果 segment 下载失败（403/超时）→ 提示用户配置代理
   - 如果缺少 XET 头 → 警告可能是假网站/DNS 污染

---

## 🔄 待实现：自动重试机制 [高优先级]

**发现日期**: 2026-06-21  
**优先级**: P1 - 高优先级  
**状态**: 📋 设计完成，待实现

### 问题描述

**偶发性文件不完整问题**（96.9% 问题）：
- **症状**: 文件只写入 96.9% (102,165,440 / 105,467,232 字节，少 3.15 MB)
- **频率**: 约 10-20% 概率
- **影响**: 用户需要手动重试或使用 `--resume` 续传

**可能原因**：
1. 某个 xorb segment 网络下载失败但未被检测
2. GlobalWriter 在极端情况下未完全 flush
3. 并发写入时的竞态条件

### 重试策略设计（3层防护）

#### 第 1 层：内部自动重试（推荐优先实现）

**位置**: `xet/pipeline/file_reconstructor.py`

**设计**：
```python
def reconstruct_file(self, file_hash, expected_size, resume=True):
    MAX_RETRIES = 3  # 最多重试 3 次
    
    for attempt in range(MAX_RETRIES):
        try:
            # 执行下载和组装
            self._do_reconstruct(file_hash, expected_size, resume)
            
            # 验证文件大小
            actual_size = self.output_path.stat().st_size
            if expected_size > 0 and actual_size != expected_size:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"[FileReconstructor] 文件大小不匹配 "
                        f"(期望 {expected_size}, 实际 {actual_size}), "
                        f"自动重试 ({attempt + 1}/{MAX_RETRIES})..."
                    )
                    # 删除不完整的文件
                    if self.output_path.exists():
                        self.output_path.unlink()
                    # 清理 checkpoint，从头重新下载
                    if self.checkpoint_manager:
                        self.checkpoint_manager.clear(file_hash)
                    continue
                else:
                    # 最后一次重试也失败，抛出异常
                    raise ReconstructionError(
                        f"文件大小不匹配（尝试 {MAX_RETRIES} 次后仍失败）: "
                        f"期望 {expected_size}, 实际 {actual_size}"
                    )
            
            # 成功
            return self.output_path
            
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                logger.warning(f"[FileReconstructor] 重试 {attempt + 1}/{MAX_RETRIES}: {e}")
                continue
            else:
                raise
```

**优点**：
- ✅ 对用户透明，大多数情况下自动解决
- ✅ 不需要用户手动重试
- ✅ 保留 checkpoint 供手动续传使用

**实施要点**：
1. 重试前删除不完整文件
2. 清理 checkpoint，从头重新下载
3. 保留最后一次异常供上层处理

#### 第 2 层：CLI 层重试（批量下载）

**位置**: `xet/cli/commands/download.py`

**设计**：
```python
def download_multiple_files(files, args):
    failed_files = []
    MAX_BATCH_RETRIES = 2
    
    for retry_round in range(MAX_BATCH_RETRIES):
        to_download = failed_files if retry_round > 0 else files
        failed_files = []
        
        for file_info in to_download:
            try:
                result = download_single_file(file_info, args)
                if not result.success:
                    failed_files.append(file_info)
            except Exception as e:
                logger.error(f"下载失败: {file_info.path} - {e}")
                failed_files.append(file_info)
        
        if not failed_files:
            break
            
        if retry_round < MAX_BATCH_RETRIES - 1:
            logger.info(
                f"有 {len(failed_files)} 个文件失败，"
                f"自动重试 ({retry_round + 1}/{MAX_BATCH_RETRIES})..."
            )
            time.sleep(2)  # 短暂延迟
    
    return failed_files
```

**优点**：
- ✅ 批量下载时自动重试失败的文件
- ✅ 避免一个文件失败导致整批失败

#### 第 3 层：用户手动续传（最后防线）

**现有机制**：保留现有的 checkpoint 机制

```bash
# 第一次下载（可能失败）
xet download repo/file.gguf

# 用户手动续传（使用 checkpoint）
xet download repo/file.gguf --resume
```

**优点**：
- ✅ 适用于网络极差的环境
- ✅ 用户可控制何时重试

### 配置选项设计

**配置文件**: `~/.xet/config.yaml`

```yaml
download:
  auto_retry:
    enabled: true           # 是否启用自动重试
    max_attempts: 3         # 最大重试次数
    retry_delay: 2          # 重试间隔（秒）
    size_mismatch_retry: true  # 文件大小不匹配时是否重试
```

**命令行参数**：

```bash
xet download repo/file.gguf --no-auto-retry  # 禁用自动重试
xet download repo/file.gguf --max-retries 5   # 自定义重试次数
```

### 实施建议

**短期（立即可做）**：
1. ✅ 在 `FileReconstructor` 添加文件大小不匹配的自动重试（第 1 层）
2. ✅ 重试前清理不完整文件和 checkpoint
3. ✅ 添加详细的重试日志

**中期（1-2周）**：
4. 在批量下载添加失败重试（第 2 层）
5. 添加配置选项支持
6. 添加命令行参数

**长期（未来优化）**：
7. 增加详细的重试统计和分析
8. 根据错误类型智能决定是否重试（网络错误重试，文件损坏不重试）
9. 集成到监控和告警系统

### 关键决策点

- ✅ **默认启用自动重试**：是
- ✅ **重试次数**：3次
- ✅ **是否清理不完整文件**：是（重试前删除）
- ✅ **是否保留 checkpoint**：是（供手动续传）
- ✅ **重试间隔**：无需等待（立即重试）

### 预期效果

- 🎯 **成功率提升**：从 80-90% 提升到 99%+
- 🎯 **用户体验**：大多数失败自动恢复，无需手动干预
- 🎯 **向后兼容**：不影响现有功能和命令行参数

### 相关文件

- `xet/pipeline/file_reconstructor.py`: 第 1 层重试逻辑
- `xet/cli/commands/download.py`: 第 2 层重试逻辑
- `~/.xet/config.yaml`: 配置文件（新增）

---

**维护者**: Claude & User  
**下次审查**: 建议 1 个月后（2026-07-21）或重大功能更新时
