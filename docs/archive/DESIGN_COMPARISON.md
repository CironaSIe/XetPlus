# xet.py vs XET+ 设计机制对比分析

## 1. IP优选（HOST Optimization）

### xet.py 的设计
- **自动执行**: 通过 `create_optimized_session()` 在下载前自动执行
- **DomainAwareSession**: 根据域名动态切换代理（优选域名用直连，其他用代理）
- **两层缓存**: 
  - DoH缓存: 24小时（IP列表）
  - 优选缓存: 1小时（最优IP+速度）
- **集成到Session**: Session创建时就完成优选，对后续代码透明

### XET+ 的实现
- ✅ **手动触发**: 需要用户指定 `--optimize-hosts`
- ❌ **缺少DomainAwareSession**: 只做了monkey-patch，没有按域名动态切换代理
- ✅ **两层缓存**: 已实现
- ❌ **未集成到Session创建**: 需要在download命令中手动调用

### 问题与改进建议
1. **缺少DomainAwareSession**: 应实现类似的按域名动态代理机制
2. **自动执行vs手动**: xet.py默认执行优选更方便，但XET+的手动方式给用户更多控制
3. **建议**: 添加配置项支持"默认启用IP优选"

---

## 2. 并行写入（Parallel Write）

### xet.py 的设计
- **GlobalWriter模式**: 所有segment共享一个writer线程
- **队列写入**: 通过 `queue.Queue` 收集 (offset, data) 然后写入
- **顺序保证**: Writer线程按offset顺序写入，避免文件碎片
- **参数**: `--parallel-segments N --parallel-write`

### XET+ 的实现
- ✅ **GlobalWriter模式**: 已在 `SegmentedReconstructor._writer_worker()` 实现
- ✅ **队列写入**: 已实现 `_write_queue`
- ✅ **并行段下载**: 已实现 `--parallel-segments`
- ❌ **缺少 `--parallel-write` 参数**: 参数名不一致

### 问题与改进建议
1. **参数命名**: 应该添加 `--parallel-write` 参数（或说明默认已启用）
2. ✅ **实现完整**: GlobalWriter模式已正确实现

---

## 3. Checkpoint保存机制

### xet.py 的设计
- **增量保存**: 每N个term保存一次（默认10）
- **文件命名**: `target.part.xet_meta.json`（非分段）/ `target.part.segments.json`（分段）
- **分段模式**: 段级checkpoint优先于xorb级
- **清理**: 成功后自动删除checkpoint

### XET+ 的实现
- ✅ **xorb级checkpoint**: 已实现 `CheckpointManager`
- ✅ **segment级checkpoint**: 已实现 `SegmentCheckpointManager`
- ✅ **增量保存**: 每个segment完成后保存
- ✅ **清理**: 成功后清理

### 问题与改进建议
- ✅ **实现完整**: checkpoint机制完整

---

## 4. 日志系统

### xet.py 的设计
- **双层日志**: 
  - 控制台: 可通过 `--log-level` 控制（默认INFO）
  - 文件: 始终DEBUG级别，保存所有日志
- **文件位置**: `~/.cache/xet/logs/xet_YYYYMMDD_HHMMSS.log`
- **自动清理**: 保留最近1个日志文件
- **第三方库抑制**: urllib3等设置WARNING

### XET+ 的实现
- ✅ **双层日志**: 已实现
- ✅ **控制台级别可控**: `-v`, `-vv`, `--log-level`
- ✅ **文件始终DEBUG**: 已实现
- ✅ **文件位置**: `~/.xet/logs/xet_YYYYMMDD_HHMMSS.log`
- ✅ **自动清理**: 保留最近10个日志文件（比xet.py更合理）
- ✅ **第三方库抑制**: 已实现

### 问题与改进建议
- ✅ **实现完整**: 日志系统完善，甚至优于xet.py

---

## 5. 缓存机制（Xorb Disk Cache）

### xet.py 的设计
- **磁盘缓存**: xorb下载后缓存到 `~/.cache/xet/xorbs/`
- **缓存命名**: `{xorb_hash}_{range_start}_{range_end}.xorb`
- **大小检查**: 加载缓存时验证大小，防止部分下载污染
- **清理**: `--keep-cache` 控制是否保留
- **分段模式**: 禁用磁盘缓存（避免冲突）

### XET+ 的实现
- ❌ **未实现磁盘缓存**: 当前没有xorb级别的磁盘缓存
- ✅ **segment级checkpoint**: 可以部分替代（但不是完整的xorb缓存）

### 问题与改进建议
1. **缺少xorb磁盘缓存**: 这是一个重要优化点
2. **建议**: 实现xorb磁盘缓存，可以加速重复下载

---

## 6. 预取机制（Prefetch）

### xet.py 的设计
- **水位线控制**: 
  - 低水位（默认48MB）: 低于此时补充预取
  - 高水位（默认192MB）: 高于此时暂停预取
- **预取数量**: 单次最多预取8个xorb
- **内存控制**: 通过水位线控制内存占用
- **参数**: `--prefetch-low`, `--prefetch-high`, `--prefetch-max`

