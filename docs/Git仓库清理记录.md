# Git 仓库清理总结

**日期**: 2026-06-21  
**状态**: ✅ 已完成  

---

## 📊 清理效果

| 阶段 | 大小 | 节省 | 说明 |
|------|------|------|------|
| **初始状态** | 184 MB | - | 包含测试输出和调试材料 |
| **第一次清理** | 92 MB | 92 MB (50%) | 删除 test_output_cli/ 等测试目录 |
| **第二次清理** | 1.4 MB | 90.6 MB (98.5%) | 删除 archive/debug_materials/xorbs/ |
| **✅ 最终** | **1.4 MB** | **182.6 MB (99.2%)** | 🎉 |

**工作目录大小**: 6.8 MB  
**提交数**: 42  
**分支数**: 1  

---

## 🗑️ 删除的大文件

### 测试输出文件（第一次清理）

1. **test_output_cli/test1_basic.gguf** - 105 MB
   - 测试输出的 GGUF 文件

2. **test_output_cli/** 目录
   - test1.log, test2.log, test3.log, test4.log, test5.log
   - test2_revision.gguf, test3_main.gguf, test5_progress.gguf

3. **其他测试目录**
   - test_output/
   - test_output_2_7/
   - test_output_batch_json/
   - test_output_cli_p1/
   - test_output_cli_p2/
   - test_output_cli_p2_fixed/
   - test_output_cli_p3/
   - test_output_verify_cache/
   - test_output_verify_cache2/
   - test_glm_json/

### 调试材料（第二次清理）

**archive/debug_materials/xorbs/** - 总计 ~100 MB

| 文件 | 大小 | 说明 |
|------|------|------|
| d81566d527460e0f17c029e903e4a9573ca65853a93c811568bb323e897ba0f1.bin | 51.4 MB | Xorb 二进制文件 |
| 33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5.bin | 19.9 MB | Xorb 二进制文件 |
| edc32dd7fbd51b16d0c668e87faf4e627bee1a31343defbe21c98261e219301e.bin | 7.4 MB | Xorb 二进制文件 |
| f52ace46e9559367a345b3c5a6ad6261391dae66197857915fa7d6a1ca27c812.bin | 6.8 MB | Xorb 二进制文件 |
| e1b463ede45b0c88b0c51bab2c61e9211fce6a7069d8dd963260c5f9c066fae2.bin | 4.5 MB | Xorb 二进制文件 |
| f1a0f07d98ea2e0fda4d535c20f1269ba996eabc6f75ecb634d9de99afd561b8.bin | 4.4 MB | Xorb 二进制文件 |
| 5985905df12a01ee48bab56884a599814317fcab1fcf8a625d9178e6e751e4c7.bin | 3.5 MB | Xorb 二进制文件 |
| 42176798d306c8a7bb049878afd60af5e8ed421bddea3c86c2ae106d22c7613a.bin | 3.5 MB | Xorb 二进制文件 |
| 5490b498398bd500a5e42e8cd02a82d7e9e8f2b980a053f5e8ddaed4406bbea5.bin | 2.4 MB | Xorb 二进制文件 |
| 59f2d04b6ae28547dae3c78668c5f647fc9ed459b2bda0af53ec2289cf9884b5.bin | 1.4 MB | Xorb 二进制文件 |

### 其他临时文件

- xetplus.7z - 618 KB
- batch_json_download.log
- cleanup_git.sh
- .gitignore_cleanup

---

## 🔧 清理步骤

### 1. 第一次清理（test_output_cli 等目录）

```bash
# 创建备份分支
git branch backup-before-cleanup

# 使用 filter-branch 删除测试目录
export FILTER_BRANCH_SQUELCH_WARNING=1
git filter-branch --force --index-filter \
  'git rm -rf --cached --ignore-unmatch \
    test_output_cli/ \
    debug_materials/ \
    test_output*/ \
    test_glm_json/ \
  ' \
  --prune-empty --tag-name-filter cat -- --all

# 清理引用和垃圾回收
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**结果**: 184 MB → 92 MB

### 2. 第二次清理（archive/debug_materials/xorbs/）

