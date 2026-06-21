# XET+ 日志控制说明

## 📋 日志系统设计

### 双层日志架构

XET+ 采用**控制台 + 文件**双层日志系统：

```
┌─────────────────────────────────────────┐
│  控制台日志 (stderr)                      │
│  - 级别可控: WARNING/INFO/DEBUG          │
│  - 用户可见，简洁明了                     │
│  - 通过 -v 或 --log-level 控制            │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│  文件日志 (~/.xet/logs/)                 │
│  - 始终 DEBUG 级别（完整记录）            │
│  - 包含时间戳、模块名、详细信息            │
│  - 用于问题排查                          │
│  - 自动清理旧日志（保留最近 10 个）        │
└─────────────────────────────────────────┘
```

**关键特性**:
- ✅ 控制台级别可控（不影响文件）
- ✅ 文件始终记录完整日志（DEBUG）
- ✅ 第三方库日志自动抑制（urllib3, requests）

---

## 🎯 使用方式

### 1. 控制台日志级别

#### 方式 A: 使用 `-v` 参数（推荐）

```bash
# 默认 - 只显示警告和错误
xet download mykor/granite-97m/file.gguf

# -v - 显示信息级别（INFO）
xet download mykor/granite-97m/file.gguf -v

# -vv - 显示调试级别（DEBUG）
xet download mykor/granite-97m/file.gguf -vv
```

**级别对应**:
- 无 `-v`: WARNING（只显示警告和错误）
- `-v`: INFO（显示操作信息）
- `-vv`: DEBUG（显示详细调试信息）

#### 方式 B: 使用 `--log-level` 参数

```bash
# 明确指定级别
xet download mykor/granite-97m/file.gguf --log-level INFO
xet download mykor/granite-97m/file.gguf --log-level DEBUG

# --log-level 优先级高于 -v
xet download mykor/granite-97m/file.gguf -vv --log-level WARNING
# 结果: 控制台只显示 WARNING
```

**可用级别**:
- `DEBUG` - 最详细
- `INFO` - 信息
- `WARNING` - 警告（默认）
- `ERROR` - 仅错误

### 2. 文件日志

#### 默认行为（自动记录）

```bash
# 默认自动保存日志到 ~/.xet/logs/xet_YYYYMMDD_HHMMSS.log
xet download mykor/granite-97m/file.gguf

# 日志位置会在控制台显示（INFO 级别）
# INFO: 日志文件: /home/user/.xet/logs/xet_20250621_123456.log
```

**特点**:
- 📁 默认位置: `~/.xet/logs/xet_YYYYMMDD_HHMMSS.log`
- 🔍 始终记录 DEBUG 级别（完整日志）
- 🧹 自动清理旧日志（保留最近 10 个）
- ⏰ 文件名包含时间戳

#### 自定义日志文件路径

```bash
# 指定日志文件路径
xet download mykor/granite-97m/file.gguf --log-file ./my-download.log

# 保存到当前目录
xet download mykor/granite-97m/file.gguf --log-file ./xet.log
```

#### 禁用文件日志

```bash
# 不保存日志文件（只输出到控制台）
xet download mykor/granite-97m/file.gguf --no-log-file
```

---

## 📊 日志级别对比

### 控制台输出示例

#### WARNING（默认）

```bash
$ xet download mykor/granite-97m/file.gguf

正在下载: file.gguf
Downloading: 100% [========>] 100 MB/100 MB  10 MB/s
✓ 下载完成
```

**只显示**: 进度条、成功/失败消息、警告/错误

#### INFO（`-v`）

```bash
$ xet download mykor/granite-97m/file.gguf -v

INFO: 日志文件: ~/.xet/logs/xet_20250621_123456.log
INFO: 使用配置: concurrency=4
INFO: 检测文件: mykor/granite-97m/file.gguf
INFO: 获取到 CAS token, endpoint=https://cas-server.xethub.hf.co

正在下载: file.gguf
Downloading: 100% [========>] 100 MB/100 MB  10 MB/s
✓ 下载完成
```

