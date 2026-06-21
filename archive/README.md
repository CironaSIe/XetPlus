# 归档文件说明

本目录存储已完成工作的历史文件，保持项目根目录整洁。

## 目录结构

### 📁 old_reports/ (10 个文件)
历史工作总结和报告文档
- `CHUNK_CACHE_FIX_COMPLETION.md` - Chunk Cache 修复完成报告
- `CLEANUP_PLAN.md` - 早期清理计划
- `COMPLETION_SUMMARY.md` - 完成总结
- `FINAL_REPORT_2026-06-21.md` - 最终报告
- `SESSION_SUMMARY_2026-06-21_XET_DETECTION.md` - XET检测会话记录
- `WORK_SUMMARY_2026-06-21.md` - 工作总结
- `WORK_SUMMARY_FINAL_2026-06-21.md` - 最终工作总结
- `XET_DETECTION_FIX_SUMMARY.md` - XET检测修复总结
- `CLI_TEST_PLAN.md` - 旧版CLI测试计划（已被根目录的`测试计划.md`取代）
- `PROJECT_STATUS.txt` - 项目状态快照

### 🔧 debug_scripts/ (12 个文件)
调试和验证脚本（已完成任务）
- `debug_chunk_cache.py` - Chunk Cache 调试
- `debug_simple.py` - 简单调试脚本
- `debug_xet_detection.py` - XET检测调试
- `download_debug_materials.py` - 下载材料调试
- `test_auto_fallback.py` - 自动fallback测试
- `test_chunk_cache_integration.py` - Chunk Cache 集成测试
- `test_e2e.py` - 端到端测试
- `test_fallback_simulation.py` - Fallback模拟测试
- `test_get_latest_commit.py` - 获取最新commit测试
- `test_host_optimizer.py` - Host优化器测试
- `test_revision_fix.py` - Revision修复测试
- `verify_revision_fix.py` - Revision修复验证

### 🧪 test_scripts/ (2 个文件)
旧版测试脚本（已被改进版取代）
- `test_cli_download_basic.sh` - 基础CLI测试（被`test_cli_p0_core_v2.sh`取代）
- `test_fixes.sh` - 修复测试脚本

### 📋 logs/ (10 个文件)
历史日志文件
- `debug_chunk_cache.log`
- `debug_download.log`
- `debug_simple.log`
- `download_materials.log`
- `download_test.log`
- `granite_download.log`
- `test_cli_basic_full.log`
- `test_e2e.log`
- `test_output.log`
- `test_real_download.log`

## 当前活跃文件（根目录）

### 核心文档
- `README.md` / `README_CN.md` - 项目说明
- `测试计划.md` - **当前测试路线图** (P0 ✅ → P1 → P2 → P3)
- `P0_TEST_REPORT.md` - P0测试报告
- `待修问题.md` - 问题跟踪

### 测试脚本
- `test_cli_p0_core_v2.sh` - **当前P0测试脚本**（改进版）

### 配置文件
- `pyproject.toml` - 项目配置
- `conftest.py` - pytest配置
- `.gitignore` - Git忽略规则

---

**归档日期**: 2026-06-21  
**归档原因**: P0测试完成，整理项目结构  
**总文件数**: 34 个归档文件