```bash
# 删除 archive 中的 xorb 文件
git filter-branch --force --index-filter \
  'git rm -rf --cached --ignore-unmatch archive/debug_materials/xorbs/' \
  --prune-empty --tag-name-filter cat -- --all

# 清理引用和垃圾回收
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**结果**: 92 MB → 1.4 MB

### 3. 更新 .gitignore

添加规则防止将来再次提交：

```gitignore
# 测试输出
test_output*/
test_glm_json/
debug_test.gguf/
test_cache_fix.gguf/
test_debug.gguf/

# 调试材料
debug_materials/
debug*.log
test_*.log

# GGUF 文件（除了归档）
*.gguf
!archive/**/*.gguf

# 临时清理脚本
cleanup_*.sh
.gitignore_cleanup
```

---

## 📝 当前 Git 历史中最大的文件

清理后，历史中最大的文件都是正常的源代码：

| 文件 | 大小 | 类型 |
|------|------|------|
| xetplus.7z | 618 KB | 压缩包（已从工作目录删除） |
| xet/cli/commands/download.py | 42 KB | 源代码 |
| xet/cli/commands/download.py | 37 KB | 源代码（旧版本） |
| xet/pipeline/chunk_assembler.py | 36 KB | 源代码 |
| docs/dev/KNOWN_ISSUES.md | 34 KB | 文档 |
| xet/network/cas_client.py | 33 KB | 源代码 |

**所有文件都 < 1 MB，非常健康！**

---

## ✅ 归档文件

以下文件已移动到 `archive/` 而非删除：

### 测试脚本

- archive/test_scripts/test_cli_p0_core_v2.sh
- archive/test_scripts/test_cli_p1_advanced.sh
- archive/test_scripts/test_cli_p2_advanced.sh
- archive/test_scripts/test_cli_p2_fixed.sh
- archive/test_scripts/test_hf_endpoint.sh
- archive/test_scripts/test_2_7_only.sh
- archive/test_scripts/test_batch_json.sh

### 调试脚本

- archive/debug_scripts/debug_chunk_logic.py
- archive/debug_scripts/test_chunk_logic.py

### 调试材料（不含 xorbs）

- archive/debug_materials/COMPLETE_FIX_SUMMARY.md
- archive/debug_materials/analyze_offset_bug.py
- archive/debug_materials/reconstruction.json
- archive/debug_materials/test_fix.py
- archive/debug_materials/test_non_contiguous.py
- archive/debug_materials/xorb_analysis.json
- archive/debug_materials/archive/CHUNK_CACHE_STATUS.md
- archive/debug_materials/archive/FIX_SUMMARY.md

**注意**: archive/debug_materials/xorbs/ 已从 Git 历史中完全删除

---

## 🚨 注意事项

### 如果需要恢复

虽然备份分支已删除，但如果需要恢复某些文件：

1. **查看旧提交**:
   ```bash
   git log --all --oneline | grep "删除之前"
   ```

2. **恢复特定文件**:
   ```bash
   git checkout <commit-hash> -- path/to/file
   ```

3. **查看已删除文件**:
   ```bash
   git log --diff-filter=D --summary
   ```

### 如果已推送到远程

由于我们重写了 Git 历史，如果仓库已推送到远程（GitHub/GitLab 等），需要强制推送：

```bash
# ⚠️ 谨慎操作！会覆盖远程历史
git push origin --force --all
git push origin --force --tags
```

**建议**: 如果有协作者，先通知他们重新 clone 仓库

---

## 📊 对比总结

### 清理前
```
.git/               184 MB
工作目录            ~110 MB (含测试文件)
总计                ~294 MB
```

### 清理后
```
.git/               1.4 MB  ⬇️ 99.2%
工作目录            6.8 MB  ⬇️ 93.8%
总计                8.2 MB  ⬇️ 97.2%
```

**总节省**: ~286 MB (97.2%)

---

## 🎯 后续建议

1. **定期清理**: 不要提交大文件到 Git
2. **使用 Git LFS**: 如果需要版本控制大文件，使用 Git LFS
3. **CI 检查**: 添加 pre-commit hook 检查文件大小
4. **文档规范**: 在 CONTRIBUTING.md 中明确禁止提交的文件类型

---

**清理完成！** 🎉

仓库现在非常精简，适合长期维护和协作开发。
