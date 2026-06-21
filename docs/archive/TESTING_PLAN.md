# XET+ 功能测试计划

## 测试目标

验证 XET+ 下载功能的完整性和正确性，包括：
- 断点续传（checkpoint resume）
- 并行写入模式（parallel write）
- IP 优选（host optimization）
- 缓存机制（chunk cache & xorb cache）

---

## 测试环境

### 基础配置
- **平台**: Termux on Android
- **Python**: 3.13
- **测试文件**: `mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf`
  - 大小: 100.6 MB (105,467,232 bytes)
  - Hash: `e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02`
  - Terms: 17
  - Xorbs: 10
  - Segments: 14

### 网络环境
- **代理可用**: `http://127.0.0.1:12334`
- **DoH 服务器**: 
  - 国内: `https://dns.alidns.com/dns-query`
  - 国外: `https://cloudflare-dns.com/dns-query`

---

## 测试用例

### 1. 基础下载测试 ✅ 已完成

**目的**: 验证核心下载和重建功能

**测试步骤**:
```bash
python -c "
from xet.cli.commands.download import download_command
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
args = parser.parse_args([])
args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
args.output = Path('test_basic.gguf')
args.proxy = 'http://127.0.0.1:12334'
args.force = True
args.endpoint = None
args.token = None
args.concurrency = 4
args.optimize_hosts_flag = False
args.no_optimize_hosts_flag = False
args.resume = False
args.checkpoint = None
args.include = None
args.progress_style = 'simple'

download_command(args)
"
```

**预期结果**:
- ✅ 下载全部 10 xorbs
- ✅ 处理全部 17 terms
- ✅ 文件大小: 105,467,232 bytes
- ✅ 无错误退出

**实际结果**: ✅ 通过

---

### 2. 断点续传测试（Checkpoint Resume）

**目的**: 验证中断后从 checkpoint 恢复

**测试步骤**:
1. **第一阶段 - 模拟中断**:
   ```bash
   # 启动下载并在 30% 时中断
   timeout 20s python -c "
   from xet.cli.commands.download import download_command
   import argparse
   from pathlib import Path
   
   parser = argparse.ArgumentParser()
   args = parser.parse_args([])
   args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
   args.output = Path('test_resume.gguf')
   args.proxy = 'http://127.0.0.1:12334'
   args.force = True
   args.endpoint = None
   args.token = None
   args.concurrency = 4
   args.optimize_hosts_flag = False
   args.no_optimize_hosts_flag = False
   args.resume = True  # 启用断点续传
   args.checkpoint = Path('test_resume.checkpoint')
   args.include = None
   args.progress_style = 'simple'
   
   download_command(args)
   " || echo "下载被中断（预期行为）"
   ```

2. **检查 checkpoint 文件**:
   ```bash
   ls -lh test_resume.checkpoint
   cat test_resume.checkpoint | python -m json.tool | head -30
   ```

3. **第二阶段 - 恢复下载**:
   ```bash
   # 使用相同参数继续下载
   python -c "
   from xet.cli.commands.download import download_command
   import argparse
   from pathlib import Path
   
   parser = argparse.ArgumentParser()
   args = parser.parse_args([])
   args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
   args.output = Path('test_resume.gguf')
   args.proxy = 'http://127.0.0.1:12334'
   args.force = False  # 不强制重新下载
   args.endpoint = None
   args.token = None
   args.concurrency = 4
   args.optimize_hosts_flag = False
   args.no_optimize_hosts_flag = False
   args.resume = True
   args.checkpoint = Path('test_resume.checkpoint')
   args.include = None
   args.progress_style = 'simple'
   
   download_command(args)
   "
   ```

**预期结果**:
- ✅ checkpoint 文件存在且包含已完成的 xorb 列表
- ✅ 恢复后跳过已下载的 xorbs
- ✅ 只下载剩余的 xorbs
- ✅ 最终文件大小正确
- ✅ checkpoint 文件被清理

**验证点**:
```bash
# 验证文件大小
stat -c "%s" test_resume.gguf
# 期望: 105467232

# 验证 checkpoint 已清理
ls test_resume.checkpoint
# 期望: No such file or directory
```

---

### 3. 并行写入模式测试（Parallel Write）

**目的**: 验证批量并行写入功能

**测试步骤**:
```bash
python -c "
from xet.cli.commands.download import download_command
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
args = parser.parse_args([])
args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
args.output = Path('test_parallel.gguf')
args.proxy = 'http://127.0.0.1:12334'
args.force = True
args.endpoint = None
args.token = None
args.concurrency = 4
args.optimize_hosts_flag = False
args.no_optimize_hosts_flag = False
args.resume = False
args.checkpoint = None
args.include = None
args.progress_style = 'simple'
# 注意: parallel_write 需要通过内部参数传递

# 需要修改代码支持 --parallel-write 参数
download_command(args)
"
```

**预期结果**:
- ✅ 使用 GlobalWriter 批量写入
- ✅ 日志显示 "parallel_write=enabled"
- ✅ 文件大小正确
- ✅ 性能提升（相比顺序写入）

**TODO**: 需要在 `download.py` 中添加 `--parallel-write` 参数支持

---

### 4. IP 优选测试（Host Optimization）

#### 4.1 使用代理的 IP 优选

**目的**: 验证通过代理访问 DoH 进行 IP 优选

