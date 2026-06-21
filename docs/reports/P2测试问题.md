# P2 测试脚本问题分析

## 问题发现时间
2026-06-21 23:39

## 核心问题

### 1. 代理配置错误 ❌ **[P0-严重]**

**问题描述：**
- 测试脚本设置 `PROXY="http://127.0.0.1:12334"` 但未检查代理是否启动
- 所有请求因代理拒绝连接失败：`[Errno 111] Connection refused`

**影响：**
- 所有网络请求失败
- 无法测试真实的下载功能

**修复方案：**
```bash
# 在脚本开始添加代理检查
if ! curl -x "$PROXY" --connect-timeout 3 -s https://www.google.com > /dev/null 2>&1; then
    echo "❌ 代理不可用，请启动代理"
    exit 1
fi
```

---

### 2. 荒谬的分片配置 😂 **[P1-严重逻辑错误]**

**问题描述：**
```bash
# test_cli_p2_advanced.sh:281
--segment-size 256    # 256 MB 分片大小
```

**文件实际大小：**
- 100.58 MB (105,467,232 bytes)

**后果：**
- 创建了 49 个段（段 0-48）
- 第一个段包含整个文件
- 剩余 48 个段全是空的/无效的
- 日志显示所有 49 个段都失败了

**合理配置应该是：**
- 文件 100MB → 分片大小应为 10-30MB
- 例如：`--segment-size 20` → 约 5 个段

**搞笑指数：** ⭐⭐⭐⭐⭐
就像用卡车运一个快递包裹，然后派出 48 辆空卡车跟着！

---

### 3. Reconstruction 数据类型错误 **[P0-崩溃]**

**错误信息：**
```
ERROR: [SegmentedReconstructor] 段 0-48 失败: 'bytes' object has no attribute 'chunk_offsets'
```

**问题分析：**
reconstruction 数据应该是解析后的结构体（有 `chunk_offsets` 等属性），但实际被当作原始 `bytes` 传递。

**可能原因：**
1. `get_segment_reconstruction()` 返回原始响应而非解析后的对象
2. 分段重构器期望的数据结构不匹配
3. API 响应格式变化但代码未更新

**需要检查：**
- `xetplus/reconstruction.py` 中的数据解析逻辑
- `SegmentedReconstructor` 期望的数据类型
- API 返回的实际响应格式

---

### 4. 环境变量传递问题 **[P2-次要]**

**问题：**
测试脚本使用：
```bash
python -m xet.cli.main download ... --proxy "$PROXY"
```

但某些 HTTP 库可能优先读取环境变量 `HTTPS_PROXY`，导致：
- `--proxy` 参数被忽略
- 连接走系统默认代理或直连

**修复：**
```bash
HTTPS_PROXY=$PROXY python -m xet.cli.main download ...
```

---

## 修复版脚本

已创建 `test_cli_p2_fixed.sh` 包含以下改进：

### ✅ 改进点

1. **代理检查** 
   - 启动前验证代理可用性
   - 失败时给出明确提示

2. **合理的分片配置**
   - 100MB 文件 → 20MB 分片
   - 预期产生约 5 个段

3. **环境变量传递**
   - 使用 `HTTPS_PROXY=$PROXY` 前缀

4. **精简测试用例**
   - 6 个测试 → 3 个核心测试
   - 移除不必要的 DNS/重试测试（这些是内部实现细节）

---

## 运行修复版脚本

```bash
cd ~/xetplus

# 1. 启动代理（如果未启动）
# export HTTPS_PROXY=http://127.0.0.1:12334

# 2. 运行修复版测试
./test_cli_p2_fixed.sh
```

---

## 建议的后续工作

### 1. 修复 reconstruction 数据解析 **[优先级：P0]**
- 检查 `get_segment_reconstruction()` 返回类型
- 确保返回解析后的结构体而非原始 bytes

### 2. 添加分片大小验证 **[优先级：P1]**
- 在 CLI 参数解析时检查 `--segment-size` 是否合理
- 如果 `segment-size > file-size`，警告或自动调整

```python
if segment_size_mb * 1024 * 1024 > file_size:
    logger.warning(
        f"Segment size ({segment_size_mb}MB) > file size ({file_size/1024/1024:.1f}MB), "
        f"adjusting to {max(1, file_size // (10 * 1024 * 1024))}MB"
    )
```

### 3. 改进测试脚本健壮性 **[优先级：P2]**
- 添加前置条件检查（代理、token、网络）
- 提供更有意义的错误信息
- 自动清理失败的输出文件

---

## 代码审查建议

**需要检查的文件：**
1. `xetplus/reconstruction.py` - reconstruction 数据解析
2. `xetplus/segmented_reconstructor.py` - 分段重构逻辑
3. `xetplus/cli/main.py` - CLI 参数验证

**需要验证的逻辑：**
- 分段数量计算是否正确
- 空段是否被跳过
- 数据类型转换是否完整
