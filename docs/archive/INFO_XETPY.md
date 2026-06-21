# ~/xet.py 完整代码分析报告

## 📊 代码统计

### 文件结构
```
xet.py/
├── xet_dl.py              # CLI 入口 (主程序)
└── xet/                   # 核心模块
    ├── __init__.py        # 61 行
    ├── auth.py            # 278 行 - 认证模块
    ├── cas_client.py      # 954 行 - CAS API 客户端
    ├── config.py          # 309 行 - 配置管理
    ├── http_utils.py      # 985 行 - HTTP 工具和 HOST 优选
    ├── merklehash.py      # 130 行 - Blake3 哈希
    ├── reconstructor.py   # 2362 行 - 文件重建引擎
    ├── types.py           # 435 行 - 数据类型定义
    └── xorb_deserializer.py # 534 行 - Xorb 反序列化

总计: ~6048 行核心代码 + CLI
```

### 类和函数统计
- **总类数**: 20 个核心类
- **总函数数**: ~177 个函数/方法
- **测试覆盖**: 缺少系统化测试

---

## 🏗️ 核心架构

### 模块依赖关系
```
xet_dl.py (CLI)
    ↓
┌────────────────────────────────────────┐
│ auth.py (XetAuth)                      │
│  - HF Token → CAS Token 转换           │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ cas_client.py (CASClient)              │
│  - Stage 1: get_reconstruction()       │
│  - Stage 2: get_xorb_data()            │
│  - URL 刷新、重试、并发控制            │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ reconstructor.py                       │
│  - FileReconstructor (小文件)         │
│  - StreamFileReconstructor (大文件)   │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ xorb_deserializer.py (XorbDeserializer)│
│  - 反序列化 xorb 容器                  │
│  - 支持 3 种压缩方案                   │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ merklehash.py                          │
│  - Blake3 keyed hash 计算              │
└────────────────────────────────────────┘

辅助模块:
├── http_utils.py - 网络优化 (HOST 优选)
├── config.py - 环境变量配置
└── types.py - 数据结构定义
```

---

## 🔑 核心类详解

### 1. XetAuth (auth.py)
```python
class XetAuth:
    """HuggingFace Token → CAS Token 认证管理器"""
```

**职责**:
- HF Token 验证
- 获取 XET read token
- CAS endpoint 和 access token 获取
- Token 缓存和刷新

**关键方法**:
- `get_token(repo_id, auth_url)` - 获取 CAS token
- `refresh_token(repo_id)` - 刷新过期 token

**关键特性**:
- ✅ 自动 token 缓存
- ✅ 401 时自动刷新
- ✅ 支持多 repo 并发认证

---

### 2. CASClient (cas_client.py - 954 行)
```python
class CASClient:
    """CAS API 客户端 - XET 协议核心"""
```

**职责**:
- Stage 1: 获取 reconstruction 信息
- Stage 2: 下载 xorb 数据
- V2/V1 API 自动切换
- URL 自动刷新
- 重试和并发控制

**关键方法**:
```python
# Stage 1: 获取文件重建信息
def get_reconstruction(file_hash: str) -> QueryReconstructionResponse

# Stage 2: 下载 xorb 数据
def get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash) -> bytes

# 流式下载（支持低速检测）
def get_xorb_data_streaming(url, url_range, min_speed, check_interval) -> bytes
```

**内置子组件**:
1. **RetryCoordinator** - 智能重试协调
   - 5xx 错误立即重试
   - 401 触发 URL 刷新
   - 429 等待后重试
   - 指数退避策略

2. **URLRefreshCoordinator** - URL 刷新管理
   - Single-flight 机制（同一 file_hash 只刷新一次）
   - 自动更新所有 pending 请求的 URL
   - 线程安全

3. **AdaptiveConcurrencyController** - 自适应并发控制
   - 根据错误率动态调整并发数
   - 防止雪崩（错误率高时降低并发）
   - 支持手动强制并发数

4. **低速检测** (LowSpeedTimeoutError)
   - 每 N 秒检查下载速度
   - 低于阈值（如 50 KB/s）持续 M 秒触发重试
   - 防止连接假死