**额外显示**: 配置信息、操作步骤、CAS endpoint

#### DEBUG（`-vv`）

```bash
$ xet download mykor/granite-97m/file.gguf -vv

DEBUG: XET CLI 启动: xet download mykor/granite-97m/file.gguf -vv
DEBUG: 控制台日志级别: DEBUG
DEBUG: 文件日志级别: DEBUG (完整)
INFO: 日志文件: ~/.xet/logs/xet_20250621_123456.log
INFO: 使用配置: concurrency=4
DEBUG: 解析路径: mykor/granite-97m/file.gguf
DEBUG: repo_id=mykor/granite-97m, filename=file.gguf
INFO: 检测文件: mykor/granite-97m/file.gguf
DEBUG: HEAD 请求: https://huggingface.co/mykor/granite-97m/resolve/main/file.gguf
DEBUG: Link header: <xet://e0aacd10...>; rel="xet-hash"
DEBUG: 提取 xet-hash: e0aacd10...
INFO: 获取到 CAS token, endpoint=https://cas-server.xethub.hf.co
DEBUG: 获取 reconstruction: e0aacd10...
DEBUG: Reconstruction: 1523 terms, 42 xorbs

正在下载: file.gguf
Downloading: 100% [========>] 100 MB/100 MB  10 MB/s

DEBUG: 下载完成: 1523 terms, 42 xorbs
DEBUG: SHA256 校验: 355f1f30...
✓ 下载完成
```

**最详细**: 所有操作细节、API 请求、数据结构

### 文件日志示例（始终 DEBUG）

```log
2025-06-21 12:34:56 [INFO] xet.cli.main: 日志文件: /home/user/.xet/logs/xet_20250621_123456.log
2025-06-21 12:34:56 [DEBUG] xet.cli.main: XET CLI 启动: xet download mykor/granite-97m/file.gguf
2025-06-21 12:34:56 [DEBUG] xet.cli.main: 控制台日志级别: WARNING
2025-06-21 12:34:56 [DEBUG] xet.cli.main: 文件日志级别: DEBUG (完整)
2025-06-21 12:34:57 [INFO] xet.cli.commands.download: 使用配置: concurrency=4
2025-06-21 12:34:57 [DEBUG] xet.cli.commands.download: 解析路径: mykor/granite-97m/file.gguf
2025-06-21 12:34:57 [DEBUG] xet.cli.commands.download: repo_id=mykor/granite-97m, filename=file.gguf
2025-06-21 12:34:58 [INFO] xet.cli.commands.download: 检测文件: mykor/granite-97m/file.gguf
2025-06-21 12:34:58 [DEBUG] xet.network.cas_client: HEAD 请求: https://huggingface.co/...
2025-06-21 12:34:59 [DEBUG] xet.network.auth: 获取 CAS token
2025-06-21 12:35:00 [INFO] xet.network.auth: 获取到 CAS token, endpoint=https://cas-server.xethub.hf.co
2025-06-21 12:35:01 [DEBUG] xet.network.cas_client: 获取 reconstruction: e0aacd10...
2025-06-21 12:35:02 [DEBUG] xet.network.cas_client: Reconstruction: 1523 terms, 42 xorbs
2025-06-21 12:35:10 [DEBUG] xet.pipeline.file_reconstructor: 下载完成: 1523 terms, 42 xorbs
2025-06-21 12:35:10 [DEBUG] xet.pipeline.file_reconstructor: SHA256 校验: 355f1f30...
2025-06-21 12:35:10 [INFO] xet.cli.commands.download: 下载完成
```

**特点**:
- ⏰ 精确时间戳
- 🏷️ 模块名称（定位问题）
- 📝 完整信息（包括 DEBUG）
- 🔍 便于事后排查

---

## 🛠️ 实际应用场景

### 场景 1: 日常使用（默认）

```bash
# 只关心结果，不需要详细信息
xet download mykor/granite-97m/file.gguf
```

