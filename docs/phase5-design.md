# Phase 5: CLI Layer 设计文档

## 📋 目标

实现 xet+ 命令行工具，提供用户友好的文件下载/上传接口。

---

## 🏗️ 架构设计

### 层次结构

```
┌─────────────────────────────────────┐
│         CLI Layer (Phase 5)         │
│  - 命令行解析                        │
│  - 进度条显示                        │
│  - 用户交互                          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│      Pipeline Layer (Phase 4)       │
│  - FileReconstructor                │
│  - DownloadScheduler                │
│  - ProgressTracker                  │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│      Network Layer (Phase 3)        │
│  - CASClient                        │
│  - 重试逻辑                          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     Protocol Layer (Phase 1)        │
│  - 数据类型定义                      │
└─────────────────────────────────────┘
```

---

## 🎯 核心命令

### 1. `xet download` - 下载文件

#### 用法

```bash
xet download <repo>/<file> [options]
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/model.gguf
```

#### 参数

```
positional arguments:
  path                  文件路径 (格式: repo/file 或 file_hash)

options:
  -o, --output PATH     输出文件路径 (默认: 当前目录)
  -c, --concurrency N   并发下载数 (默认: 4)
  --resume              从 checkpoint 恢复 (默认: 启用)
  --no-resume           禁用断点续传
  --checkpoint PATH     Checkpoint 文件路径
  -v, --verbose         详细输出
  -q, --quiet           静默模式（只显示错误）
  --progress-style      进度条样式 (rich|simple|none)
```

#### 示例

```bash
# 基本下载
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/model.gguf

# 指定输出路径
xet download mykor/model.gguf -o ~/models/granite.gguf

# 调整并发数
xet download mykor/model.gguf -c 8

# 静默模式
xet download mykor/model.gguf -q

# 详细模式
xet download mykor/model.gguf -vv
```

### 2. `xet info` - 查看文件信息

#### 用法

```bash
xet info <repo>/<file>
xet info mykor/granite-embedding-97m-multilingual-r2-GGUF/model.gguf
```

#### 输出

```
File: model.gguf
Repository: mykor/granite-embedding-97m-multilingual-r2-GGUF
Size: 100.58 MB
Hash: abc123...
Terms: 17
Xorbs: 10
CAS Endpoint: https://cas.xethub.com
```

### 3. `xet config` - 配置管理

#### 用法

```bash
xet config [key] [value]
xet config endpoint https://cas.xethub.com
xet config token YOUR_TOKEN
xet config --list
```

#### 配置项

```
endpoint          CAS 服务器地址
token             认证 Token
concurrency       默认并发数
progress_style    进度条样式
log_level         日志级别
```

---

## 🎨 进度条设计

### Rich 样式（默认）

```
Downloading model.gguf
━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━ 45% • 45.3/100.6 MB • 5.2 MB/s • ETA: 10s

Downloaded: 45.3 MB
Assembled:  42.1 MB
Speed:      5.2 MB/s
ETA:        10s
```

### Simple 样式

```
Downloading: 45% [=========>          ] 45.3/100.6 MB  5.2 MB/s  ETA: 10s
```

### None 样式

```
Downloading model.gguf... 45.3 MB / 100.6 MB (45%)
```

---

## 📝 配置文件

### 位置

1. `/etc/xet/config.toml` - 系统级
2. `~/.xetrc` - 用户级
3. `./.xet/config.toml` - 项目级
4. 环境变量 - 最高优先级

### 格式（TOML）

```toml
[xet]
endpoint = "https://cas.xethub.com"
token = "your_token_here"

[download]
concurrency = 4
resume = true
checkpoint_dir = "~/.xet/checkpoints"

[ui]
progress_style = "rich"
color = true

[logging]
level = "INFO"
file = "~/.xet/xet.log"
```

### 环境变量

```bash
XET_ENDPOINT=https://cas.xethub.com
XET_TOKEN=your_token
XET_CONCURRENCY=4
XET_LOG_LEVEL=DEBUG
```

