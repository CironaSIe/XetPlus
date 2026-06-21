# XET+ CLI 完整测试套件规划

## 📊 测试进度总览

```
测试阶段      状态      进度    说明
═══════════════════════════════════════════════════════════════
P0 - 核心功能  ✅ 完成   5/5    基础下载、revision、错误处理、进度显示
P1 - 重要功能  ⚪ 未开始  0/8    批量、缓存、断点续传等
P2 - 高级功能  ⚪ 未开始  0/6    内存控制、性能优化等
P3 - 集成测试  ⚪ 未开始  0/4    完整工作流、端到端
```

---

## 🎯 P0 - 核心功能测试（必须完成）

**目标**: 验证最基本的下载功能正常工作  
**脚本**: `test_cli_p0_core_v2.sh`  
**执行时间**: 2026-06-21  
**实际耗时**: ~20 分钟  
**测试报告**: `P0_TEST_REPORT.md`

### 测试用例列表

1. ✅ **TC-P0-01: 基础下载**
   - 描述: 使用 user/repo/file 格式下载单个文件
   - 验证: 文件大小 (105,467,232 bytes)、SHA256
   - 状态: **通过** - XET 重建模式正常工作

2. ✅ **TC-P0-02: revision 参数**
   - 描述: 使用 --revision 指定 commit hash
   - 验证: 正确使用指定 revision (45ce642d3fab...)
   - 状态: **通过** - revision 功能正常

3. ✅ **TC-P0-03: 默认 main 分支**
   - 描述: 不指定 revision，使用默认 main
   - 验证: 正常下载
   - 状态: **通过** - 默认行为正确

4. ✅ **TC-P0-04: 错误处理**
   - 描述: 尝试下载不存在的文件
   - 验证: 正确的错误信息 ("文件不是 XET 格式") 和退出码
   - 状态: **通过** - 错误处理正确 (测试脚本有小问题)

5. ✅ **TC-P0-05: 进度显示**
   - 描述: 验证进度条和速度显示
   - 验证: 日志包含进度信息 (Xorb: 10/10 | Seg: 14/14)
   - 状态: **通过** - 进度显示完善 (测试脚本有小问题)

---

## 🎯 P1 - 重要功能测试（应该完成）

**目标**: 验证重要的高级功能
**脚本**: `test_cli_p1_advanced.sh`
**预计时间**: 30-40 分钟

### 测试用例列表

1. ⚪ **TC-P1-01: 批量下载（--include）**
   ```bash
   xet download user/repo --include "*.gguf" --token <token> -o output/
   ```
   - 验证: 列出所有匹配文件
   - 验证: 跳过非 XET 文件
   - 验证: 所有 XET 文件下载成功
   - 预计时间: 5-10 分钟

2. ⚪ **TC-P1-02: 断点续传（--resume）**
   ```bash
   # 第一次下载（中断）
   xet download <file> -o resume.gguf &
   sleep 10 && kill -INT $PID
   
   # 第二次下载（恢复）
   xet download <file> --resume -o resume.gguf
   ```
   - 验证: checkpoint 文件存在
   - 验证: 不重新下载已完成部分
   - 验证: 最终文件完整
   - 预计时间: 5 分钟

3. ⚪ **TC-P1-03: 禁用断点续传（--no-resume）**
   ```bash
   xet download <file> --no-resume -o no_resume.gguf
   ```
   - 验证: 不创建 checkpoint
   - 验证: 从头开始下载
   - 预计时间: 3 分钟

4. ⚪ **TC-P1-04: 缓存功能（默认启用）**
   ```bash
   # 第一次下载（构建缓存）
   xet download <file> -o cached1.gguf
   
   # 第二次下载（使用缓存）
   xet download <file> -o cached2.gguf
   ```
   - 验证: 缓存目录存在
   - 验证: 第二次下载更快
   - 验证: 缓存命中率 > 0%
   - 预计时间: 6 分钟

5. ⚪ **TC-P1-05: 禁用缓存（--no-cache）**
   ```bash
   xet download <file> --no-cache -o no_cache.gguf
   ```
   - 验证: 不创建缓存文件
   - 验证: 不读取缓存
   - 预计时间: 3 分钟

6. ⚪ **TC-P1-06: 保留缓存（--keep-cache）**
   ```bash
   xet download <file> --keep-cache -o keep.gguf
   ```
   - 验证: 下载完成后缓存仍存在
   - 预计时间: 3 分钟

