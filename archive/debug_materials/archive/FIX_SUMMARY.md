# Chunk Cache 偏移计算 Bug 修复总结

## 问题描述

### 现象
在启用 chunk cache 时，约 30% 的 xorb 被错误地跳过缓存，日志中出现类似以下的 INFO 级别消息：

```
[CacheAdapter] Chunk 缓存长度不匹配，跳过:
  xorb_hash: edc32dd7fbd51b16...
  merged_range: [0, 540) (长度 540)
  期望 indices: 541
  实际 indices: 113
  差异: 428
```

### 根本原因

**错误假设**: 代码假设一个 xorb 内的 chunks 总是连续的。

**实际情况**: Xorb 可以包含多个不连续的 chunk 范围。

#### 示例

对于 xorb `edc32dd7fbd51b16...`:

- **Fetch infos 的 chunk_range**:
  - `[0, 69)` - 69 个 chunks
  - `[474, 484)` - 10 个 chunks  
  - `[507, 540)` - 33 个 chunks

- **Merged range**: `[0, 540)` - 跨度 540

- **实际包含的 chunks**: 69 + 10 + 33 = **112 个**

- **Chunk_byte_indices 长度**: 113 (112 chunks + 1 个结束偏移)

### 错误的逻辑

```python
# chunk_cache_adapter.py, line 153 (修复前)
merged_range = ChunkRange(
    start=min(cr.start for cr in chunk_ranges),
    end=max(cr.end for cr in chunk_ranges)
)
expected_len = merged_range.length() + 1  # ❌ 假设连续
```

这会计算出 `expected_len = 541`，但实际只有 113 个索引。

### 正确的逻辑

```python
# chunk_cache_adapter.py, line 153-154 (修复后)
# 修复：不能假设 chunks 连续，应该用所有 ranges 的长度之和
total_chunks = sum(cr.length() for cr in chunk_ranges)
expected_len = total_chunks + 1  # ✅ 使用实际 chunks 数量
```

这会正确计算出 `expected_len = 113`。

## 受影响的 Xorb

根据测试文件分析，10 个 xorb 中有 3 个受此 bug 影响：

| Xorb Hash (前16位) | Chunk Ranges | Merged Range | 实际 Chunks | 间隙 |
|-------------------|--------------|--------------|------------|------|
| `edc32dd7fbd51b16` | `[(0,69), (474,484), (507,540)]` | `[0, 540)` | 112 | `[69,474)`, `[484,507)` |
| `f52ace46e9559367` | `[(0,41), (104,155)]` | `[0, 155)` | 92 | `[41,104)` |
| `33d17623391c6d2b` | `[(118,409), (419,436)]` | `[118, 436)` | 308 | `[409,419)` |

## 修复方案

### 代码变更

**文件**: `/data/data/com.termux/files/home/xetplus/xet/pipeline/chunk_cache_adapter.py`

#### 变更 1: 修复偏移计算 (line 153-154)

```diff
- expected_len = merged_range.length() + 1
+ # 修复：不能假设 chunks 连续，应该用所有 ranges 的长度之和
+ total_chunks = sum(cr.length() for cr in chunk_ranges)
+ expected_len = total_chunks + 1
```

#### 变更 2: 更新日志级别和消息 (line 154-173)

```diff
  if len(chunk_byte_indices) != expected_len:
-     # 非连续的 chunk ranges 是正常的，只记录 INFO
-     logger.info(
-         f"[CacheAdapter] Chunk 缓存长度不匹配，跳过:\n"
+     # 这种情况现在应该很罕见（说明 xorb 数据本身有问题）
+     logger.warning(
+         f"[CacheAdapter] ⚠️  Chunk 缓存数据异常:\n"
          f"  xorb_hash: {xorb_hash[:16]}...\n"
-         f"  merged_range: {merged_range} (长度 {merged_range.length()})\n"
+         f"  fetch_infos 数量: {len(fetch_infos)}"
      )
+     for idx, fi in enumerate(fetch_infos):
+         logger.warning(
+             f"    [{idx}] chunk_range: {fi.chunk_range.start}-{fi.chunk_range.end} "
+             f"(长度 {fi.chunk_range.length()})"
+         )
+     logger.warning(
+         f"  总 chunks: {total_chunks}\n"
          f"  期望 indices: {expected_len}\n"
          f"  实际 indices: {len(chunk_byte_indices)}\n"
          f"  差异: {expected_len - len(chunk_byte_indices)}\n"
-         f"  结论: 跳过缓存（非连续 chunk ranges）"
+         f"  结论: 跳过缓存（xorb 数据可能损坏）"
      )
      return
```