**V2 API 支持**:
- ✅ 自动检测 V2 响应格式
- ✅ V2 不可用时 fallback 到 V1
- ✅ multipart ranges 优化

---

### 3. FileReconstructor (reconstructor.py - 2362 行)
```python
class FileReconstructor:
    """原始全量加载重建器（小文件 <100MB）"""
```

**职责**:
- 并发下载所有 xorb
- multipart segments 合并
- 文件数据重建
- SHA256 校验

**关键流程**:
```python
def download_and_reconstruct(file_hash, recon, expected_sha256):
    # 1. Terms 覆盖校验
    # 2. 并发下载所有 xorbs（multipart 支持）
    # 3. 反序列化并缓存
    # 4. 按 terms 顺序重建数据
    # 5. SHA256 校验
    return file_data
```

**Multipart 处理** (关键实现):
```python
def _download_single_xorb(xorb_hash, fetch_infos, file_hash):
    """下载单个 xorb 的所有 segments 并合并"""
    
    # 按 chunk_range.start 排序
    sorted_infos = sorted(fetch_infos, key=lambda fi: fi.chunk_range.start)
    
    # 分别下载每个 segment
    all_pieces = []
    for fi in sorted_infos:
        part_bytes = cas_client.get_xorb_data_with_retry(
            fi.url, fi.url_range, xorb_hash, file_hash
        )
        all_pieces.append((fi.chunk_range.start, part_bytes))
    
    # 分别反序列化并合并
    combined_offsets = []
    combined_data = bytearray()
    
    for base_chunk_start, raw_bytes in all_pieces:
        piece = XorbDeserializer.deserialize(raw_bytes)
        base_data_offset = len(combined_data)
        
        # 全局索引转换
        for local_idx, local_offset in piece.chunk_offsets:
            global_chunk_idx = base_chunk_start + local_idx
            global_data_offset = base_data_offset + local_offset
            combined_offsets.append((global_chunk_idx, global_data_offset))
        
        combined_data.extend(piece.data)
    
    return XorbBlockData(combined_offsets, bytes(combined_data))
```

**特点**:
- ✅ 所有数据加载到内存
- ✅ 适合小文件（<100MB）
- ✅ 简单高效
- ❌ 大文件内存爆炸

---

### 4. StreamFileReconstructor (reconstructor.py)
```python
class StreamFileReconstructor:
    """流式分片重建器（大文件 >100MB）"""
```

**职责**:
- 流式下载和写入
- 缓冲区管理
- 预取优化
- Windows 多线程写盘支持

**架构** (生产者-消费者模式):
```
Term 循环线程 (main)
    ↓ 下载 xorb 并提取 term 数据
写队列 (Queue)
    ↓ 缓冲控制
Writer 线程
    ↓ seek + write
目标文件
```

**关键特性**:
1. **缓冲区管理**:
   - `perfile_buffer_size`: 单文件缓冲（默认 64MB）
   - `total_buffer_size`: 全局缓冲（默认 256MB）
   - 自动阻塞防止内存爆炸

2. **预取优化**:
   - 低水位线触发预取（默认 48MB）
   - 高水位线暂停预取（默认 192MB）
   - 平衡 I/O 效率和内存

3. **Windows 多线程写盘修复**:
   ```python
   def _open_file_shared_write(path):
       """Windows: CreateFileW(FILE_SHARE_READ | FILE_SHARE_WRITE)
          允许多个线程同时写入同一文件"""
   ```

4. **Reference 操作支持**:
   - 从已写入的文件内容复制数据
   - 实现文件内去重

**配置** (环境变量兼容 hf-xet):
```bash
HF_XET_RECONSTRUCTION_DOWNLOAD_BUFFER_SIZE=256m
HF_XET_RECONSTRUCTION_DOWNLOAD_BUFFER_PERFILE_SIZE=64m
HF_XET_RECONSTRUCTION_DOWNLOAD_BUFFER_LIMIT=512m
HF_XET_RECONSTRUCT_WRITE_SEQUENTIALLY=true
HF_XET_NUM_CONCURRENT_RANGE_GETS=4
```

---