### XET+ 的实现
- ❌ **未实现预取**: 当前是按需下载，没有预取机制
- ✅ **并发下载**: 通过并发控制间接实现类似效果

### 问题与改进建议
1. **缺少预取机制**: 对于大文件可能影响性能
2. **建议**: 可以作为性能优化项，但优先级较低

---

## 7. 模式选择（Mode Selection）

### xet.py 的设计
- **auto模式**: 自动选择（<256MB用direct，>=256MB用xet）
- **xet模式**: 强制使用XET reconstruction
- **direct模式**: 强制使用presigned URL直接下载
- **参数**: `--mode {auto,xet,direct}`

### XET+ 的实现
- ❌ **只有xet模式**: 当前只支持XET reconstruction
- ❌ **缺少direct模式**: 小文件直接下载可能更快
- ✅ **自动分段**: >1GB自动启用分段下载

### 问题与改进建议
1. **缺少direct模式**: 小文件(<100MB)用direct更快
2. **建议**: 实现direct模式，并添加auto模式自动选择

---

## 8. 缓冲控制（Buffer Management）

### xet.py 的设计
- **写缓冲**: `--buffer-mb` 控制每文件写缓冲（默认32MB）
- **总上限**: 全局缓冲上限512MB
- **内存受限**: `--buffer-mb 8` 用于低内存环境

### XET+ 的实现
- ❌ **未实现显式缓冲控制**: 依赖操作系统的缓冲
- ✅ **队列缓冲**: write_queue有maxsize限制

### 问题与改进建议
1. **缺少用户可控的缓冲参数**: 对低内存环境不友好
2. **建议**: 添加 `--buffer-size` 参数控制队列大小

---

## 9. 错误处理与重试

### xet.py 的设计
- **RetryCoordinator**: 全局重试协调器
  - 单个xorb无限重试
  - 全局监控：所有xorb都在重试时触发停止
  - 宽限期：120秒
- **LowSpeedTimeout**: 低速检测自动重试
- **URLRefresh**: 403时刷新URL

### XET+ 的实现
- ✅ **URLRefreshCoordinator**: 已实现
- ✅ **AdaptiveConcurrencyController**: 已实现
- ✅ **LowSpeedTimeout**: 已实现
- ❌ **缺少RetryCoordinator**: 没有全局重试协调

### 问题与改进建议
1. **缺少全局重试协调**: 可能导致永久重试
2. **建议**: 实现RetryCoordinator或类似机制

---

## 10. 进度显示

### xet.py 的设计
- **多层进度**: 
  - 文件级进度
  - 段级进度（分段模式）
  - xorb级进度
- **实时速度**: 下载速度显示
- **ETA**: 预计剩余时间

### XET+ 的实现
- ✅ **进度条**: 已实现 `ProgressTracker`
- ✅ **多种样式**: rich/simple/quiet
- ⚠️ **进度细节**: 可能不如xet.py详细

### 问题与改进建议
- ✅ **基本完善**: 进度显示已实现

---

## 总结对比

| 功能模块 | xet.py | XET+ | 优先级 | 建议 |
|---------|--------|------|--------|------|
| **IP优选** | ✅ 自动 + DomainAwareSession | ⚠️ 手动 + monkey-patch | 🔴 高 | 实现DomainAwareSession |
| **并行写入** | ✅ | ✅ | ✅ 完成 | - |
| **Checkpoint** | ✅ | ✅ | ✅ 完成 | - |
| **日志系统** | ✅ | ✅ (更优) | ✅ 完成 | - |
| **Xorb缓存** | ✅ | ❌ | 🟡 中 | 实现磁盘缓存 |
| **预取机制** | ✅ | ❌ | 🟢 低 | 性能优化项 |
| **Direct模式** | ✅ | ❌ | 🟡 中 | 小文件加速 |
| **缓冲控制** | ✅ | ❌ | 🟢 低 | 低内存友好 |
| **重试协调** | ✅ | ❌ | 🟡 中 | 避免死循环 |
| **进度显示** | ✅ | ✅ | ✅ 完成 | - |

---

## 关键差距与改进路线图

### 🔴 高优先级（核心功能差距）
1. **DomainAwareSession**: 按域名动态切换代理
2. **自动IP优选**: 默认启用或配置文件控制

### 🟡 中优先级（性能和稳定性）
3. **Xorb磁盘缓存**: 加速重复下载
4. **Direct模式**: 小文件快速下载
5. **RetryCoordinator**: 全局重试协调

### 🟢 低优先级（优化项）
6. **预取机制**: 进一步性能优化
7. **缓冲控制**: 低内存环境友好
8. **更详细的进度**: 段级/xorb级进度

---

## 结论

**XET+ 当前状态**: 
- ✅ 核心下载功能：100%完整
- ✅ 分段下载：完整实现
- ✅ 断点续传：segment级更优
- ⚠️ IP优选：功能完整但集成方式不如xet.py
- ❌ 缺少：xorb缓存、direct模式、预取机制

**功能完整度**: 约85%（核心功能100%，优化功能70%）

**下一步建议**:
1. 实现DomainAwareSession（最重要）
2. 实现xorb磁盘缓存
3. 添加direct模式
4. 其他优化项可选实现
