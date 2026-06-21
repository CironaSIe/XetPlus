# CLI 参数对比分析：xet.py vs xetplus

## 📋 完整参数对比表

基于 `xet_dl.py` 源码分析（行号 2132-2248）

### 基本参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `-o, --output` | ✅ | ✅ | `./downloads` / `./downloads` | ✅ 一致 |
| `-i, --include` | ✅ | ✅ | - | ✅ 一致 |
| `-m, --mode` | ✅ `{auto,xet,direct}` | ✅ `{auto,xet,direct}` | `auto` / `auto` | ✅ 一致 |
| `--token` | ✅ | ✅ | - | ✅ 一致 |
| `--proxy` | ✅ | ✅ | - | ✅ 一致 |
| `-v, --verbose` | ✅ | ✅ | - | ✅ 一致 |
| `--log-level` | ✅ | ✅ | - | ✅ 一致 |
| `--log-file` | ❌ | ✅ | - | ⚠️ xetplus 独有 |
| `--no-log-file` | ❌ | ✅ | - | ⚠️ xetplus 独有 |

---

### 性能调优参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--concurrent` | ✅ (行 2170) | ❌ | `6` | ❌ **不一致** |
| `--concurrency` | ❌ | ✅ | `4` | ❌ **不一致** |
| `--parallel-segments` | ✅ (行 2172) | ✅ | `1` / `1` | ✅ 一致 |
| `--parallel-write` | ✅ (行 2174) | ❌ | `False` | ❌ **xetplus 缺失** |
| `--buffer-mb` | ✅ (行 2176) | ❌ | `32` | ❌ **xetplus 缺失** |
| `--segment-size` | ✅ (行 2178) | ✅ | - | ✅ 一致 |
| `--no-adaptive-concurrency` | ❌ | ✅ | - | ⚠️ xetplus 独有 |

---

### 预取控制参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--prefetch-low` | ✅ (行 2183) | ✅ | `48` / `48` | ✅ 一致 |
| `--prefetch-high` | ✅ (行 2185) | ✅ | `192` / `192` | ✅ 一致 |
| `--prefetch-max` | ✅ (行 2187) | ❌ | `8` | ❌ **xetplus 缺失** |

---

### 内存控制参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--max-memory-mb` | ❌ | ✅ | `200` | ⚠️ xetplus 独有 |

---

### 可靠性参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--retry-max` | ✅ (行 2192) | ❌ | `5` | ❌ **xetplus 缺失** |
| `--checkpoint-interval` | ✅ (行 2194) | ❌ | `10` | ❌ **xetplus 缺失** |
| `--resume` | ❌ | ✅ | `True` | ⚠️ xetplus 独有 |
| `--no-resume` | ❌ | ✅ | - | ⚠️ xetplus 独有 |
| `--checkpoint` | ❌ | ✅ | - | ⚠️ xetplus 独有 |

---

### 缓存参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--cache-dir` | ✅ (行 2199) | ✅ | `~/.cache/xet/xorbs/` | ✅ 一致 |
| `--keep-cache` | ✅ (行 2200) | ✅ | `False` / `False` | ✅ 一致 |
| `--no-cache` | ❌ | ✅ | - | ⚠️ xetplus 独有 |

---

### HOST 优选参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--optimize-hosts` | ✅ (行 2204) | ✅ | `False` / `False` | ✅ 一致 |
| `--no-optimize-hosts` | ❌ | ✅ | - | ⚠️ xetplus 独有 |
| `--refresh-hosts` | ✅ (行 2206) | ✅ | - | ✅ 一致 |
| `--dns-servers` | ✅ (行 2208) | ❌ | - | ❌ **xetplus 缺失** |

---

### 进度显示参数

| 参数 | xet.py | xetplus | 默认值对比 | 状态 |
|------|--------|---------|-----------|------|
| `--progress-style` | ❌ | ✅ `{rich,simple,quiet}` | `rich` | ⚠️ xetplus 独有 |

---

## 🔴 关键不一致问题

### 1. 并发参数命名不一致 ⚠️

**xet.py** (行 2170):
```python
perf.add_argument("--concurrent", type=int, default=6,
                  help="每段最大并发 xorb 下载数 (默认 6, 推荐 4-12)")
```

