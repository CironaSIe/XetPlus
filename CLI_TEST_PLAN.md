# XET+ CLI 完整测试计划

## 📅 创建日期: 2026-06-21

---

## 🎯 测试目标

确保所有 CLI 命令和参数都经过实际测试，覆盖正常流程和边界情况。

---

## 📋 CLI 命令列表

### 1. `xet download` - 下载命令
### 2. `xet info` - 文件信息查看
### 3. `xet config` - 配置管理

---

## 🧪 测试分类

### A. 单元测试（已有）
- ✅ 核心模块单元测试（tests/unit/）
- ✅ Pipeline 组件测试
- ✅ 网络层测试

### B. 集成测试（部分）
- ✅ Chunk cache 集成测试
- ✅ 下载工作流测试
- ⚠️  CLI 命令集成测试（不完整）

### C. 端到端测试（缺失）
- ❌ 完整下载流程测试
- ❌ 多文件批量下载测试
- ❌ 断点续传测试
- ❌ 错误恢复测试

---

## 📝 详细测试计划

## 1️⃣ `xet download` 命令测试

### 1.1 基础下载功能

#### 测试用例 1.1.1: 单文件下载（user/repo/file 格式）
```bash
# 正常情况
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --token <token> \
  --proxy http://127.0.0.1:12334 \
  -o test_output/test1.gguf

# 验证
- [ ] 文件下载成功
- [ ] 文件大小正确 (105,467,232 bytes)
- [ ] SHA256 校验正确
- [ ] 进度条正常显示
- [ ] 速度和 ETA 显示正常
```

#### 测试用例 1.1.2: 使用 revision 参数
```bash
# 指定 commit hash
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --revision 45ce642d3fab2033d167ec09641a159010f7d9d9 \
  --token <token> \
  -o test_output/test2.gguf

# 验证
- [ ] 正确使用指定的 commit
- [ ] 文件内容与 commit 一致
```

#### 测试用例 1.1.3: 自动 fallback（main 不存在）
```bash
# 找一个没有 main 分支的仓库测试
xet download <repo-without-main>/file.gguf \
  --token <token> \
  -o test_output/test3.gguf

# 验证
- [ ] 自动探测最新 commit
- [ ] 日志显示 "main 分支不存在，尝试获取最新 commit..."
- [ ] 下载成功
```

### 1.2 批量下载功能

#### 测试用例 1.2.1: 使用 --include 匹配多个文件
```bash
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF \
  --include "*.gguf" \
  --token <token> \
  -o test_output/batch/

# 验证
- [ ] 列出所有匹配文件
- [ ] 跳过非 XET 文件
- [ ] 所有 XET 文件下载成功
- [ ] 文件保存在正确位置
```

### 1.3 断点续传功能

#### 测试用例 1.3.1: 中断后恢复
```bash
# 第一次下载（手动中断）
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --token <token> \
  -o test_output/resume.gguf &
PID=$!
sleep 10
kill -INT $PID

# 第二次下载（恢复）
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --token <token> \
  --resume \
  -o test_output/resume.gguf

# 验证
- [ ] checkpoint 文件存在
- [ ] 恢复下载成功
- [ ] 不重新下载已完成的部分
- [ ] 最终文件完整正确
```

#### 测试用例 1.3.2: 禁用断点续传
```bash
xet download <file> \
  --no-resume \
  -o test_output/no_resume.gguf

# 验证
- [ ] 不创建 checkpoint 文件
- [ ] 从头开始下载
```

### 1.4 网络优化功能

#### 测试用例 1.4.1: HOST 优选
```bash
xet download <file> \
  --optimize-hosts \
  --proxy http://127.0.0.1:12334 \
  --token <token> \
  -o test_output/optimized.gguf

# 验证
- [ ] 显示 "正在执行 HOST 优选..."
- [ ] 显示优选结果（域名 → IP，RTT，速度）
- [ ] 下载使用优选的 IP
```

#### 测试用例 1.4.2: 自定义 DNS 服务器
```bash
xet download <file> \
  --optimize-hosts \
  --dns-servers "https://cloudflare-dns.com/dns-query,https://dns.google/dns-query" \
  --token <token> \
  -o test_output/custom_dns.gguf

# 验证
- [ ] 使用自定义 DNS 服务器
- [ ] 日志显示 DNS 服务器列表
```

### 1.5 并发控制

#### 测试用例 1.5.1: 指定并发数
```bash
xet download <file> \
  --concurrency 8 \
  --token <token> \
  -o test_output/concurrent.gguf

# 验证
- [ ] 使用指定的并发数
- [ ] 日志显示正确的并发配置
```

