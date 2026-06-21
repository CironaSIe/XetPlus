# XET+ 使用指南

## 目录
- [快速开始](#快速开始)
- [基础使用](#基础使用)
- [高级功能](#高级功能)
- [性能优化](#性能优化)
- [故障排查](#故障排查)
- [最佳实践](#最佳实践)

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/yourusername/xetplus.git
cd xetplus

# 安装依赖
pip install -r requirements.txt
```

### 第一次下载

```bash
# 基础下载
python -m xet.cli.commands.download user/repo/model.gguf

# 国内用户推荐（启用 IP 优选）
python -m xet.cli.commands.download user/repo/model.gguf --optimize-hosts
```

## 基础使用

### 下载文件

```bash
# 下载到当前目录
python -m xet.cli.commands.download user/repo/model.gguf

# 指定输出路径
python -m xet.cli.commands.download user/repo/model.gguf -o /path/to/output.gguf

# 指定输出目录
python -m xet.cli.commands.download user/repo/model.gguf -O /path/to/directory/
```

### 认证配置

```bash
# 设置 token（如果需要访问私有仓库）
export XET_TOKEN=your_token_here

# 或在下载时指定
python -m xet.cli.commands.download user/repo/file.bin --token your_token
```

## 高级功能

### 1. 下载模式选择

XET+ 支持三种下载模式：

#### Auto 模式（推荐，默认）
自动选择最优模式：
- 小文件（<256MB）→ Direct 模式
- 大文件（≥256MB）→ XET 模式

```bash
python -m xet.cli.commands.download user/repo/file.bin --mode auto
```

#### Direct 模式
直接下载，跳过 XET 重建：
- ✅ 速度快（2-5x）
- ✅ 资源占用低
- ❌ 不支持断点续传

```bash
python -m xet.cli.commands.download user/repo/config.json --mode direct
```

#### XET 模式
完整的 XET 重建流程：
- ✅ 支持断点续传
- ✅ 支持大文件
- ❌ 速度较慢（需要解压和重建）

```bash
python -m xet.cli.commands.download user/repo/large_model.gguf --mode xet
```

### 2. 缓存控制

#### 启用缓存（默认）
重复下载时自动使用缓存，加速 36x：

```bash
# 默认缓存到 ~/.xet/cache/xorbs/
python -m xet.cli.commands.download user/repo/model.gguf

# 下载完成后保留缓存（重复下载加速）
python -m xet.cli.commands.download user/repo/model.gguf --keep-cache

# 自定义缓存目录
python -m xet.cli.commands.download user/repo/model.gguf --cache-dir /path/to/cache
```

#### 禁用缓存
不使用缓存，每次都从网络下载：

```bash
python -m xet.cli.commands.download user/repo/model.gguf --no-cache
```

#### 缓存管理

```bash
# 查看缓存大小
du -sh ~/.xet/cache/xorbs/

# 清理缓存
rm -rf ~/.xet/cache/xorbs/*

# 清理旧缓存（7 天前）
find ~/.xet/cache/xorbs/ -type f -mtime +7 -delete
```

### 3. IP 优选（国内网络优化）

#### 命令行方式

```bash
# 启用 IP 优选
python -m xet.cli.commands.download user/repo/model.gguf --optimize-hosts

# 禁用 IP 优选
python -m xet.cli.commands.download user/repo/model.gguf --no-optimize-hosts
```

#### 配置文件方式（推荐）

```bash
# 永久启用（写入 ~/.xetrc）
xet config network.optimize_hosts true

# 查看当前配置
xet config network.optimize_hosts

# 永久禁用
xet config network.optimize_hosts false
```

#### 环境变量方式

```bash
# 在 ~/.bashrc 或 ~/.zshrc 中添加
export XET_OPTIMIZE_HOSTS=true

# 临时启用（当前会话）
XET_OPTIMIZE_HOSTS=true python -m xet.cli.commands.download user/repo/file.bin
```

#### 优先级
```
命令行参数 > 环境变量 > 配置文件 > 默认值
```

### 4. 并发控制

```bash
# 调整并发数（默认 16）
python -m xet.cli.commands.download user/repo/model.gguf --concurrent 32

# 低内存环境（减少并发）
python -m xet.cli.commands.download user/repo/model.gguf --concurrent 4

# 高带宽环境（增加并发）
python -m xet.cli.commands.download user/repo/model.gguf --concurrent 64
```

### 5. 断点续传

XET+ 自动支持断点续传，下载中断后重新运行即可继续：

```bash
# 第一次下载（中断）
python -m xet.cli.commands.download user/repo/large_model.gguf
# Ctrl+C 中断

# 继续下载（自动从断点恢复）
python -m xet.cli.commands.download user/repo/large_model.gguf
```

断点文件位置：`<output_path>.xet_checkpoint`

### 6. 内存控制（低内存环境）

默认解压缓冲区限制为 200MB，适合大多数环境：

```bash
# 查看默认设置（200MB）
python -m xet.cli.commands.download user/repo/model.gguf

# 低内存环境（如 Termux，总内存 2GB）
python -m xet.cli.commands.download user/repo/model.gguf --max-memory-mb 100

# 极低内存环境（总内存 ≤ 1GB）
python -m xet.cli.commands.download user/repo/model.gguf --max-memory-mb 64

# 高内存环境（加速解压）
python -m xet.cli.commands.download user/repo/model.gguf --max-memory-mb 400
```

**推荐值**：
- **64-100MB**: 极低内存环境（总内存 ≤ 1GB）
- **100-150MB**: 低内存环境（总内存 1-2GB，如 Termux）
- **200-300MB**: 正常环境（默认 200MB）
- **400+MB**: 高内存环境（充足内存，追求速度）

**工作原理**：
- 按需解压 xorb，而不是一次性全部解压
- 自动释放已写入的 xorb 数据
- 内存占用可控，避免 OOM

**资源使用策略**（对齐 xet.py 设计）：
- **内存：尽量节约** - 通过 `--max-memory-mb` 控制解压缓冲区，预取机制按需下载
- **磁盘：相对节约** - 磁盘缓存用于加速重复下载（36x），默认下载完成后删除
- **CPU：相对多用** - LZ4 解压、并发处理，充分利用多核
- **带宽：直接拉满** - 多线程并发下载（`--concurrent`），无限速

**预取机制**（自动启用）：
- 按 term 顺序处理，按需下载 xorb（不是一次性全部下载）
- 水位线控制：低水位 48MB，高水位 192MB
- 异步预取后续 xorb，隐藏网络延迟
- 自动释放已使用的 xorb，内存占用可控

**高级控制**（通常不需要调整）：
```bash
# 调整预取水位线（低内存环境）
python -m xet.cli.commands.download user/repo/model.gguf \
    --prefetch-low 24 \
    --prefetch-high 96

# 调整预取水位线（高内存环境）
python -m xet.cli.commands.download user/repo/model.gguf \
    --prefetch-low 96 \
    --prefetch-high 384
```

**磁盘缓存说明**：
- 默认启用但下载完成后自动删除（单次下载场景）
- 使用 `--keep-cache` 保留缓存，重复下载同一文件时加速 36x
- 使用 `--no-cache` 禁用缓存，适合磁盘空间极度紧张的环境
- **低内存环境推荐保留缓存**：用磁盘换带宽，避免重复下载

### 7. 代理设置

```bash
# 使用 HTTP 代理
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080

# 使用 SOCKS5 代理
export HTTP_PROXY=socks5://proxy.example.com:1080
export HTTPS_PROXY=socks5://proxy.example.com:1080

# 不代理某些域名
export NO_PROXY=localhost,127.0.0.1,.xethub.com
```

**注意**: 启用 IP 优选后，优选的域名会自动跳过代理（直连更快）。

## 性能优化

### 国内网络优化方案

```bash
# 1. 启用 IP 优选（必须）
xet config network.optimize_hosts true

# 2. 保留缓存（重复下载）
python -m xet.cli.commands.download user/repo/model.gguf --keep-cache

# 3. 适当提高并发（如果带宽充足）
python -m xet.cli.commands.download user/repo/model.gguf --concurrent 32

# 完整命令示例
python -m xet.cli.commands.download user/repo/model.gguf \
    --optimize-hosts \
    --keep-cache \
    --concurrent 32
```

### 小文件批量下载

```bash
# 使用 Direct 模式（跳过 XET 重建）
for file in config.json metadata.json vocab.txt; do
    python -m xet.cli.commands.download user/repo/$file --mode direct
done
```

### 大文件下载优化

```bash
# 1. 使用 XET 模式（支持断点续传）
# 2. 启用缓存
# 3. 适当并发
python -m xet.cli.commands.download user/repo/100GB_model.gguf \
    --mode xet \
    --keep-cache \
    --concurrent 16
```

### 低内存环境

```bash
# 降低内存占用（推荐）
python -m xet.cli.commands.download user/repo/model.gguf \
    --concurrent 4 \
    --max-memory-mb 100 \
    --keep-cache  # 保留缓存，避免重复下载浪费带宽

# 极低内存环境（总内存 ≤ 1GB）
python -m xet.cli.commands.download user/repo/model.gguf \
    --concurrent 2 \
    --max-memory-mb 64 \
    --keep-cache  # 用磁盘换带宽

# 磁盘空间极度紧张时才禁用缓存（会增加带宽消耗）
python -m xet.cli.commands.download user/repo/model.gguf \
    --concurrent 2 \
    --max-memory-mb 64 \
    --no-cache
```

## 故障排查

### 常见问题

#### 1. 下载速度慢

**现象**: 下载速度只有几十 KB/s

**解决方案**:
```bash
# 启用 IP 优选（国内用户必须）
python -m xet.cli.commands.download user/repo/file.bin --optimize-hosts

# 检查代理设置（可能拖慢速度）
unset HTTP_PROXY HTTPS_PROXY

# 增加并发
python -m xet.cli.commands.download user/repo/file.bin --concurrent 32
```

#### 2. 缓存未命中

**现象**: 提示 "缓存未命中" 或多次下载同一文件不加速

**解决方案**:
```bash
# 检查缓存目录是否存在
ls -la ~/.xet/cache/xorbs/

# 确保使用 --keep-cache
python -m xet.cli.commands.download user/repo/file.bin --keep-cache

# 检查磁盘空间
df -h ~/.xet/cache/
```

#### 3. 断点续传失败

**现象**: 重新下载时没有从断点继续

**解决方案**:
```bash
# 检查断点文件是否存在
ls -la output_file.gguf.xet_checkpoint

# 确保使用相同的输出路径
python -m xet.cli.commands.download user/repo/file.bin -o /same/path/file.bin

# 如果断点文件损坏，删除后重新下载
rm output_file.gguf.xet_checkpoint
```

#### 4. 认证失败

**现象**: "401 Unauthorized" 或 "403 Forbidden"

**解决方案**:
```bash
# 设置有效的 token
export XET_TOKEN=your_valid_token

# 或使用命令行参数
python -m xet.cli.commands.download user/repo/file.bin --token your_token

# 检查 token 是否过期
# （需要重新登录获取新 token）
```

#### 5. 内存不足

**现象**: "MemoryError" 或系统卡死

**解决方案**:
```bash
# 减少并发
python -m xet.cli.commands.download user/repo/file.bin --concurrent 2

# 降低内存缓冲（推荐）
python -m xet.cli.commands.download user/repo/file.bin --max-memory-mb 100

# 极低内存环境（仅降低内存占用，保留缓存以节省带宽）
python -m xet.cli.commands.download user/repo/file.bin \
    --concurrent 2 \
    --max-memory-mb 64 \
    --keep-cache

# 磁盘空间不足时才禁用缓存（会导致重复下载浪费带宽）
python -m xet.cli.commands.download user/repo/file.bin \
    --no-cache

# 使用 Direct 模式（如果文件较小）
python -m xet.cli.commands.download user/repo/file.bin --mode direct
```

**Termux 用户推荐配置**:
```bash
# 2GB 内存设备
python -m xet.cli.commands.download user/repo/model.gguf \
    --concurrent 4 \
    --max-memory-mb 100 \
    --keep-cache
```

### 日志分析

```bash
# 启用详细日志
python -m xet.cli.commands.download user/repo/file.bin --verbose

# 保存日志到文件
python -m xet.cli.commands.download user/repo/file.bin 2>&1 | tee download.log

# 查看关键信息
grep -E "ERROR|WARNING|缓存|重试" download.log
```

## 最佳实践

### 1. 国内用户配置

```bash
# 一次性配置（写入 ~/.bashrc）
cat >> ~/.bashrc << 'EOF'
# XET+ 配置
export XET_OPTIMIZE_HOSTS=true
alias xet-download='python -m xet.cli.commands.download'
EOF

source ~/.bashrc

# 之后直接使用
xet-download user/repo/model.gguf --keep-cache
```

### 2. 批量下载脚本

```bash
#!/bin/bash
# download_all.sh - 批量下载脚本

REPO="user/repo"
FILES=(
    "model-part1.gguf"
    "model-part2.gguf"
    "config.json"
)

for file in "${FILES[@]}"; do
    echo "正在下载: $file"
    python -m xet.cli.commands.download "$REPO/$file" \
        --optimize-hosts \
        --keep-cache \
        --concurrent 16 \
        || echo "下载失败: $file"
done
```

### 3. CI/CD 集成

```yaml
# .github/workflows/download.yml
name: Download Model

on: [push]

jobs:
  download:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      
      - name: Install XET+
        run: |
          git clone https://github.com/yourusername/xetplus.git
          cd xetplus
          pip install -r requirements.txt
      
      - name: Download Model
        env:
          XET_TOKEN: ${{ secrets.XET_TOKEN }}
        run: |
          python -m xet.cli.commands.download user/repo/model.gguf \
            --mode direct \
            --no-cache
```

### 4. Docker 使用

```dockerfile
# Dockerfile
FROM python:3.9-slim

# 安装 XET+
RUN git clone https://github.com/yourusername/xetplus.git /opt/xetplus && \
    cd /opt/xetplus && \
    pip install -r requirements.txt

# 设置环境变量
ENV XET_OPTIMIZE_HOSTS=true
ENV PYTHONPATH=/opt/xetplus

# 下载脚本
COPY download.sh /usr/local/bin/download.sh
RUN chmod +x /usr/local/bin/download.sh

ENTRYPOINT ["/usr/local/bin/download.sh"]
```

### 5. 定期清理缓存

```bash
# 添加到 crontab
crontab -e

# 每周日凌晨 2 点清理 7 天前的缓存
0 2 * * 0 find ~/.xet/cache/xorbs/ -type f -mtime +7 -delete
```

## 性能基准参考

### 小文件（<256MB）
```
模式: Direct
速度: 2-5x 快于 XET 模式
推荐: --mode direct
```

### 大文件（>1GB）
```
模式: XET（自动）
并发: 16-32（根据网络调整）
推荐: --keep-cache --concurrent 16
```

### 重复下载
```
缓存命中: 36x 加速
推荐: --keep-cache
```

### 国内网络
```
IP 优选: 10x 加速
推荐: xet config network.optimize_hosts true
```

## 相关文档

- [README.md](../README.md) - 项目概览
- [架构设计](XET_ARCHITECTURE_REFERENCE.md) - 技术细节
- [测试指南](TESTING_GUIDE.md) - 测试和开发
- [缓存实现](XORB_CACHE_IMPLEMENTATION.md) - 缓存详解

---

**最后更新**: 2026-06-20  
**维护者**: Claude & User