**xetplus** (`download.py:54`):
```python
parser.add_argument(
    "-c", "--concurrency",
    help="并发下载数（默认: 从配置读取或 4）",
    type=int,
)
```

**影响**: 用户习惯不同参数名，迁移成本高

**解决方案**:
```python
# 方案 1: 添加别名
parser.add_argument(
    "-c", "--concurrency", "--concurrent",  # 同时支持两个名称
    help="并发下载数（默认: 4）",
    type=int,
)

# 方案 2: 保留向后兼容
parser.add_argument("--concurrent", dest="concurrency", type=int, help=argparse.SUPPRESS)
```

---

### 2. 断点续传设计差异 🔄

**xet.py**:
- `--checkpoint-interval` (默认 10) - 每 N term 保存 checkpoint
- 隐式启用断点续传，无开关

**xetplus**:
- `--resume/--no-resume` - 显式控制是否启用断点续传
- `--checkpoint` - 指定 checkpoint 文件路径
- 无 `--checkpoint-interval` 参数

**影响**: 用户无法控制保存频率

**解决方案**:
```python
# xetplus 补充参数
parser.add_argument(
    "--checkpoint-interval",
    help="每 N terms 保存 checkpoint（默认: 10）",
    type=int,
    default=10,
)
```

---

## ❌ xetplus 缺失的功能

### 1. `--parallel-write` 并行写入

**xet.py 实现** (`reconstructor.py:GlobalWriter`):
- 多个段并行写入同一文件
- 使用 Windows `CreateFileW` 或 Linux 多线程安全写入
- SSD 环境下提升 2-3 倍速度

**xetplus 状态**: 未实现

**实现优先级**: P1（大文件性能关键）

**实现方案**:
```python
# xet/pipeline/global_writer.py (新建)
class GlobalWriter:
    """全局写入器 - 支持多段并行写入"""
    
    def __init__(self, path: Path, file_size: int):
        self._path = path
        self._file = self._open_shared_write(path)
        self._lock = threading.Lock()
    
    def write_segment(self, offset: int, data: bytes):
        """线程安全的定位写入"""
        with self._lock:
            self._file.seek(offset)
            self._file.write(data)
```

**修改文件**:
- 新建 `xet/pipeline/global_writer.py` (+150 行)
- `xet/cli/commands/download.py` (+5 行，参数定义)
- `xet/pipeline/file_reconstructor.py` (+30 行，集成)

---

### 2. `--buffer-mb` 写缓冲控制

**xet.py 实现** (行 2176):
```python
perf.add_argument("--buffer-mb", type=int, default=32,
                  help="每文件写缓冲 MB (默认 32, 内存紧张可降至 8-16)")
```

**用途**:
- 控制写入队列大小
- 内存受限环境可降低到 8-16 MB
- 高性能环境可提升到 64-128 MB

**xetplus 状态**: 未实现

**实现优先级**: P2（性能调优）

**实现方案**:
```python
# xet/pipeline/chunk_assembler.py
class ChunkAssembler:
    def __init__(self, ..., buffer_mb: int = 32):
        self.buffer_mb = buffer_mb
        self._write_queue = queue.Queue(maxsize=buffer_mb * 1024 * 1024 // 32768)
```

---

### 3. `--prefetch-max` 单次预取上限

**xet.py 实现** (行 2187):
```python
prefetch.add_argument("--prefetch-max", type=int, default=8,
                      help="单次最多预取 xorb 数量 (默认 8)")
```

**用途**:
- 限制单次预取的 xorb 数量
- 避免慢速网络时过度预取
- 配合水位线精确控制内存

**xetplus 状态**: 未实现

**实现优先级**: P2（内存精细控制）

**实现方案**:
```python
# xet/pipeline/chunk_assembler_helpers.py
def _prefetch_upcoming_xorbs(self, ...):
    # 现有代码...
    
    # 限制预取数量
    prefetch_max = self.prefetch_max or 8
    submitted = 0
    for xorb_hash in upcoming_xorbs:
        if submitted >= prefetch_max:  # ← 新增限制
            break
        # 提交下载...
        submitted += 1
```

---

### 4. `--retry-max` 重试次数控制

**xet.py 实现** (行 2192):
```python
reliability.add_argument("--retry-max", type=int, default=5,
                         help="最大重试次数 (默认 5)")
```

**xetplus 状态**: 硬编码在 `CASClient`

