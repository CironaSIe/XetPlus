# HOST 优选与代理协同设计分析

**日期**: 2026-06-21  
**问题来源**: P2测试中发现 `--proxy` 参数与 HOST 优选功能冲突

---

## 当前实现分析

### 优选逻辑流程

xetplus 的 HOST 优选模块（`host_optimizer.py`）**已经实现了代理协同逻辑**：

```python
# 第1步：DoH 查询获取所有 IP
all_ips = self._doh_query_all(domains)

# 第2步：双向测速（直连 vs 代理）
for ip in ips:
    # 测直连
    futures[executor.submit(self._tcp_rtt, ip, 443, False)] = (domain, ip, False)
    
    # 测代理（如果配置了代理）
    if self.proxy:
        futures[executor.submit(self._tcp_rtt, ip, 443, True)] = (domain, ip, True)

# 第3步：选择最快的方式
# 对每个域名，优选结果包含：
# - ip: 最优 IP
# - use_proxy: True/False (是否需要代理)
# - rtt: 延迟
# - speed: 传输速度
```

### should_use_proxy() 方法

```python
def should_use_proxy(self, domain: str) -> Optional[str]:
    """根据优选结果决定是否使用代理。
    
    - 直连可达的域名返回 None（不走代理）
    - 需要代理的域名返回 proxy URL
    - 未优选的域名 fallback 到全局 proxy 设置
    """
    if domain not in self.mappings:
        # 未优选的域名，使用全局代理设置
        return self.proxy if self.proxy else None
    
    # 已优选的域名，根据测速结果决定
    use_proxy = self.mappings[domain].get("use_proxy", True)
    
    if use_proxy:
        return self.proxy if self.proxy else None
    else:
        return None  # 直连更快，不走代理
```

---

## 发现的问题

### ❌ **问题 1: 优选逻辑未被正确调用**

**症状**: P2测试中，即使添加 `--proxy` 参数，仍然出现 SSL EOF 错误。

**根本原因**: 
在实际的 HTTP 请求中，`should_use_proxy()` 方法**可能没有被调用**，导致：
- 优选结果选择了直连（`use_proxy: False`）
- 但请求仍然强制使用全局代理配置
- 导致直连 IP + 代理混用 → SSL 协议冲突

**需要验证的地方**:
```bash
# 检查 HTTP 客户端是否调用了 should_use_proxy()
grep -rn "should_use_proxy" xet/ --include="*.py"
```

---

### ❌ **问题 2: 默认行为不明确**

**当前行为**:
- 如果配置了 `--proxy`，HOST 优选**默认启用**
- 优选会测试直连和代理两种方式
- 但如果直连更快，会选择直连（`use_proxy: False`）

**问题**:
用户明确指定 `--proxy` 时，期望是：
- 🤔 **期望A**: 所有流量都走代理（忽略优选结果）
- 🤔 **期望B**: 优选后智能选择（直连快就直连，需要代理才走代理）

**当前实现更接近期望B，但没有文档说明，导致用户困惑。**

---

### ✅ **问题 3: --no-optimize-hosts 的作用**

**当前实现**:
```bash
# 禁用 HOST 优选后
--no-optimize-hosts

# 行为变成：
# - 不进行 DoH 查询
# - 不进行测速
# - 所有请求使用系统 DNS + 全局代理配置
```

**这就是为什么 P2 测试加上 `--no-optimize-hosts` 后成功了！**

---

## 理想的设计方案

### 方案 A: 智能协同（推荐）✅

**设计思路**: 优选逻辑和代理配置协同工作，自动选择最优路径。

**行为**:
```bash
# 1. 没有代理配置
--no-proxy
→ 只测直连，选择最快的直连 IP

# 2. 有代理配置，启用优选（默认）
--proxy http://127.0.0.1:12334
→ 同时测直连和代理
→ 每个域名独立选择最快的方式
→ 例如：
   - huggingface.co: 直连更快 → 直连
   - cas-server.xethub.hf.co: 代理更快 → 走代理
   - transfer.xethub.hf.co: 直连更快 → 直连

# 3. 有代理配置，禁用优选
--proxy http://127.0.0.1:12334 --no-optimize-hosts
→ 所有流量强制走代理
→ 使用系统 DNS
```

**优点**:
- ✅ 自动优化，用户无需关心细节
- ✅ 充分利用国内网络优势（能直连就直连）
- ✅ 提供强制模式（`--no-optimize-hosts`）

**缺点**:
- ⚠️ 行为复杂，需要详细文档说明
- ⚠️ 用户可能困惑"为什么我设了代理还走直连"

---

### 方案 B: 简单分离（保守）

**设计思路**: 优选和代理互斥，由用户明确选择。

**行为**:
```bash
# 模式1: 国内网络优化（默认）
--optimize-hosts
→ DoH 查询 + 测速 + 优选 IP
→ 全部直连，不使用代理

# 模式2: 全部走代理
--proxy http://127.0.0.1:12334
→ 自动禁用 HOST 优选
→ 所有流量走代理

# 模式3: 混合（高级）
--proxy http://127.0.0.1:12334 --optimize-hosts
→ 同时测直连和代理
→ 每个域名选择最快方式
```