---

## 🎯 实现计划

### 阶段 1: 基础 CLI 框架（1 天）

#### 文件结构

```
xet/cli/
├── __init__.py
├── main.py              # 入口点
├── commands/
│   ├── __init__.py
│   ├── download.py      # download 命令
│   ├── info.py          # info 命令
│   └── config.py        # config 命令
├── config_manager.py    # 配置管理
└── progress.py          # 进度条封装
```

#### 核心组件

1. **main.py**
   ```python
   def main():
       parser = argparse.ArgumentParser(
           prog='xet',
           description='XetHub 文件管理工具'
       )
       subparsers = parser.add_subparsers(dest='command')
       
       # 注册子命令
       register_download_command(subparsers)
       register_info_command(subparsers)
       register_config_command(subparsers)
       
       args = parser.parse_args()
       # 执行命令
   ```

2. **config_manager.py**
   ```python
   class ConfigManager:
       def __init__(self):
           self.configs = [
               SystemConfig(),
               UserConfig(),
               ProjectConfig(),
               EnvConfig(),
           ]
       
       def get(self, key: str) -> Any:
           # 按优先级查找
       
       def set(self, key: str, value: Any):
           # 保存到用户配置
   ```

### 阶段 2: Download 命令（1 天）

#### commands/download.py

```python
def download_command(args):
    # 1. 加载配置
    config = ConfigManager()
    endpoint = args.endpoint or config.get('endpoint')
    token = args.token or config.get('token')
    
    # 2. 初始化 CAS 客户端
    cas_client = CASClient(endpoint=endpoint, access_token=token)
    
    # 3. 解析文件路径
    repo, file_path = parse_file_spec(args.path)
    
    # 4. 获取文件信息
    file_info = cas_client.get_file_info(repo, file_path)
    
    # 5. 初始化进度条
    progress = RichProgress() if args.progress_style == 'rich' else SimpleProgress()
    
    def progress_callback(stats):
        progress.update(stats)
    
    # 6. 初始化 FileReconstructor
    reconstructor = FileReconstructor(
        cas_client=cas_client,
        output_path=args.output or Path(file_info.name),
        checkpoint_path=get_checkpoint_path(args),
        max_workers=args.concurrency,
        progress_callback=progress_callback,
    )
    
    # 7. 执行下载
    try:
        with progress:
            reconstructor.reconstruct_file(
                file_hash=file_info.hash,
                expected_size=file_info.size,
                resume=args.resume,
            )
        print(f"✓ 下载完成: {args.output}")
    except KeyboardInterrupt:
        print("\n⚠ 用户中断，进度已保存")
        sys.exit(130)
    except Exception as e:
        print(f"✗ 下载失败: {e}", file=sys.stderr)
        sys.exit(1)
```

### 阶段 3: 进度条实现（1 天）

#### progress.py

```python
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn
from rich.console import Console

class RichProgress:
    def __init__(self):
        self.progress = Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            "ETA: {task.fields[eta]}",
        )
        self.task = None
    
    def __enter__(self):
        self.progress.__enter__()
        self.task = self.progress.add_task("Downloading", total=0)
        return self
    
    def __exit__(self, *args):
        self.progress.__exit__(*args)
    
    def update(self, stats: dict):
        self.progress.update(
            self.task,
            total=stats['total_bytes'],
            completed=stats['assembled_bytes'],
            eta=f"{stats['eta_seconds']:.0f}s",
        )

class SimpleProgress:
    def __init__(self):
        self.last_pct = 0
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass
    
    def update(self, stats: dict):
        pct = stats['progress_pct']
        if int(pct) > self.last_pct:
            bar = '=' * int(pct / 5) + '>' + ' ' * (20 - int(pct / 5))
            print(f"\rDownloading: {pct:>5.1f}% [{bar}] {self._format_bytes(stats['assembled_bytes'])}/{self._format_bytes(stats['total_bytes'])}  {self._format_speed(stats['speed_bps'])}  ETA: {stats['eta_seconds']:.0f}s", end='')
            self.last_pct = int(pct)
    
    @staticmethod
    def _format_bytes(bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024
        return f"{bytes:.1f} TB"
    
    @staticmethod
    def _format_speed(bps):
        return RichProgress._format_bytes(bps) + "/s"
```

