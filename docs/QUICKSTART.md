# XET+ 快速开始

> 5 分钟快速上手 XET+ - 高性能 XET 协议下载工具

---

## 📦 安装

### 前置要求

- Python 3.9+
- pip

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/yourusername/xetplus.git
cd xetplus

# 2. 安装依赖
pip install -r requirements.txt

# 3. 验证安装
python -m xet.cli.main --help
```

---

## 🚀 基础使用

### 查看文件信息

快速查看 XET 文件的元数据：

```bash
python -m xet.cli.main info mykor/granite-embedding-97m-multilingual-r2-GGUF/model.gguf
```

**输出示例**：
```
📄 model.gguf
  类型: XET ✅
  大小: 100.6 MB (105,467,232 bytes)
  Xet Hash: e0aacd103e054264f5ede71ce63218c1...
  SHA256: 355f1f30ac3bdad09de420c5d78dd369...
  Terms: 17
  Xorbs: 10 (unique)
```

### 下载单个文件

```bash
python -m xet.cli.main download mykor/granite-embedding-97m-multilingual-r2-GGUF/model.gguf
```

默认下载到当前目录，使用 `-o` 指定输出路径：

```bash
python -m xet.cli.main download user/repo/file.gguf -o ./models/model.gguf
```

### 批量下载

使用 glob 模式匹配下载多个文件：

```bash
# 下载所有 Q4 量化的 GGUF 文件
python -m xet.cli.main download mykor/granite-embedding-97m-multilingual-r2-GGUF \
    --include "*Q4*.gguf"

# 下载所有 .safetensors 文件
python -m xet.cli.main download user/repo \
    --include "*.safetensors" \
    -o ./models/
```

---

## 🌐 国内网络优化

### 方案1：使用 hf-mirror（推荐）

**无需代理**，直接使用国内镜像：

```bash
python -m xet.cli.main download user/repo/file.gguf \
    --hf-endpoint https://hf-mirror.com
```

### 方案2：使用代理

通过环境变量设置代理：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
python -m xet.cli.main download user/repo/file.gguf
```

或命令行参数：

```bash
python -m xet.cli.main download user/repo/file.gguf \
    --proxy http://127.0.0.1:7890
```

### 方案3：启用 HOST 优选

自动选择最快的 IP（需要代理配合）：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 \
python -m xet.cli.main download user/repo/file.gguf \
    --optimize-hosts
```

**效果**：国内网络速度提升 3-10x

> 详细网络配置请参考：[docs/NETWORK_OPTIONS_GUIDE.md](NETWORK_OPTIONS_GUIDE.md)

---

## 🔧 配置管理

### 持久化配置

避免每次输入参数，配置保存到 `~/.xetrc`：

```bash
# 设置 HuggingFace token
python -m xet.cli.main config xet.token YOUR_HF_TOKEN

# 设置默认并发数
python -m xet.cli.main config download.concurrency 16

# 设置默认端点
python -m xet.cli.main config xet.endpoint https://hf-mirror.com

# 启用 HOST 优选
python -m xet.cli.main config network.optimize_hosts true
```

### 查看配置

```bash
# 列出所有配置
python -m xet.cli.main config --list

# 获取单个配置
python -m xet.cli.main config --get xet.token
```

### 删除配置

```bash
# 删除指定配置
python -m xet.cli.main config --unset xet.token

# 删除嵌套配置
python -m xet.cli.main config --unset network.optimize_hosts
```

---

## 🎯 常用场景

### 场景1：下载 HuggingFace 大模型（国内）

```bash
# 一次性配置
python -m xet.cli.main config xet.endpoint https://hf-mirror.com
python -m xet.cli.main config xet.token YOUR_HF_TOKEN

# 下载模型
python -m xet.cli.main download Qwen/Qwen2.5-7B-Instruct-GGUF \
    --include "*.gguf" \
    -o ./models/qwen2.5-7b/
```

### 场景2：断点续传

网络中断？没问题，自动从断点恢复：

```bash
# 第一次下载（中断）
python -m xet.cli.main download user/repo/large_file.gguf

