# XET 下载实现三方对比分析报告

**分析日期**: 2026-06-21  
**对比版本**: Rust 原版 (~/xet) | Python 旧版 (~/xet.py) | Python 新版 (~/xetplus)

---

## 一、架构总览对比

### 1.1 代码规模

| 维度 | Rust 原版 | Python 旧版 | Python 新版 (xetplus) |
|------|-----------|-------------|------------------------|
| 核心代码量 | ~15,000+ 行 | ~6,048 行 | ~6,409 行 |
| 模块化程度 | 高（15+ 模块） | 中（8 模块） | 高（12+ 模块） |
| 并发模型 | async/await (Tokio) | ThreadPoolExecutor | ThreadPoolExecutor |
| 类型系统 | 强类型 + 编译检查 | 动态类型 | 动态类型 + 类型注解 |

### 1.2 架构分层

**Rust 原版（最复杂）**:
```
FileDownloadSession
  └─> FileReconstructor
       └─> ReconstructionTermManager (自适应预取)
            └─> FileTerm + XorbBlock (单例飞行)
                 └─> RemoteClient (ACC + RetryWrapper)
                      └─> ChunkCache (磁盘缓存)
```

**Python 旧版（经典三层）**:
```
CLI Layer (xet_dl.py)
  └─> Business Logic (StreamFileReconstructor)
       └─> Infrastructure (CASClient, XorbDeserializer)
```

**Python 新版（模块化重构）**:
```
CLI Layer (download.py)
  └─> Pipeline Layer (FileReconstructor)
       ├─> DownloadScheduler (并行下载)
       ├─> ChunkAssembler (预取组装)
       └─> CheckpointManager (断点续传)
            └─> Network Layer (CASClient + ACC)
```

---

## 二、功能完整性对比

### 2.1 核心功能矩阵

| 功能模块 | Rust | xet.py | xetplus | 优先级 |
|---------|------|--------|---------|--------|
| **基础下载** |
| V2/V1 API 自动降级 | ✅ | ✅ | ✅ | - |
| Multi-range fetch | ✅ | ✅ | ✅ | - |
| 流式下载 | ✅ | ✅ | ✅ | - |
| **断点续传** |
| 文件级 checkpoint | ✅ | ✅ | ✅ | - |
| Xorb 级 checkpoint | ❌ | ✅ | ✅ | - |
| 分段级 checkpoint | ✅ | ✅ | ✅ | - |
| Term 级 checkpoint | ✅ | ✅ (每10 terms) | ❌ | **P1** |
| **缓存机制** |
| Chunk-level 磁盘缓存 | ✅ | ❌ | ✅ | - |
| Xorb-level 磁盘缓存 | ❌ | ✅ | ✅ | - |
| LRU 驱逐策略 | ✅ | ✅ | ✅ | - |
| 跨文件去重 | ✅ | ✅ | ✅ | - |
| **并发控制** |
| 自适应并发 (ACC) | ✅ | ✅ | ✅ | - |
| RTT/带宽预测 | ✅ | ❌ | ❌ | **P2** |
| 全局重试协调 | ❌ | ✅ | ✅ | - |
| **错误处理** |
| URL 刷新协调 (403) | ✅ | ✅ | ✅ | - |
| Token 刷新 (401) | ✅ | ✅ | ✅ | - |
| 低速超时检测 | ❌ | ✅ | ✅ | - |
| **预取机制** |
| 水位线预取 | ✅ | ✅ | ✅ | - |
| 完成速率估算 | ✅ | ✅ | ❌ | **P1** |
| 自适应预取大小 | ✅ | ✅ | ❌ | **P1** |
| **内存管理** |
| 动态缓冲区扩展 | ✅ | ❌ | ✅ | - |
| 虚拟许可 (seed permit) | ✅ | ❌ | ❌ | **P2** |
| 按 term 大小分配 | ✅ | ❌ | ✅ | - |

### 2.2 xetplus 需要补齐的功能

#### 来自 xet.py

**P1: Term 级 checkpoint**
- **位置**: `xet.py/xet/reconstructor.py:349-365`
- **价值**: 更细粒度断点续传，减少重复下载
- **修改**: `xet/pipeline/checkpoint_manager.py` 扩展

**P1: 完成速率估算器**
- **位置**: `xet.py/xet/utils.py:ExpWeightedMovingAvg`
- **价值**: 自适应调整预取大小
- **修改**: 新建 `xet/pipeline/completion_rate_estimator.py`

#### 来自 Rust 原版

**P2: RTT/带宽在线预测**
- **位置**: `xet_client/concurrency_controller.rs:OnlineLinearRegression`
- **价值**: 更精确的并发控制
- **修改**: `xet/network/adaptive_concurrency.py` 增强

**P2: 虚拟许可机制**
- **位置**: Rust `SemaphoreExt::increment_permits_to_target`
- **价值**: 避免下载启动时的 FIFO 等待
- **修改**: 新建 `xet/pipeline/virtual_permit.py`

---

## 三、设计亮点对比

### 3.1 xetplus 已超越部分

1. **模块化架构**
   - Pipeline 层清晰分离：Scheduler / Assembler / Reconstructor
   - 更易测试和扩展
   - xet.py 是单体 `StreamFileReconstructor`