7. ⚪ **TC-P1-07: 网络优化（--optimize-hosts）**
   ```bash
   xet download <file> --optimize-hosts --proxy <proxy> -o optimized.gguf
   ```
   - 验证: 显示 HOST 优选过程
   - 验证: 显示优选结果
   - 预计时间: 5 分钟

8. ⚪ **TC-P1-08: 并发控制（--concurrency）**
   ```bash
   xet download <file> --concurrency 8 -o concurrent.gguf
   ```
   - 验证: 使用指定的并发数
   - 预计时间: 3 分钟

---

## 🎯 P2 - 高级功能测试（可选完成）

**目标**: 验证性能优化和高级参数
**脚本**: `test_cli_p2_performance.sh`
**预计时间**: 20-30 分钟

### 测试用例列表

1. ⚪ **TC-P2-01: 低内存模式**
   ```bash
   xet download <file> --max-memory-mb 100 --prefetch-low 20 --prefetch-high 80 -o low_mem.gguf
   ```
   - 验证: 内存使用不超过限制
   - 验证: 下载成功
   - 预计时间: 5 分钟

2. ⚪ **TC-P2-02: 分段下载**
   ```bash
   xet download <file> --segment-size 256MB --parallel-segments 2 -o segmented.gguf
   ```
   - 验证: 使用指定分段大小
   - 验证: 并行下载段
   - 预计时间: 5 分钟

3. ⚪ **TC-P2-03: 自定义 DNS**
   ```bash
   xet download <file> --optimize-hosts --dns-servers "https://dns.google/dns-query" -o dns.gguf
   ```
   - 验证: 使用自定义 DNS
   - 预计时间: 5 分钟

4. ⚪ **TC-P2-04: 重试控制**
   ```bash
   xet download <file> --retry-max 3 -o retry.gguf
   ```
   - 验证: 重试次数不超过限制
   - 预计时间: 3 分钟

5. ⚪ **TC-P2-05: Checkpoint 间隔**
   ```bash
   xet download <file> --checkpoint-interval 5 -o checkpoint.gguf
   ```
   - 验证: 按指定间隔保存 checkpoint
   - 预计时间: 5 分钟

6. ⚪ **TC-P2-06: 并行写入（实验性）**
   ```bash
   xet download <file> --parallel-write --buffer-mb 64 -o parallel_write.gguf
   ```
   - 验证: 使用并行写入
   - 验证: 性能提升
   - 预计时间: 5 分钟

---

## 🎯 P3 - 集成测试（完整流程）

**目标**: 验证完整的使用场景
**脚本**: `test_cli_p3_integration.sh`
**预计时间**: 30-40 分钟

### 测试用例列表

1. ⚪ **TC-P3-01: info 命令**
   ```bash
   xet info user/repo/file.gguf --token <token>
   ```
   - 验证: 显示 Xet Hash
   - 验证: 显示文件大小
   - 验证: 显示 SHA256
   - 预计时间: 1 分钟

2. ⚪ **TC-P3-02: config 命令**
   ```bash
   xet config xet.token test_token
   xet config --list
   xet config --unset xet.token
   ```
   - 验证: 配置保存成功
   - 验证: 配置显示正确
   - 验证: 配置删除成功
   - 预计时间: 2 分钟

3. ⚪ **TC-P3-03: 完整下载工作流**
   ```bash
   # 配置
   xet config xet.token <token>
   xet config network.concurrency 8
   
   # 查看信息
   xet info user/repo/file.gguf
   
   # 下载
   xet download user/repo/file.gguf --optimize-hosts -o output.gguf
   ```
   - 验证: 完整流程无错误
   - 预计时间: 10 分钟

4. ⚪ **TC-P3-04: 批量下载 + 断点续传**
   ```bash
   # 批量下载（中断）
   xet download user/repo --include "*.gguf" -o batch/ &
   sleep 30 && kill -INT $PID
   
   # 恢复下载
   xet download user/repo --include "*.gguf" --resume -o batch/
   ```
   - 验证: 批量下载可中断
   - 验证: 恢复后继续下载
   - 预计时间: 15 分钟

---

## 📊 测试执行计划

### 第一阶段: P0 核心功能（✅ 已完成）
- [x] 创建测试脚本
- [x] 执行测试 1-5
- [x] 分析测试结果
- [x] 生成测试报告
- [ ] 修复测试脚本小问题 (local 变量声明、test4 退出码逻辑)
- **完成日期**: 2026-06-21