**优点**:
- ✅ 行为清晰，容易理解
- ✅ 减少意外情况

**缺点**:
- ❌ 无法充分利用混合优化的优势

---

## 推荐的修复方案

### 短期修复（立即可做）

#### 1. 修复 HTTP 客户端调用逻辑

确保所有 HTTP 请求都调用 `should_use_proxy()` 来决定是否使用代理：

```python
# 在发起请求前
domain = urlparse(url).hostname
proxy = host_optimizer.should_use_proxy(domain) if host_optimizer else self.global_proxy

session = create_robust_session(proxy=proxy)
```

#### 2. 更新 CLI 帮助文档

```bash
--proxy PROXY         HTTP/HTTPS 代理地址（如 http://127.0.0.1:7890）
                      
                      代理 + HOST 优选协同工作：
                      • 启用 HOST 优选时（默认）：同时测试直连和代理，
                        每个域名自动选择最快的方式
                      • 禁用 HOST 优选时（--no-optimize-hosts）：
                        所有流量强制走代理
                      
--optimize-hosts      启用 HOST 优选（DoH 查询 + 测速，国内网络优化）
                      与 --proxy 协同使用时，会测试直连和代理两种方式，
                      自动为每个域名选择最快的连接方式
                      
--no-optimize-hosts   禁用 HOST 优选
                      使用代理时建议添加此参数，确保所有流量走代理
```

#### 3. 添加日志提示

在优选完成后打印摘要：

```python
logger.info("[HostOpt] 优选完成:")
for domain, result in mappings.items():
    mode = "代理" if result["use_proxy"] else "直连"
    logger.info(f"  {domain}: {mode} ({result['ip']}, RTT {result['rtt']*1000:.1f}ms)")
```

---

### 长期优化（需要测试）

#### 1. 智能缓存失效

当用户切换代理配置时，自动刷新优选缓存：

```python
def __init__(self, proxy: str = ""):
    self.proxy = proxy
    
    # 如果代理配置变化，清除缓存
    cached_proxy = self._get_cached_proxy_config()
    if cached_proxy != proxy:
        logger.info("[HostOpt] 代理配置变化，清除优选缓存")
        self._clear_cache()
```

#### 2. 增强测速准确性

当前的 TCP RTT 测速可能不准确：

```python
def _tcp_rtt(self, ip: str, port: int, use_proxy: bool):
    if use_proxy and self.proxy:
        # ❌ 当前实现：测的是到代理服务器的延迟
        # ✅ 应该改为：通过代理连接到目标IP的延迟
        
        # 建议实现：HTTP CONNECT 隧道测延迟
        return self._tcp_rtt_via_proxy(ip, port)
```

#### 3. 提供配置选项

```bash
# 在 ~/.xet/config.json 中
{
  "network": {
    "optimize_hosts": true,
    "proxy_policy": "auto",  # auto | force_proxy | force_direct
    "prefer_direct": true    # 当直连和代理速度接近时，优先直连
  }
}
```

---

## 测试验证

### 验证当前实现

```bash
# 1. 检查 should_use_proxy 是否被调用
grep -rn "should_use_proxy" xet/ --include="*.py"

# 2. 查看优选缓存
cat ~/.xet/cache/host_optimize.json | python -m json.tool

# 3. 测试混合模式
python -m xet.cli.main download \
    mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --proxy http://127.0.0.1:12334 \
    --optimize-hosts \
    --token $HF_TOKEN \
    -o test_mixed.gguf \
    2>&1 | grep -E "优选|直连|代理|HostOpt"
```

### 添加单元测试

```python
def test_proxy_optimization_mixed():
    """测试代理 + 优选混合模式"""
    optimizer = HostOptimizer(proxy="http://127.0.0.1:12334")
    optimizer.optimize(["huggingface.co", "transfer.xethub.hf.co"])
    
    # 验证每个域名都有优选结果
    assert "huggingface.co" in optimizer.mappings
    assert "use_proxy" in optimizer.mappings["huggingface.co"]
    
    # 验证 should_use_proxy 返回正确结果
    hf_proxy = optimizer.should_use_proxy("huggingface.co")
    if optimizer.mappings["huggingface.co"]["use_proxy"]:
        assert hf_proxy == "http://127.0.0.1:12334"
    else:
        assert hf_proxy is None
```

---

## 结论

你的建议完全正确！**HOST 优选逻辑应该与代理配置协同工作**，而不是互斥。

### 当前状态
- ✅ 代码层面：优选逻辑**已经支持**代理协同（测试直连和代理）
- ❌ 实际使用：`should_use_proxy()` 可能未被正确调用
- ❌ 文档层面：没有说明协同工作机制

### 下一步
1. 验证 HTTP 客户端是否调用了 `should_use_proxy()`
2. 更新文档说明协同机制
3. 添加日志输出优选决策
4. 测试混合模式是否真正工作

**关键问题**: 需要检查为什么P2测试中必须加 `--no-optimize-hosts` 才能成功，这说明优选结果可能没有被正确应用到实际请求中。