### 阶段 4: 错误处理和日志（1 天）

#### 日志配置

```python
import logging
from pathlib import Path

def setup_logging(level: str, log_file: Path = None):
    """配置日志系统。"""
    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(
        logging.Formatter('%(levelname)s: %(message)s')
    )
    
    # 文件 handler
    handlers = [console_handler]
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        handlers.append(file_handler)
    
    # 配置根 logger
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=handlers,
    )
```

#### 错误处理

```python
class XetError(Exception):
    """XET 工具基础异常。"""
    pass

class NetworkError(XetError):
    """网络相关错误。"""
    pass

class AuthenticationError(XetError):
    """认证错误。"""
    pass

class FileNotFoundError(XetError):
    """文件不存在。"""
    pass

def handle_error(e: Exception):
    """统一错误处理。"""
    if isinstance(e, AuthenticationError):
        print("✗ 认证失败，请检查 token", file=sys.stderr)
        print("提示: 运行 'xet config token YOUR_TOKEN' 配置 token", file=sys.stderr)
        sys.exit(1)
    elif isinstance(e, FileNotFoundError):
        print(f"✗ 文件不存在: {e}", file=sys.stderr)
        sys.exit(2)
    elif isinstance(e, NetworkError):
        print(f"✗ 网络错误: {e}", file=sys.stderr)
        print("提示: 请检查网络连接和 endpoint 配置", file=sys.stderr)
        sys.exit(3)
    else:
        print(f"✗ 未知错误: {e}", file=sys.stderr)
        if logging.getLogger().level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(255)
```

---

## 📦 依赖

### 新增依赖

```toml
[project.dependencies]
# 现有依赖
requests = "^2.31.0"
...

# CLI 新增
rich = "^13.7.0"          # 进度条和终端 UI
click = "^8.1.7"          # 或使用 argparse（内置）
toml = "^0.10.2"          # 配置文件解析
```

### 可选依赖

```bash
# 开发依赖
pip install ipython      # 交互式 REPL
pip install pytest-cov   # 覆盖率报告
```

---

## 🧪 测试计划

### 单元测试

```
tests/cli/
├── test_config_manager.py      # 配置管理
├── test_download_command.py    # 下载命令
├── test_info_command.py        # info 命令
└── test_progress.py            # 进度条
```

### 集成测试

```python
def test_download_real_file():
    """使用真实 API 测试完整下载流程。"""
    result = subprocess.run([
        'xet', 'download',
        'mykor/granite-embedding-97m-multilingual-r2-GGUF/test-file.gguf',
        '-o', '/tmp/test.gguf',
        '--progress-style', 'none',
    ], capture_output=True)
    
    assert result.returncode == 0
    assert Path('/tmp/test.gguf').exists()
```

---

## 📊 里程碑

### Day 1: CLI 框架
- ✅ 命令行参数解析
- ✅ 配置文件加载
- ✅ 基本命令结构

### Day 2: Download 命令
- ✅ 文件路径解析
- ✅ 集成 FileReconstructor
- ✅ 基本下载功能

### Day 3: 进度条和 UI
- ✅ Rich 进度条
- ✅ Simple 进度条
- ✅ 彩色输出

### Day 4: 完善和测试
- ✅ 错误处理
- ✅ 日志系统
- ✅ 单元测试
- ✅ 集成测试

---

## 🎉 完成标准

- [ ] 所有核心命令实现完成
- [ ] 进度条正常显示
- [ ] 配置文件正常工作
- [ ] 错误提示用户友好
- [ ] 测试覆盖率 > 70%
- [ ] 集成测试通过
- [ ] 用户文档完成

---

**准备开始 Phase 5 实现！**