### 1.6 缓存功能

#### 测试用例 1.6.1: 使用缓存
```bash
# 第一次下载（构建缓存）
xet download <file> \
  --token <token> \
  -o test_output/cached1.gguf

# 第二次下载（使用缓存）
xet download <file> \
  --token <token> \
  -o test_output/cached2.gguf

# 验证
- [ ] 缓存命中率 > 0%
- [ ] 第二次下载更快
- [ ] 缓存目录存在文件
```

#### 测试用例 1.6.2: 禁用缓存
```bash
xet download <file> \
  --no-cache \
  --token <token> \
  -o test_output/no_cache.gguf

# 验证
- [ ] 不创建缓存文件
- [ ] 不读取缓存
```

#### 测试用例 1.6.3: 保留缓存
```bash
xet download <file> \
  --keep-cache \
  --token <token> \
  -o test_output/keep_cache.gguf

# 验证
- [ ] 下载完成后缓存仍然存在
- [ ] 可用于后续下载
```

### 1.7 内存控制

#### 测试用例 1.7.1: 低内存模式
```bash
xet download <file> \
  --max-memory-mb 100 \
  --prefetch-low 20 \
  --prefetch-high 80 \
  --token <token> \
  -o test_output/low_mem.gguf

# 验证
- [ ] 内存使用不超过限制
- [ ] 下载成功完成
- [ ] 预取水位线正常工作
```

### 1.8 分段下载

#### 测试用例 1.8.1: 指定分段大小
```bash
xet download <file> \
  --segment-size 256MB \
  --parallel-segments 2 \
  --token <token> \
  -o test_output/segmented.gguf

# 验证
- [ ] 使用指定的分段大小
- [ ] 并行下载多个段
```

### 1.9 错误处理

#### 测试用例 1.9.1: 无效 token
```bash
xet download <file> \
  --token invalid_token \
  -o test_output/error.gguf

# 验证
- [ ] 显示清晰的错误信息
- [ ] 退出码非 0
```

#### 测试用例 1.9.2: 不存在的文件
```bash
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/nonexistent.gguf \
  --token <token> \
  -o test_output/error.gguf

# 验证
- [ ] 显示 "文件不是 XET 格式" 或 "文件不存在"
- [ ] 退出码非 0
```

#### 测试用例 1.9.3: 网络中断
```bash
# 下载过程中断网测试
xet download <file> \
  --token <token> \
  --retry-max 3 \
  -o test_output/network_error.gguf

# 验证
- [ ] 自动重试
- [ ] 重试次数不超过限制
- [ ] 显示重试日志
```

---

## 2️⃣ `xet info` 命令测试

### 测试用例 2.1: 查看文件信息
```bash
xet info mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --token <token>

# 验证
- [ ] 显示 Xet Hash
- [ ] 显示文件大小
- [ ] 显示 SHA256
- [ ] 显示重建信息
```

### 测试用例 2.2: 使用 revision
```bash
xet info mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --revision 45ce642d3fab2033d167ec09641a159010f7d9d9 \
  --token <token>

# 验证
- [ ] 使用指定 revision
- [ ] 显示正确的信息
```

---

## 3️⃣ `xet config` 命令测试

### 测试用例 3.1: 设置配置
```bash
xet config xet.token test_token
xet config xet.endpoint https://test.example.com
xet config network.concurrency 8

# 验证
- [ ] 配置保存成功
- [ ] 配置文件存在
```

### 测试用例 3.2: 查看配置
```bash
xet config --list

# 验证
- [ ] 显示所有配置项
- [ ] 格式清晰易读
```

### 测试用例 3.3: 删除配置
```bash
xet config --unset xet.token

# 验证
- [ ] 配置项被删除
- [ ] 配置文件更新
```

---

## 🔧 测试工具和脚本

### 需要创建的测试脚本

1. **test_cli_download_basic.sh** - 基础下载测试
2. **test_cli_download_advanced.sh** - 高级功能测试
3. **test_cli_batch.sh** - 批量下载测试
4. **test_cli_resume.sh** - 断点续传测试
5. **test_cli_network.sh** - 网络优化测试
6. **test_cli_cache.sh** - 缓存功能测试
7. **test_cli_memory.sh** - 内存控制测试
8. **test_cli_errors.sh** - 错误处理测试
9. **test_cli_info.sh** - info 命令测试
10. **test_cli_config.sh** - config 命令测试

### 测试框架

