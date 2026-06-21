# 优选器缓存修复 + P3测试脚本

**日期**: 2026-06-21  
**状态**: ✅ 已修复 + P3脚本已创建

---

## 修复内容

### 1. HOST 优选器缓存感知代理配置 ✅

#### 修改文件
`xet/network/host_optimizer.py`

#### 修改内容

**A. 保存缓存时记录代理配置**
```python
def _save_cache(self) -> None:
    """保存优选缓存。"""
    try:
        data = {
            "timestamp": time.time(),
            "proxy_config": self.proxy,  # 新增：记录代理配置
            "mappings": self.mappings,
        }
```

**B. 加载缓存时检查代理配置变化**
```python
def _load_cache(self) -> bool:
    """加载优选缓存。"""
    # ... 时间戳检查 ...
    
    # 新增：检查代理配置是否变化
    cached_proxy = data.get("proxy_config", "")
    if cached_proxy != self.proxy:
        logger.info(
            f"[HostOpt] 代理配置变化（缓存: {cached_proxy or '无'} → 当前: {self.proxy or '无'}），清除缓存"
        )
        return False  # 使缓存失效，重新优选
```

#### 效果

**修复前**:
```bash
# 场景1：之前没有代理时测试
xet download ... --optimize-hosts  # 缓存：全部直连

# 场景2：现在有代理
xet download ... --proxy http://127.0.0.1:12334 --optimize-hosts
# ❌ 读取旧缓存 → 强制直连 → SSL冲突
```

**修复后**:
```bash
# 场景1：之前没有代理时测试
xet download ... --optimize-hosts  # 缓存：全部直连

# 场景2：现在有代理
xet download ... --proxy http://127.0.0.1:12334 --optimize-hosts
# ✅ 检测到代理配置变化 → 清除缓存 → 重新测速 → 智能选择
# 输出：[HostOpt] 代理配置变化（缓存: 无 → 当前: http://127.0.0.1:12334），清除缓存
```

---

## P3 测试脚本

### 创建文件
`test_cli_p3_integration.sh`

### 测试用例

#### TC-P3-01: info 命令 ⏱️ ~1分钟
```bash
xet info user/repo/file.gguf --token <token>
```
- ✅ 验证：显示 Xet Hash
- ✅ 验证：显示文件大小
- ✅ 验证：显示 SHA256

#### TC-P3-02: config 命令 ⏱️ ~2分钟
```bash
xet config xet.token test_token
xet config --list
xet config --unset xet.token
```
- ✅ 验证：配置保存成功
- ✅ 验证：配置显示正确
- ✅ 验证：配置删除成功

#### TC-P3-03: 完整下载工作流 ⏱️ ~5-10分钟
```bash
xet download user/repo/file.gguf \
    --token <token> \
    --proxy <proxy> \
    --concurrency 6
```
- ✅ 验证：完整流程无错误
- ✅ 验证：文件大小和SHA256正确

#### TC-P3-04: 批量下载所有 Q4 模型 ⏱️ ~10-20分钟
```bash
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF \
    --include "*Q4*.gguf" \
    --token <token> \
    --proxy <proxy> \
    -o batch_q4/
```
- ✅ 验证：匹配并下载所有 Q4 模型
- ✅ 验证：下载的文件数量 > 0
- ✅ 验证：至少一个文件校验正确

**仓库中的 Q4 模型**:
- `granite-embedding-97M-multilingual-r2-Q4_0.gguf`
- `granite-embedding-97M-multilingual-r2-Q4_K_M.gguf`
- `granite-embedding-97M-multilingual-r2-Q4_K_S.gguf`

---

## 运行测试

### 前置条件
1. 启动代理：`http://127.0.0.1:12334`
2. 设置环境变量：`export HTTPS_PROXY=http://127.0.0.1:12334`
3. HF Token 已配置（脚本中硬编码）

### 执行命令
```bash
cd ~/xetplus
./test_cli_p3_integration.sh
```

### 预计时间
- 总耗时：15-30 分钟
- 最耗时的是 TC-P3-04（批量下载多个文件）

---

## 测试进度总览（更新后）

```
测试阶段      状态      进度    用例数  说明
══════════════════════════════════════════════════════════
P0 - 核心功能  ✅ 完成   5/5      5个   基础下载、revision等
P1 - 重要功能  ✅ 完成   8/8      8个   批量、缓存、断点续传
P2 - 高级功能  ✅ 完成   3/3      3个   内存控制、分段、并行写入
P3 - 集成测试  🆕 就绪   0/4      4个   完整工作流、批量下载
──────────────────────────────────────────────────────────
总计                   16/20    20个   已完成 80%
```

---

## 修复验证

### 验证缓存失效逻辑

```bash
# 1. 清除旧缓存
rm ~/.xet/cache/host_optimize.json

# 2. 第一次测试（无代理）
python -m xet.cli.main download \
    mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --optimize-hosts \
    --token $HF_TOKEN \
    -o test1.gguf

# 查看缓存
cat ~/.xet/cache/host_optimize.json | grep proxy_config
# 输出: "proxy_config": ""

# 3. 第二次测试（有代理）
python -m xet.cli.main download \
    mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --proxy http://127.0.0.1:12334 \
    --optimize-hosts \
    --token $HF_TOKEN \
    -o test2.gguf

# 应该看到日志：
# [HostOpt] 代理配置变化（缓存: 无 → 当前: http://127.0.0.1:12334），清除缓存
# 🚀 正在执行 HOST 优选（DoH 查询 + 测速）...
```

---

## 后续工作

### 1. 运行P3测试
```bash
./test_cli_p3_integration.sh
```

### 2. 文档更新
更新用户文档说明：
- 缓存机制（1小时TTL）
- 代理配置变化时自动刷新
- `--refresh-hosts` 手动强制刷新

### 3. 性能优化（可选）
- 减少DoH查询时间
- 优化测速并发度
- 考虑增量优选（只测新增域名）

---

## 关键发现总结

### ✅ 代码设计正确
- `DomainAwareSession` 实现完善
- `should_use_proxy()` 逻辑正确
- 优选器会同时测直连和代理

### ❌ 缓存机制有缺陷（已修复）
- 缓存不感知代理配置变化
- 导致代理配置改变后使用过期的优选结果
- 修复：保存和加载时检查 `proxy_config`

### 📝 用户体验改进
- 自动感知代理变化，无需手动清缓存
- 更好的日志提示
- 减少 `--refresh-hosts` 的使用频率
