# 日志系统对比分析：xet.py vs xetplus

## 📊 统计对比

### 日志数量统计

| 项目 | 总日志数 | DEBUG | INFO | WARNING | ERROR |
|------|---------|-------|------|---------|-------|
| **xet.py** | 208 | 104 (50%) | 21 (10%) | 62 (30%) | 21 (10%) |
| **xetplus** | 266 | 97 (36%) | 84 (32%) | 60 (23%) | 25 (9%) |

### 关键发现

1. **xet.py 特点**:
   - DEBUG 占比最高 (50%)，详细调试信息丰富
   - INFO 占比较低 (10%)，用户关键信息较少
   - WARNING 占比较高 (30%)，警告信息较多

2. **xetplus 特点**:
   - INFO 占比显著提升 (32%)，用户友好
   - DEBUG 占比适中 (36%)，平衡详细度和可读性
   - 整体日志数量更多 (266 vs 208)

---

## 🔍 关键日志点对比

### 1. 下载开始/结束

**xet.py** (`reconstructor.py`):
```python
logger.debug(f"[Reconstructor] 开始重建: {file_hash[:20]}..., "
             f"文件大小: {file_size}, terms: {len(recon.terms)}")  # DEBUG 级别

logger.debug(f"[Reconstructor] 重建完成: {len(file_data)} bytes")  # DEBUG 级别
```

**xetplus** (`chunk_assembler.py`):
```python
logger.info(
    f"[ChunkAssembler] 开始组装文件（预取模式）: {output_path}, "
    f"内存限制: {self.max_memory_mb}MB, "
    f"水位线: {self.prefetch_low_mb}-{self.prefetch_high_mb}MB"
)  # INFO 级别

logger.info(
    f"[ChunkAssembler] 文件组装完成: {output_path} "
    f"({total_written} bytes, {len(recon.terms)} terms)"
)  # INFO 级别
```

**差异**:
- xet.py 用 **DEBUG**，xetplus 用 **INFO**
- xetplus 包含更多配置信息（内存限制、水位线）

---

### 2. 下载进度

**xet.py** (`reconstructor.py:224`):
```python
logger.debug(f"[Reconstructor] xorb 下载完成 {completed}/{total}: "
             f"{xorb_hash[:16]}...")  # DEBUG 级别
```

**xetplus** (`chunk_assembler.py:528-534`):
```python
if (term_idx + 1) % 100 == 0:
    cache_mb = sum(len(x.data) for x in self._xorb_cache.values()) / 1024 / 1024
    logger.debug(
        f"[ChunkAssembler] 进度: {term_idx + 1}/{len(recon.terms)} terms, "
        f"缓存: {cache_mb:.1f}MB, "
        f"已写入: {total_written / 1024 / 1024:.1f}MB"
    )  # DEBUG 级别，每 100 term 输出一次
```

**差异**:
- xet.py 每个 xorb 输出一次（频繁）
- xetplus 每 100 term 输出一次（节制）

---

### 3. 缓存命中

**xet.py** (`reconstructor.py`):
```python
logger.debug(f"[Cache] 缓存命中: {xorb_hash[:16]}...")  # DEBUG 级别
```

**xetplus** (`chunk_assembler_helpers.py:79-81`):
```python
logger.info(
    f"[Cache] 从磁盘加载 {loaded_count} 个 xorb ({cache_mb:.1f}MB)"
)  # INFO 级别
```

**差异**:
- xet.py 每个缓存命中都记录（DEBUG）
- xetplus 汇总记录（INFO），更清晰

---

### 4. 断点续传

**xet.py** (`reconstructor.py:784`):
```python
logger.info("[StreamReconstructor] 断点文件无效，将从头开始")  # INFO 级别
```

**xetplus** (`chunk_assembler.py:426-429`):
```python
logger.info(
    f"[ChunkAssembler] 从 checkpoint 恢复: "
    f"跳过前 {start_term_idx} 个 terms ({len(checkpoint.completed_terms)} terms 已完成)"
)  # INFO 级别
```

**差异**:
- xetplus 提供更详细的续传信息（跳过数量、已完成数量）

---

### 5. 错误处理