**测试步骤**:
```bash
# 清理旧缓存
rm -f ~/.xet/cache/host_optimize.json

# 使用代理 + IP 优选
python -c "
from xet.cli.commands.download import download_command
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
args = parser.parse_args([])
args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
args.output = Path('test_optimize_proxy.gguf')
args.proxy = 'http://127.0.0.1:12334'
args.force = True
args.endpoint = None
args.token = None
args.concurrency = 4
args.optimize_hosts_flag = True  # 启用 IP 优选
args.no_optimize_hosts_flag = False
args.dns_servers = None  # 使用默认 DoH
args.resume = False
args.checkpoint = None
args.include = None
args.progress_style = 'simple'

download_command(args)
"
```

**预期结果**:
- ✅ 通过代理访问 DoH 服务器成功
- ✅ 获取到多个 IP 地址
- ✅ 进行 RTT 和传输速率测试
- ✅ 选择最优 IP 并缓存
- ✅ 下载成功

**验证点**:
```bash
# 查看优选缓存
cat ~/.xet/cache/host_optimize.json | python -m json.tool

# 期望看到：
# {
#   "huggingface.co": {"ip": "...", "use_proxy": true, "rtt": ...},
#   "transfer.xethub.hf.co": {"ip": "...", "use_proxy": false, "rtt": ...}
# }
```

#### 4.2 使用国内 DoH 的 IP 优选

**目的**: 验证无代理情况下使用国内 DoH

**测试步骤**:
```bash
# 清理旧缓存
rm -f ~/.xet/cache/host_optimize.json

# 无代理 + 国内 DoH
python -c "
from xet.cli.commands.download import download_command
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
args = parser.parse_args([])
args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
args.output = Path('test_optimize_domestic.gguf')
args.proxy = None  # 无代理
args.force = True
args.endpoint = None
args.token = None
args.concurrency = 4
args.optimize_hosts_flag = True
args.no_optimize_hosts_flag = False
args.dns_servers = 'https://dns.alidns.com/dns-query,https://doh.pub/dns-query'
args.resume = False
args.checkpoint = None
args.include = None
args.progress_style = 'simple'

download_command(args)
"
```

**预期结果**:
- ✅ DoH 查询成功（使用阿里 DNS）
- ⚠️ `huggingface.co` 无法直连（预期，被墙）
- ✅ `transfer.xethub.hf.co` 可能可以直连
- ⚠️ 如果 transfer 也被墙，下载会失败（预期行为）

---

### 5. 缓存机制测试

#### 5.1 Chunk Cache 测试

**目的**: 验证 chunk 级别缓存

**测试步骤**:
```bash
# 第一次下载（填充缓存）
python -c "
from xet.cli.commands.download import download_command
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
args = parser.parse_args([])
args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
args.output = Path('test_cache1.gguf')
args.proxy = 'http://127.0.0.1:12334'
args.force = True
args.endpoint = None
args.token = None
args.concurrency = 4
args.optimize_hosts_flag = False
args.no_optimize_hosts_flag = False
args.resume = False
args.checkpoint = None
args.include = None
args.progress_style = 'simple'

download_command(args)
"

# 检查缓存
ls -lh ~/.xet/cache/chunks/
du -sh ~/.xet/cache/chunks/

# 第二次下载（使用缓存）
time python -c "
from xet.cli.commands.download import download_command
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
args = parser.parse_args([])
args.path = 'mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf'
args.output = Path('test_cache2.gguf')
args.proxy = 'http://127.0.0.1:12334'
args.force = True
args.endpoint = None
args.token = None
args.concurrency = 4
args.optimize_hosts_flag = False
args.no_optimize_hosts_flag = False
args.resume = False
args.checkpoint = None
args.include = None
args.progress_style = 'simple'

download_command(args)
"
```

**预期结果**:
- ✅ 第一次下载后缓存目录有数据
- ✅ 第二次下载速度显著提升（跳过网络下载）
- ✅ 两次下载的文件大小一致

#### 5.2 Xorb Cache 测试

**目的**: 验证 xorb 级别缓存回退机制

**测试步骤**:
```bash
# 禁用 chunk cache，使用 xorb cache
# TODO: 需要添加 --disable-chunk-cache 参数
```

---

### 6. 并发下载测试

**目的**: 验证不同并发度的下载性能

**测试步骤**:
```bash
# 并发度 = 1
time python -c "..." --concurrency 1

# 并发度 = 4（默认）
time python -c "..." --concurrency 4

# 并发度 = 8
time python -c "..." --concurrency 8

# 并发度 = 16
time python -c "..." --concurrency 16
```

**预期结果**:
- ✅ 并发度越高，下载速度越快（在网络带宽允许的情况下）
- ✅ 过高的并发度可能导致性能下降（线程开销）

---

### 7. 错误处理测试

#### 7.1 网络中断测试

**测试步骤**:
```bash
# 下载过程中断网络
# 观察重试机制
```

**预期结果**:
- ✅ 自动重试失败的 segment
- ✅ 重试次数达到上限后报错
- ✅ checkpoint 保存已完成的进度

#### 7.2 磁盘空间不足测试

**测试步骤**:
```bash
# 在磁盘空间不足的目录下载
```

**预期结果**:
- ✅ 检测到磁盘空间不足
- ✅ 清理 .part 文件
- ✅ 友好的错误提示

---

## 测试总结

### 已完成测试
1. ✅ 基础下载（无缓存、无优选）
2. ✅ 修复 5 个关键 bug

### 待测试功能
1. ⏳ 断点续传
2. ⏳ 并行写入模式
3. ⏳ IP 优选（国内/国外 DoH）
4. ⏳ 缓存机制
5. ⏳ 并发性能
6. ⏳ 错误处理

### 测试工具
- 手动测试脚本
- 性能对比（time 命令）
- 缓存检查（du, ls）
- 日志分析（grep, tail）

---

## 自动化测试脚本

TODO: 创建 `tests/integration/test_download_features.py`，包含所有测试用例的自动化执行。