### 第二阶段: P1 重要功能（本周）
- [ ] 创建 P1 测试脚本
- [ ] 执行所有 8 个测试
- [ ] 验证测试结果
- [ ] 修复发现的问题
- **预计完成**: 2-3 天

### 第三阶段: P2 高级功能（下周）
- [ ] 创建 P2 测试脚本
- [ ] 执行所有 6 个测试
- [ ] 性能基准测试
- [ ] 优化性能问题
- **预计完成**: 3-4 天

### 第四阶段: P3 集成测试（下周）
- [ ] 创建 P3 测试脚本
- [ ] 执行完整工作流测试
- [ ] 端到端验证
- [ ] 文档更新
- **预计完成**: 2-3 天

### 第五阶段: CI/CD 集成（下周末）
- [ ] 配置 CI 环境
- [ ] 集成测试到 CI
- [ ] 自动化测试执行
- [ ] 覆盖率报告
- **预计完成**: 1-2 天

---

## 📈 测试覆盖目标

```
测试级别          当前    目标    差距
═══════════════════════════════════════
P0 核心功能      100%    100%     0%  ✅
P1 重要功能        0%     90%    90%
P2 高级功能        0%     70%    70%
P3 集成测试        0%     80%    80%
───────────────────────────────────────
总体覆盖率        22%     85%    63%
```

---

## 🎯 各阶段交付物

### P0 阶段
- ✅ `test_cli_p0_core_v2.sh` - 核心功能测试脚本（改进版）
- ✅ `P0_TEST_REPORT.md` - P0 测试报告
- ⚠️ 测试脚本小问题待修复 (不影响功能)

### P1 阶段
- ⚪ `test_cli_p1_advanced.sh` - 高级功能测试脚本
- ⚪ `test_p1_report.md` - P1 测试报告
- ⚪ 问题修复（如有）

### P2 阶段
- ⚪ `test_cli_p2_performance.sh` - 性能测试脚本
- ⚪ `test_p2_report.md` - P2 测试报告
- ⚪ `performance_baseline.md` - 性能基线

### P3 阶段
- ⚪ `test_cli_p3_integration.sh` - 集成测试脚本
- ⚪ `test_p3_report.md` - P3 测试报告
- ⚪ `E2E_TEST_GUIDE.md` - 端到端测试指南

### CI/CD 阶段
- ⚪ `.github/workflows/test.yml` - CI 配置
- ⚪ `coverage_report.html` - 覆盖率报告
- ⚪ `CI_CD_GUIDE.md` - CI/CD 使用指南

---

## 💡 测试最佳实践

### 1. 每个测试独立运行
- 不依赖其他测试的状态
- 清理自己的临时文件
- 使用唯一的输出文件名

### 2. 清晰的进度显示
```bash
[1/5] TC-P0-01: 基础下载                      [运行中]
[2/5] TC-P0-02: revision 参数                 [队列中]
[3/5] TC-P0-03: 默认 main 分支                [队列中]
```

### 3. 详细的失败信息
```bash
❌ TC-P0-04: 错误处理 [失败]
   原因: 错误信息不清晰
   期望: "文件不存在" 或 "不是 XET 格式"
   实际: "下载失败"
   日志: test_output/test4.log
```

### 4. 可重复执行
- 自动清理旧的测试输出
- 支持 --clean 参数强制清理
- 支持 --continue 参数继续未完成测试

---

## 🔧 测试工具增强

### 计划增强功能
1. **进度条显示**: 显示当前测试/总测试数
2. **实时状态**: 显示每个测试的状态（运行中/完成/失败）
3. **时间估算**: 显示剩余时间
4. **并行执行**: 支持同时运行多个测试（可选）
5. **选择性运行**: 支持只运行特定测试
6. **HTML 报告**: 生成可视化测试报告

---

## 📋 测试用例总览

```
优先级  类别        用例数  状态       预计时间
═══════════════════════════════════════════════
P0      核心功能      5     100% 完成  15-20分钟 ✅
P1      重要功能      8     0% 完成    30-40分钟
P2      高级功能      6     0% 完成    20-30分钟
P3      集成测试      4     0% 完成    30-40分钟
───────────────────────────────────────────────
总计                 23     22% 完成   95-130分钟
```

---

**创建日期**: 2026-06-21  
**更新日期**: 2026-06-21  
**状态**: ✅ P0 完成 - 准备进入 P1 阶段  
**下一步**: 创建 P1 测试脚本并执行