**输出**: 进度条 + 成功/失败
**日志文件**: 自动保存完整日志（事后排查）

### 场景 2: 调试问题（`-v`）

```bash
# 查看操作过程
xet download mykor/granite-97m/file.gguf -v
```

**输出**: 配置信息 + 操作步骤 + 进度条
**用于**: 确认配置是否正确、操作是否符合预期

### 场景 3: 深度调试（`-vv`）

```bash
# 查看所有细节
xet download mykor/granite-97m/file.gguf -vv
```

**输出**: 所有 DEBUG 信息
**用于**: 排查网络问题、API 错误、数据格式问题

### 场景 4: 指定日志文件

```bash
# 保存日志到特定位置（方便分享）
xet download mykor/granite-97m/file.gguf --log-file ./download-issue.log
```

**用途**: 
- 报告 bug 时附上日志
- 多次下载对比日志
- 自动化脚本保存日志

### 场景 5: 禁用文件日志

```bash
# 临时下载，不需要保存日志
xet download mykor/granite-97m/small-file.bin --no-log-file
```

**用途**:
- 临时测试
- 节省磁盘空间
- CI/CD 环境（日志由外部收集）

---

## 🎨 日志格式对比

### 控制台格式（简洁）

```
INFO: 使用配置: concurrency=4
WARNING: 连接超时，正在重试...
ERROR: 下载失败: 404 Not Found
```

**特点**: 级别 + 消息（简洁明了）

### 文件格式（详细）

```
2025-06-21 12:34:56 [INFO] xet.cli.commands.download: 使用配置: concurrency=4
2025-06-21 12:35:10 [WARNING] xet.network.cas_client: 连接超时，正在重试...
2025-06-21 12:35:20 [ERROR] xet.network.cas_client: 下载失败: 404 Not Found
```

**特点**: 时间戳 + [级别] + 模块名 + 消息

---

## 🔧 技术实现

### 根 Logger 设置

```python
# 根 logger 设置为 DEBUG（放行所有日志）
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
```

### 控制台 Handler（级别可控）

```python
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(console_level)  # WARNING/INFO/DEBUG
console_handler.setFormatter(
    logging.Formatter("%(levelname)s: %(message)s")
)
```

### 文件 Handler（始终 DEBUG）

```python
file_handler = logging.FileHandler(log_path, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)  # 始终 DEBUG
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
```

### 第三方库抑制

```python
# 即使控制台设置 DEBUG，也不显示第三方库的 DEBUG 日志
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("urllib3.util.retry").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
```

---

## 📚 与 xet.py 对比

| 特性 | xet.py | XET+ | 优势 |
|------|--------|------|------|
| **控制台级别** | `--log-level` | `-v` + `--log-level` | XET+ 更灵活 |
| **文件日志** | 自动保存 DEBUG | 自动保存 DEBUG | 相同 |
| **日志清理** | 保留最新 1 个 | 保留最新 10 个 | XET+ 更合理 |
| **第三方库抑制** | ✅ | ✅ | 相同 |
| **可选禁用** | ❌ | ✅ `--no-log-file` | XET+ 更灵活 |

---

## 🎯 最佳实践

### 推荐用法

```bash
# 日常使用 - 默认即可
xet download mykor/granite-97m/file.gguf

# 查看进度 - 使用 -v
xet download mykor/granite-97m/file.gguf -v

# 排查问题 - 使用 -vv + 自定义日志
xet download mykor/granite-97m/file.gguf -vv --log-file ./debug.log
```

### 日志查看

```bash
# 实时查看日志
tail -f ~/.xet/logs/xet_*.log

# 搜索错误
grep ERROR ~/.xet/logs/xet_*.log

# 查看最近的日志
ls -lt ~/.xet/logs/ | head -5
```

---

**日期**: 2025-06-21  
**版本**: XET+ 0.2.0 (Phase 5 + CLI Improvements + Logging)  
**状态**: ✅ 日志系统完善，控制台可控 + 文件完整记录