### 5. HostOptimizer (http_utils.py - 985 行)
```python
class HostOptimizer:
    """HOST 优选管理器 - 国内网络优化关键"""
```

**职责**:
- DoH 查询域名 IP
- 双向测速（直连 vs 代理）
- Monkey-patch getaddrinfo
- 按域名动态设置代理

**优化目标域名**:
```python
HOST_GROUPS = {
    "api": ["huggingface.co"],              # HF API（通常被墙）
    "cas": ["cas-server.xethub.hf.co"],     # CAS reconstruction
    "data": ["transfer.xethub.hf.co"],      # xorb 下载（流量最大）
}
```

**DoH 服务器** (国内优先):
```python
DOH_SERVERS = [
    "https://dns.alidns.com/resolve",       # 阿里云（国内直连）
    "https://223.5.5.5/dns-query",          # 阿里云备选
    "https://cloudflare-dns.com/dns-query", # Cloudflare（需代理）
    "https://dns.google/resolve",           # Google（需代理）
]
```

**优选流程**:
```
1. DoH 并行查询多个 DNS → 取 IP 并集
   └─ 缓存 24h (~/.cache/xet/host_doh.json)

2. 对每个 IP 测速:
   - 直连 RTT
   - 通过代理 RTT
   └─ 选择最优路径

3. 按域名排序:
   - 优先级: (use_proxy, rtt)
   - 直连优先，其次 RTT 小
   └─ 缓存 1h (~/.cache/xet/host_optimize.json)

4. Monkey-patch socket.getaddrinfo
   └─ 返回优选 IP

5. DomainAwareSession 动态设置 proxies
   └─ 按域名决定是否走代理
```

**关键方法**:
```python
def optimize(force_refresh=False, force_doh=False):
    """执行 HOST 优选，返回映射表"""

def apply_to_session(session):
    """将优选应用到 requests.Session"""

def patch_getaddrinfo():
    """Monkey-patch socket.getaddrinfo"""
```

**缓存策略**:
- DoH 缓存: 24 小时（IP 很少变）
- 优选缓存: 1 小时（网络常变）
- `--refresh`: 强制刷新全部
- `--force-doh`: 仅刷新 DoH

**实际效果** (国内网络):
- transfer.xethub.hf.co 直连可达 → 10+ MB/s
- huggingface.co 被墙 → 自动走代理

---

### 6. XorbDeserializer (xorb_deserializer.py - 534 行)
```python
class XorbDeserializer:
    """Xorb 容器反序列化器"""
```

**支持的压缩方案**:
1. **方案 0**: 无压缩（原始数据）
2. **方案 1**: LZ4 压缩
3. **方案 2**: Zstandard 压缩

**Xorb 格式** (二进制):
```
[Header: 8 bytes]
  - Magic: "XORB" (4 bytes)
  - Version: u32 (4 bytes)

[Chunk Table]
  每个 chunk:
    - Index: u16 (2 bytes)
    - Compression: u8 (1 byte)
    - Data offset: u32 (4 bytes)
    - Compressed size: u32 (4 bytes)
    - Decompressed size: u32 (4 bytes)

[Chunk Data]
  压缩后的 chunk 数据
```

**反序列化流程**:
```python
def deserialize(xorb_bytes: bytes) -> XorbBlockData:
    # 1. 解析 header (magic + version)
    # 2. 解析 chunk table
    # 3. 按顺序解压每个 chunk
    # 4. 构建 chunk_offsets [(chunk_idx, byte_offset), ...]
    # 5. 拼接所有解压数据
    return XorbBlockData(chunk_offsets, data)
```

**返回格式**:
```python
@dataclass
class XorbBlockData:
    chunk_offsets: List[Tuple[int, int]]  # [(chunk_idx, byte_offset), ...]
    data: bytes                            # 所有 chunk 数据拼接
```

**注意事项**:
- `chunk_offsets` 的 `chunk_idx` 是**本地索引**（从 0 开始）
- 需要根据 `fetch_info.chunk_range.start` 转换为全局索引
- multipart segments 需要分别反序列化后合并

---

## 🐛 已修复的 Bug 列表

~/xet.py 文档中记录了大量修复的 bug，以下是关键问题：