**理由**:
- 修复后，长度不匹配现在表示**真正的数据异常**（而不是预期的非连续 chunks）
- 提升日志级别从 INFO 到 WARNING，因为这是异常情况
- 更详细的日志输出，帮助诊断真正的数据问题

## 验证

### 离线验证

使用 `debug_materials/test_fix.py` 验证修复逻辑：

```bash
$ cd debug_materials
$ python test_fix.py
```

**结果**:
- 旧逻辑: 7/10 通过 (70.0%)
- 新逻辑: 10/10 通过 (100.0%)
- 缓存命中率提升: +30.0%

### 集成测试

使用 `test_chunk_cache_integration.py` 进行完整的端到端测试：

```bash
$ cd /data/data/com.termux/files/home/xetplus
$ python test_chunk_cache_integration.py --proxy http://127.0.0.1:12334
```

**验证项**:
1. ✅ 所有 10 个 xorb 成功缓存（无跳过）
2. ✅ 文件重组成功
3. ✅ SHA256 校验通过

## 影响

### 性能提升
- 修复前: 30% 的 xorb 被错误跳过缓存
- 修复后: 所有有效 xorb 都能正常缓存
- 预期缓存命中率提升约 30%

### 兼容性
- ✅ 向后兼容：不影响现有缓存数据
- ✅ 不破坏连续 chunk ranges 的处理
- ✅ 仅修复了错误的验证逻辑

## 相关文件

### 修复的代码
- `/data/data/com.termux/files/home/xetplus/xet/pipeline/chunk_cache_adapter.py`

### 测试和分析工具
- `debug_materials/analyze_offset_bug.py` - Bug 分析脚本
- `debug_materials/test_fix.py` - 离线验证脚本
- `test_chunk_cache_integration.py` - 集成测试脚本

### 调试材料
- `debug_materials/reconstruction.json` - Reconstruction 元数据
- `debug_materials/xorb_analysis.json` - 所有 xorb 的分析数据
- `debug_materials/xorbs/*.bin` - 解压后的 xorb 数据

## 技术细节

### Chunk 索引的含义

`chunk_byte_indices` 是一个长度为 `N+1` 的数组，其中 `N` 是 xorb 内实际包含的 chunk 数量：

- `chunk_byte_indices[i]`: 第 i 个 chunk 在 xorb 解压数据中的起始字节偏移
- `chunk_byte_indices[N]`: 解压数据的总长度（最后一个 chunk 的结束偏移）

### 为什么会有非连续的 Chunk Ranges?

这是 XET 文件格式的正常特性：

1. **文件重组优化**: 同一个 xorb 可以被多个文件的不同部分引用
2. **存储效率**: 相似的数据块会被打包到同一个 xorb，即使它们在文件中位置不连续
3. **增量更新**: 文件修改后，只有变化的部分会生成新 xorb

## 教训

1. **不要假设数据布局**: 即使看起来合理的假设（chunks 连续）也可能是错误的
2. **离线调试材料很有价值**: 能够下载并分析真实数据大大加速了问题定位
3. **日志级别要准确**: INFO vs WARNING 的选择会影响问题的可见性
4. **验证要全面**: 既需要单元测试（test_fix.py），也需要集成测试（test_chunk_cache_integration.py）

## 后续建议

1. **监控缓存性能**: 在生产环境中监控 chunk cache 的命中率
2. **添加单元测试**: 为 `ChunkCacheAdapter` 添加覆盖非连续 chunk ranges 的测试用例
3. **文档更新**: 在代码注释中明确说明 chunk_byte_indices 的语义和非连续 ranges 的正常性

---

**修复日期**: 2026-06-21  
**修复版本**: commit 即将创建  
**相关 Issue**: N/A (离线调试发现)
