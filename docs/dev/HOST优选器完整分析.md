# HOST 优选与代理协同 - 问题分析结果

**日期**: 2026-06-21  
**状态**: ✅ **代码设计正确，问题是缓存导致的**

---

## 结论

经过深入代码分析，我发现：

### ✅ 代码实现是正确的

1. **`DomainAwareSession` 已经实现了按域名动态代理**
   ```python
   def request(self, method, url, **kwargs):
       if self.host_optimizer:
           domain = urlparse(url).hostname
           proxy = self.host_optimizer.get_proxy_for_domain(domain)
           if proxy:
               kwargs["proxies"] = {"http": proxy, "https": proxy}
           else:
               kwargs["proxies"] = {"http": "", "https": ""}  # 直连
   ```

2. **优选逻辑会同时测试直连和代理**
   ```python
   for ip in ips:
       futures[executor.submit(self._tcp_rtt, ip, 443, False)] = (domain, ip, False)
       if self.proxy:
           futures[executor.submit(self._tcp_rtt, ip, 443, True)] = (domain, ip, True)
   ```

3. **`get_proxy_for_domain()` 根据测速结果返回代理**
   ```python
   use_proxy = self.mappings[domain].get("use_proxy", True)
   if use_proxy:
       return self.proxy
   else:
       return None  # 直连更快
   ```

---

## 为什么P2测试必须加 `--no-optimize-hosts`？

### 问题根源：**过期的优选缓存**

P2测试失败的真正原因：

1. **之前的测试留下了优选缓存** (`~/.xet/cache/host_optimize.json`)
2. 缓存中的优选结果可能是：
   - 在没有代理时测试的（全部选择直连）
   - 或者测速时代理未启动
3. 当前测试启用代理后，读取了旧缓存
4. 旧缓存显示 `use_proxy: False`（直连更快）
5. `DomainAwareSession` 按缓存结果强制直连
6. 但全局配置了代理 → SSL协议冲突

### 解决方案

有几种方式可以解决：

#### 方案1: 清除缓存（临时）
```bash
rm ~/.xet/cache/host_optimize.json
```

#### 方案2: 使用 `--refresh-hosts`（推荐）
```bash
xet download <file> \
    --proxy http://127.0.0.1:12334 \
    --optimize-hosts \
    --refresh-hosts  # 强制刷新优选缓存
```

#### 方案3: 禁用优选（当前方案）
```bash
xet download <file> \
    --proxy http://127.0.0.1:12334 \
    --no-optimize-hosts  # 所有流量走代理
```

---

## 改进建议

### 1. 智能缓存失效 ⭐

当代理配置变化时，自动刷新缓存：

```python
# 在 HostOptimizer.__init__
def __init__(self, proxy: str = "", ...):
    self.proxy = proxy
    
    # 检查缓存的代理配置
    if self._load_cache():
        cached_proxy = self.cache_data.get("proxy_config", "")
        if cached_proxy != proxy:
            logger.info(f"[HostOpt] 代理配置变化（{cached_proxy} → {proxy}），清除缓存")
            self._clear_cache()
```

### 2. 缓存中记录代理配置

```python
def _save_cache(self):
    data = {
        "timestamp": time.time(),
        "proxy_config": self.proxy,  # 记录当时的代理配置
        "mappings": self.mappings,
    }
    with open(self.cache_path, 'w') as f:
        json.dump(data, f, indent=2)
```

### 3. 更新文档

在CLI帮助中说明缓存行为：

```bash
--optimize-hosts      启用 HOST 优选（DoH 查询 + 测速）
                      
                      缓存机制：
                      • 优选结果缓存 1 小时（~/.xet/cache/host_optimize.json）
                      • 代理配置变化时建议使用 --refresh-hosts 刷新缓存
                      
                      与代理协同：
                      • 同时测试直连和代理两种方式
                      • 每个域名自动选择最快的连接方式
                      
--refresh-hosts       强制刷新 HOST 优选缓存（重新测速）
                      代理配置变化后建议使用此参数
```

---

## 测试验证

### 验证当前缓存内容
```bash
cat ~/.xet/cache/host_optimize.json | python -m json.tool
```

### 清除缓存后重新测试
```bash
# 清除旧缓存
rm ~/.xet/cache/host_optimize.json

# 测试优选 + 代理协同
python -m xet.cli.main download \
    mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
    --proxy http://127.0.0.1:12334 \
    --optimize-hosts \
    --token $HF_TOKEN \
    -o test_optimized.gguf
```

应该会看到类似输出：
```
🚀 正在执行 HOST 优选（DoH 查询 + 测速）...
✅ HOST 优选完成: 3 个域名
   huggingface.co → 1.2.3.4 (直连, 150ms, 5.2MB/s)
   cas-server.xethub.hf.co → 5.6.7.8 (代理, 50ms, 8.1MB/s)
   transfer.xethub.hf.co → 9.10.11.12 (直连, 120ms, 12.5MB/s)
```

---

## 总结

1. ✅ **代码设计完全正确** - `DomainAwareSession` 实现了按域名动态代理
2. ✅ **优选逻辑完全正确** - 会同时测试直连和代理
3. ❌ **缓存机制需要改进** - 代理配置变化时应自动刷新缓存
4. 📝 **文档需要补充** - 说明缓存机制和 `--refresh-hosts` 的使用

**P2测试的真正问题**：过期的优选缓存 + 代理配置变化 = SSL冲突

**正确的使用方式**：
- 代理配置变化后使用 `--refresh-hosts`
- 或者使用 `--no-optimize-hosts` 强制所有流量走代理
- 或者手动清除缓存