### 网络相关
- **Bug E**: 网络请求卡死（无 timeout）
- **Bug Q**: direct 模式下载无 timeout
- **Bug R**: 启动阶段每次新连接（未复用 Session）
- **Bug S**: 无 HTTPAdapter/Retry
- **Bug T**: trust_env=True 意外走系统代理
- **Bug V**: IPv6 优先无 Happy Eyeballs
- **Bug W**: 无 HOST 优选

### 重建相关
- **Bug AF**: 循环依赖（RetryCoordinator）
- **Bug AG**: 早期网络请求不走代理
- **Bug U**: Session 未复用

### 并发相关
- **Windows 多线程写盘**: CreateFileW FILE_SHARE_WRITE

---

## 🎯 特色功能

### 1. 双模式重建
- **FileReconstructor**: 小文件（<256MB）
- **StreamFileReconstructor**: 大文件（>256MB）
- 自动切换或手动指定

### 2. HOST 优选（国内网络关键）
- DoH 多 DNS 并行查询
- 直连 vs 代理双向测速
- Monkey-patch getaddrinfo
- 按域名动态代理

### 3. 智能重试机制
- RetryCoordinator: 按错误类型分类重试
- URLRefreshCoordinator: Single-flight URL 刷新
- AdaptiveConcurrencyController: 动态调整并发
- 低速检测: 防止连接假死

### 4. 流式优化
- 生产者-消费者队列
- 缓冲区自动控制
- 预取优化（低/高水位线）
- Windows 多线程写盘支持

### 5. 环境变量配置
完全兼容 hf-xet/xet-core:
```bash
HF_XET_RECONSTRUCTION_DOWNLOAD_BUFFER_SIZE
HF_XET_RECONSTRUCTION_DOWNLOAD_BUFFER_PERFILE_SIZE
HF_XET_NUM_CONCURRENT_RANGE_GETS
```

---

## 📊 与 XET+ 的对比

| 方面 | ~/xet.py | XET+ |
|------|----------|------|
| **代码行数** | ~6048 行 | ~4000 行 |
| **架构** | 扁平单体 | 五层分离 |
| **测试** | 无系统化测试 | 82 个单元测试 |
| **HOST 优选** | ✅ 完整实现 | ❌ 未实现 |
| **流式重建** | ✅ 双模式 | ✅ 单模式 |
| **Multipart** | ✅ 正确处理 | ✅ 正确处理 |
| **错误处理** | ✅ 复杂完善 | ✅ 结构化清晰 |
| **性能** | ~10 MB/s | ~10 MB/s |
| **用户体验** | tqdm | Rich UI |

---

## 💡 XET+ 可以学习的地方

### 1. HOST 优选功能（可选）
国内网络环境下的关键优化：
- DoH 查询避免 DNS 污染
- 直连测速发现可达 CDN 节点
- 显著提升下载速度

**建议**: 作为可选功能实现，通过配置启用

### 2. 双模式重建（可选）
根据文件大小自动切换：
- 小文件: 全量内存（简单快速）
- 大文件: 流式处理（节省内存）

**建议**: XET+ 目前流式处理已足够，可选优化

### 3. 更细粒度的错误分类
RetryCoordinator 按错误类型精确处理：
- 5xx: 立即重试
- 401: 刷新 URL
- 429: 等待后重试
- 超时: 换 IP 重试

**建议**: XET+ 可以增强错误处理逻辑

### 4. 自适应并发控制
根据错误率动态调整并发数：
- 错误率低: 增加并发
- 错误率高: 降低并发防雪崩

**建议**: XET+ 可以考虑实现

---

## 🏆 ~/xet.py 的优势

1. **生产级稳定性**
   - 大量 bug 修复经验
   - 覆盖各种边界情况

2. **国内网络优化**
   - HOST 优选显著提升体验
   - DoH 避免 DNS 污染

3. **大文件支持**
   - 流式处理 10GB+ 文件
   - 缓冲区精确控制

4. **Windows 兼容性**
   - 多线程写盘问题修复
   - 跨平台路径处理

---

**文档版本**: 1.0
**分析日期**: 2026-06-21
**分析基于**: ~/xet.py commit c8ab802