2. **Chunk-level 缓存**
   - 比 xorb-level 更细粒度
   - 支持部分 xorb 复用
   - 代码: `xet/pipeline/chunk_disk_cache.py`

3. **全局重试协调器**
   - 检测"所有下载都在重试"的死锁场景
   - 超过宽限期自动停止
   - 代码: `xet/network/retry_coordinator.py`

4. **Host 优选**
   - DoH 查询 + TCP/HTTP 测速
   - 国内网络优化
   - 代码: `xet/network/host_optimizer.py`

### 3.2 Rust 独有亮点（值得学习）

1. **单例飞行模式 (Single-flight)**
   - XorbBlock 下载去重
   - 使用 `OnceCell` 实现

2. **渐进式预取**
   - 初始预取 2 个小块快速启动
   - 根据完成速率动态调整

3. **零拷贝数据传递**
   - 使用 `Bytes` (Arc-based)
   - Python GIL 限制收益

### 3.3 xet.py 独有亮点（值得学习）

1. **水位线预取控制**
   - 低水位 48MB、高水位 192MB
   - 内存占用可控

2. **全局单 Writer 模式**
   - 并行段共享写盘线程
   - 避免文件锁竞争

3. **低速持续检测**
   - 滑动窗口计算区间速度
   - 支持断点续传

---

## 四、改进建议清单

### P1: 重要增强（建议 2 周内完成）

#### P1.1 移植 Term 级 Checkpoint

**实现方案**:
```python
# xet/pipeline/checkpoint_manager.py
class CheckpointManager:
    def mark_term_completed(self, file_hash: str, term_idx: int, xorb_hash: str):
        """标记 term 完成（每 10 个 term 保存一次）"""
        self._data["completed_terms"].add((term_idx, xorb_hash))
        if term_idx % 10 == 0:
            self._save()
```

**修改文件**:
- `xet/pipeline/checkpoint_manager.py` (+50 行)
- `xet/pipeline/chunk_assembler.py` (+10 行)

#### P1.2 实现完成速率估算器

**实现方案**:
```python
# xet/pipeline/completion_rate_estimator.py
class CompletionRateEstimator:
    """指数加权移动平均速率估算器"""
    
    def __init__(self, half_life: int = 3):
        self.alpha = 0.5 ** (1.0 / half_life)
        self._value = 0.0
    
    def update(self, bytes_delta: int):
        elapsed = time.time() - self._last_update
        if elapsed > 0:
            instant_rate = bytes_delta / elapsed
            self._value = self.alpha * self._value + (1 - self.alpha) * instant_rate
```

**修改文件**:
- 新建 `xet/pipeline/completion_rate_estimator.py` (+80 行)
- `xet/pipeline/chunk_assembler.py` (+30 行)

### P2: 性能优化（建议 1 个月内完成）

#### P2.1 增强 ACC 的 RTT/带宽预测

**修改文件**:
- `xet/network/adaptive_concurrency.py` (+150 行)
- 新建 `xet/network/online_regression.py` (+100 行)

#### P2.2 .part 文件显示真实进度

**修改文件**:
- `xet/pipeline/chunk_assembler.py` (+15 行)

---

## 五、测试场景清单

### 基于 `~/xet.py/XET测试信息.md`

#### T1: 小文件直接下载 (<256MB)

```bash
export HF_TOKEN="hf_..."
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --mode auto
```

**验证点**:
- 自动选择 direct 模式
- SHA256 校验通过
- 耗时 < 30s

#### T2: 大文件 XET 重建

```bash
xet download ... --mode xet --max-memory-mb 150
```

**验证点**:
- 内存峰值 < 200MB
- 水位线预取生效

#### T3: 断点续传

```bash
# 中断后续传
xet download ... &
PID=$!
sleep 8 && kill -INT $PID
xet download ...  # 续传
```

**验证点**:
- Checkpoint 保存正确
- 跳过已完成 xorb

#### T4: 缓存复用

```bash
# 第二次下载极快
xet download ... --output file1.gguf
xet download ... --output file2.gguf
```

**验证点**:
- 缓存命中 100%
- 实际下载 = 0 字节

---

## 六、实施路线图

### 第1周: P1.1 Term 级 Checkpoint
- Day 1-2: 实现 `CheckpointManager` 扩展
- Day 3: 集成到 `ChunkAssembler`
- Day 4-5: 测试 T3（断点续传）

### 第2周: P1.2 完成速率估算器
- Day 1-2: 实现 `CompletionRateEstimator`
- Day 3: 自适应预取逻辑
- Day 4-5: 测试低速网络

### 第3-4周: P2 性能优化
- 虚拟许可机制
- .part 文件显示
- RTT/带宽预测

---

## 七、总结

### 当前状态评估

xetplus **已实现核心功能完整性**：

**超越部分**:
- ✅ 模块化架构
- ✅ Chunk-level 缓存
- ✅ 全局重试协调器
- ✅ Host 优选

**待补齐部分**:
- ⚠️ Term 级 checkpoint
- ⚠️ 完成速率估算器
- ⚠️ RTT/带宽预测

### 优先级建议

**立即实施（2 周）**: P1.1 + P1.2  
→ 达到 xet.py 同等水平

**后续优化（1 个月）**: P2 全部  
→ 超越两个参考版本

---

**报告结束日期**: 2026-06-21  
**维护者**: XET+ Team