```bash
#!/bin/bash
# test_framework.sh - 测试框架

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 测试计数
TOTAL=0
PASSED=0
FAILED=0

# 测试函数
test_case() {
    local name="$1"
    local command="$2"
    local expected_exit_code="${3:-0}"
    
    TOTAL=$((TOTAL + 1))
    echo -e "\n🧪 测试: $name"
    
    if eval "$command"; then
        local exit_code=$?
        if [ $exit_code -eq $expected_exit_code ]; then
            echo -e "${GREEN}✅ 通过${NC}"
            PASSED=$((PASSED + 1))
        else
            echo -e "${RED}❌ 失败 (退出码: $exit_code, 期望: $expected_exit_code)${NC}"
            FAILED=$((FAILED + 1))
        fi
    else
        echo -e "${RED}❌ 失败${NC}"
        FAILED=$((FAILED + 1))
    fi
}

# 报告函数
report() {
    echo -e "\n" "=" * 70
    echo -e "📊 测试报告"
    echo -e "=" * 70
    echo -e "总计: $TOTAL"
    echo -e "${GREEN}通过: $PASSED${NC}"
    echo -e "${RED}失败: $FAILED${NC}"
    echo -e "成功率: $(( PASSED * 100 / TOTAL ))%"
}
```

---

## 📊 测试覆盖矩阵

| 功能 | 单元测试 | 集成测试 | CLI测试 | 状态 |
|------|---------|---------|---------|------|
| 基础下载 | ✅ | ✅ | ⚠️ | 部分 |
| revision 参数 | ✅ | ✅ | ❌ | 缺失 |
| 自动 fallback | ✅ | ✅ | ❌ | 缺失 |
| 批量下载 | ✅ | ⚠️ | ❌ | 缺失 |
| 断点续传 | ✅ | ⚠️ | ❌ | 缺失 |
| 网络优化 | ✅ | ❌ | ❌ | 缺失 |
| 缓存功能 | ✅ | ✅ | ⚠️ | 部分 |
| 内存控制 | ✅ | ⚠️ | ❌ | 缺失 |
| 错误处理 | ✅ | ⚠️ | ❌ | 缺失 |
| info 命令 | ✅ | ❌ | ❌ | 缺失 |
| config 命令 | ✅ | ❌ | ❌ | 缺失 |

**图例**:
- ✅ 完整测试
- ⚠️ 部分测试
- ❌ 缺失测试

---

## 🎯 优先级

### P0 - 关键功能（必须测试）
1. 基础下载流程
2. revision 参数
3. 自动 fallback
4. 断点续传
5. 错误处理

### P1 - 重要功能（应该测试）
1. 批量下载
2. 缓存功能
3. 网络优化
4. info 命令
5. config 命令

### P2 - 一般功能（可选测试）
1. 内存控制
2. 分段下载
3. 并发控制
4. 自定义参数

---

## 📝 测试执行计划

### 第一阶段: P0 功能测试（1-2天）
- [ ] 创建基础测试脚本
- [ ] 测试下载流程
- [ ] 测试 revision 和 fallback
- [ ] 测试断点续传
- [ ] 测试错误处理

### 第二阶段: P1 功能测试（1-2天）
- [ ] 测试批量下载
- [ ] 测试缓存功能
- [ ] 测试网络优化
- [ ] 测试 info/config 命令

### 第三阶段: P2 功能测试（可选）
- [ ] 测试高级参数
- [ ] 性能测试
- [ ] 压力测试

---

## 🔍 当前状态评估

### 已有测试
- ✅ 完整的单元测试覆盖
- ✅ Chunk cache 集成测试
- ✅ 部分下载流程测试

### 缺失测试
- ❌ CLI 命令的端到端测试
- ❌ revision 参数的实际测试
- ❌ 自动 fallback 的实际测试
- ❌ 批量下载的完整测试
- ❌ 断点续传的完整测试
- ❌ 网络优化的实际测试
- ❌ info/config 命令测试

### 测试覆盖率估算
- 单元测试: ~80%
- 集成测试: ~40%
- CLI 端到端测试: ~20%
- **总体覆盖率**: ~50%

---

## 💡 建议

1. **立即行动**: 创建 P0 测试脚本
2. **CI 集成**: 将测试集成到 CI/CD 流程
3. **定期运行**: 每次提交前运行完整测试套件
4. **文档更新**: 将测试结果记录到文档
5. **覆盖率监控**: 追踪测试覆盖率变化

---

## 📚 参考文档

- `tests/` - 现有测试目录
- `TESTING_GUIDE.md` - 测试指南
- `XET_DETECTION_FIX_SUMMARY.md` - 最新功能说明

---

**创建者**: Claude & User  
**状态**: 待执行  
**优先级**: 高