**xet.py** (`reconstructor.py`):
```python
logger.warning(f"[XorbReady] xorb {xorb_hash[:16]}... 曾缓存但已淘汰, 重新下载")
```

**xetplus** (`chunk_assembler_helpers.py:134`):
```python
logger.error(f"[Download] Xorb {xorb_hash[:16]}... 下载失败: {e}")
```

**差异**:
- xet.py 对失败情况较宽容（WARNING）
- xetplus 对严重错误更严格（ERROR）

---

## ⚠️ xetplus 日志缺失的原因

### 根本问题

测试中发现日志文件完全缺失内容，只有警告信息。经分析：

1. **控制台 handler 输出到 stderr** (`xet/cli/main.py:35`)
   ```python
   console_handler = logging.StreamHandler(sys.stderr)  # ← 输出到 stderr
   ```

2. **后台任务只捕获 stdout**
   ```bash
   # 后台任务只捕获标准输出
   command > output.log  # 缺少 2>&1
   ```

3. **日志文件配置正确但未生效**
   - 配置在 `main.py:50-63` 正确设置了文件 handler
   - 但测试命令未指定 `--log-file` 参数
   - 默认日志目录 `~/.xet/logs/` 可能不存在

---

## 🔧 修复建议

### 1. 修复日志文件输出 (P0)

**方案 1: 确保日志目录存在**
```python
# xet/cli/main.py:get_default_log_file()
def get_default_log_file() -> str:
    log_dir = Path.home() / ".xet" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)  # ✅ 确保目录存在
    # ...
```

**方案 2: 后台任务捕获 stderr**
```bash
# 测试脚本修改
python -m xet.cli.commands.download ... 2>&1 | tee download_test.log
```

**方案 3: 显式指定日志文件**
```bash
python -m xet.cli.commands.download ... --log-file download_test.log
```

---

### 2. 对齐关键日志级别 (P1)

**下载开始/结束**: 统一为 **INFO**
- ✅ xetplus 已正确使用 INFO
- ⚠️ xet.py 使用 DEBUG（改进空间）

**进度信息**: 统一为 **DEBUG** + 节制频率
- ✅ xetplus 每 100 term 输出一次
- ⚠️ xet.py 每个 xorb 输出（太频繁）

**缓存统计**: 统一为 **INFO** + 汇总
- ✅ xetplus 已汇总输出
- ⚠️ xet.py 单个记录（改进空间）

---

### 3. 增强 xetplus 日志 (P2)

**补充缺失的日志点**:
1. **SHA256 验证结果**:
   ```python
   logger.info(f"SHA256 验证通过: {expected_sha256}")
   ```

2. **ACC 调整记录**:
   ```python
   logger.info(f"[ACC] 并发数调整: {old} → {new} (EWMA={rate:.3f})")
   ```

3. **速度统计**:
   ```python
   logger.info(f"下载完成: {size_mb:.2f} MB, 平均速度: {speed_mbps:.2f} MB/s")
   ```

4. **Checkpoint 保存**:
   ```python
   logger.debug(f"[Checkpoint] 保存: term={term_idx}, xorb={xorb_hash[:16]}")
   ```

---

## 📊 日志级别使用规范

基于对比分析，推荐以下规范：

| 级别 | 用途 | 示例 |
|------|------|------|
| **DEBUG** | 内部状态、频繁事件 | xorb 解压、term 处理（每 N 次输出） |
| **INFO** | 关键里程碑、用户关心的进度 | 下载开始/结束、缓存统计、SHA256 验证 |
| **WARNING** | 可恢复错误、降级策略 | 缓存失效、重试警告 |
| **ERROR** | 严重错误、下载失败 | xorb 下载失败、文件写入错误 |

---

## 📝 测试验证清单

- [ ] 修复日志目录创建逻辑
- [ ] 验证后台任务日志文件包含完整日志
- [ ] 对比 xet.py 和 xetplus 的日志输出
- [ ] 确保 INFO 级别包含所有关键进度
- [ ] 确保 DEBUG 级别包含详细调试信息
- [ ] 验证日志频率适中（不过度输出）

---

**最后更新**: 2026-06-21  
**分析基于**: xet.py (208 条日志) vs xetplus (266 条日志)