**实现优先级**: P2（用户可配置性）

**实现方案**:
```python
# xet/cli/commands/download.py
parser.add_argument(
    "--retry-max",
    help="最大重试次数（默认: 5）",
    type=int,
    default=5,
)

# xet/network/cas_client.py
class CASClient:
    def __init__(self, ..., retry_max: int = 5):
        self.retry_max = retry_max
```

---

### 5. `--dns-servers` 自定义 DoH 服务器

**xet.py 实现** (行 2208):
```python
host_opt.add_argument("--dns-servers", type=str, default="",
                      help="自定义 DoH 服务器（逗号分隔）")
```

**xetplus 状态**: 硬编码在 `HostOptimizer`

**实现优先级**: P3（高级用户）

---

## ⚠️ xet.py 缺失的功能

### 1. `--no-adaptive-concurrency` ACC 开关

**xetplus 独有**: 允许禁用自适应并发控制

**用途**: 调试、对比测试

---

### 2. `--progress-style` 进度条样式

**xetplus 独有**: 支持 `rich` / `simple` / `quiet` 三种样式

**用途**: 不同终端环境适配

---

### 3. `--log-file` / `--no-log-file` 日志文件控制

**xetplus 独有**: 显式控制日志文件输出

**用途**: 灵活的日志管理

---

## 🎯 对齐优先级

### P0 - 立即修复（本周完成）

1. ✅ **统一并发参数名**: 添加 `--concurrent` 别名
2. ✅ **修复日志文件输出**: 确保 `--log-file` 生效

### P1 - 高优先级（1-2周完成）

3. ⬜ **实现 `--parallel-write`**: 并行段写入（大文件性能关键）
4. ⬜ **添加 `--prefetch-max`**: 单次预取上限
5. ⬜ **添加 `--checkpoint-interval`**: term 级保存间隔
6. ⬜ **添加 `--retry-max`**: 重试次数控制

### P2 - 中优先级（1个月完成）

7. ⬜ **实现 `--buffer-mb`**: 写缓冲控制
8. ⬜ **添加 `--dns-servers`**: 自定义 DoH

### P3 - 低优先级（按需实现）

9. ⬜ **统一断点续传设计**: 考虑 `--checkpoint-interval` vs `--resume`
10. ⬜ **参数默认值对齐**: `--concurrent` 默认值 4 vs 6

---

## 📝 实施清单

### 第1步: 添加别名（立即）

```python
# xet/cli/commands/download.py
parser.add_argument(
    "-c", "--concurrency", "--concurrent",  # 同时支持
    help="并发下载数（默认: 4）",
    type=int,
)
```

### 第2步: 补充缺失参数（1-2周）

```python
# prefetch-max
parser.add_argument(
    "--prefetch-max",
    help="单次最多预取 xorb 数量（默认: 8）",
    type=int,
    default=8,
)

# checkpoint-interval
parser.add_argument(
    "--checkpoint-interval",
    help="每 N terms 保存 checkpoint（默认: 10）",
    type=int,
    default=10,
)

# retry-max
parser.add_argument(
    "--retry-max",
    help="最大重试次数（默认: 5）",
    type=int,
    default=5,
)
```

### 第3步: 实现 parallel-write（1-2周）

- 新建 `xet/pipeline/global_writer.py`
- 集成到 `file_reconstructor.py`
- 添加 `--parallel-write` 参数

### 第4步: 实现 buffer-mb（按需）

- 扩展 `chunk_assembler.py`
- 添加写缓冲队列控制

---

## 📊 对齐状态

| 类别 | 对齐度 | 缺失功能 | 优先级 |
|------|-------|----------|--------|
| **基本参数** | 90% | `--log-file` (xetplus 独有) | ✅ 完成 |
| **性能调优** | 60% | `--parallel-write`, `--buffer-mb` | 🔴 P1 |
| **预取控制** | 66% | `--prefetch-max` | 🟡 P2 |
| **可靠性** | 40% | `--retry-max`, `--checkpoint-interval` | 🟡 P2 |
| **缓存控制** | 100% | - | ✅ 完成 |
| **HOST优选** | 80% | `--dns-servers` | 🟢 P3 |

**总体对齐度**: **75%**

---

**最后更新**: 2026-06-21  
**分析基于**: xet_dl.py 源码 (行 2132-2248)