# 恢复下载（自动检测 checkpoint）
python -m xet.cli.main download user/repo/large_file.gguf
```

### 场景3：高并发下载

大文件？增加并发数：

```bash
python -m xet.cli.main download user/repo/large_file.gguf \
    --concurrency 32
```

### 场景4：查看文件是否为 XET 格式

```bash
# 检查单个文件
python -m xet.cli.main info user/repo/file.gguf

# 批量检查
python -m xet.cli.main info user/repo --include "*.gguf"
```

---

## ⚡ 性能优化技巧

### 1. Xorb 缓存加速

XET+ 自动缓存下载的 xorb，重复下载速度提升 **36x**：

```bash
# 第一次：正常下载
python -m xet.cli.main download user/repo/model_v1.gguf

# 第二次：如果模型只是轻微修改，大部分 xorb 命中缓存
python -m xet.cli.main download user/repo/model_v2.gguf
```

### 2. 并行批量写入（实验性）

大文件写入性能提升 **2-3x**：

```bash
python -m xet.cli.main download user/repo/large_file.gguf \
    --parallel-write
```

### 3. 调整预取水位线

控制内存使用和下载速度的平衡：

```bash
# 低内存环境
python -m xet.cli.main download user/repo/file.gguf \
    --prefetch-low 24 \
    --prefetch-high 96

# 高内存环境（更激进预取）
python -m xet.cli.main download user/repo/file.gguf \
    --prefetch-low 96 \
    --prefetch-high 384
```

---

## 🔍 故障排查

### 问题1：401 Unauthorized

**原因**：需要 HuggingFace token

**解决**：
```bash
# 设置 token
python -m xet.cli.main config xet.token YOUR_HF_TOKEN

# 或命令行传递
python -m xet.cli.main download user/repo/file.gguf --token YOUR_TOKEN
```

### 问题2：下载速度慢（国内）

**解决方案**（按优先级）：

1. **使用 hf-mirror**（推荐）：
   ```bash
   python -m xet.cli.main config xet.endpoint https://hf-mirror.com
   ```

2. **启用 HOST 优选 + 代理**：
   ```bash
   HTTPS_PROXY=http://127.0.0.1:7890 \
   python -m xet.cli.main download user/repo/file.gguf --optimize-hosts
   ```

3. **直接使用代理**：
   ```bash
   export HTTPS_PROXY=http://127.0.0.1:7890
   ```

### 问题3：文件校验失败

**原因**：下载损坏或网络问题

**解决**：
```bash
# 删除部分下载的文件
rm -rf file.gguf file.gguf.part checkpoint_file.gguf.json

# 重新下载
python -m xet.cli.main download user/repo/file.gguf
```

### 问题4：磁盘空间不足

XET+ 下载过程中会占用额外空间（checkpoint + xorb cache）：

- **Checkpoint 文件**：与原文件同目录，`.json` 后缀
- **Xorb 缓存**：`~/.cache/xet/xorbs/`

清理缓存：
```bash
# 清理 xorb 缓存
rm -rf ~/.cache/xet/xorbs/

# 清理 checkpoint 文件
rm -f *.json
```

---

## 📚 进一步阅读

### 用户文档
- [完整使用指南](USER_GUIDE.md) - 所有命令和参数详解
- [网络选项指南](NETWORK_OPTIONS_GUIDE.md) - 国内网络优化完整方案

### 开发文档
- [架构设计](ARCHITECTURE.md) - 理解 XET+ 内部结构
- [贡献指南](CONTRIBUTING.md) - 如何参与开发
- [测试指南](TESTING_GUIDE.md) - 运行和编写测试

### 技术深入
- [XET Hash 提取方法](XET_HASH_EXTRACTION_METHODS.md) - 协议细节
- [HuggingFace vs hf-mirror](HUGGINGFACE_VS_HFMIRROR.md) - 端点对比

---

## 🤝 获取帮助

- **命令帮助**：`python -m xet.cli.main --help`
- **问题报告**：[GitHub Issues](https://github.com/yourusername/xetplus/issues)
- **功能建议**：[GitHub Discussions](https://github.com/yourusername/xetplus/discussions)

---

**下一步**：查看 [用户指南](USER_GUIDE.md) 了解更多高级功能！
