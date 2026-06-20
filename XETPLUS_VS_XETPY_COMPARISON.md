# XET+ vs ~/xet.py 功能对比分析

## 📊 整体对比

| 功能模块 | ~/xet.py | XET+ | 状态 |
|---------|----------|------|------|
| Protocol Layer | ✅ | ✅ | 完全对齐 |
| Network Layer | ✅ | ✅ | 完全对齐 |
| Storage Layer | ✅ | ⚠️ | 缺 xorb 解压 |
| Pipeline Layer | ✅ | ✅ | 基本对齐 |
| CLI Layer | ✅ | ✅ | 完全对齐 |

---

## 🔍 详细功能对比

### 1. Xorb 解压 (核心差异)

#### ~/xet.py 实现 ✅
**位置**: `xet/xorb_deserializer.py`

**核心函数**:
```python
class XorbDeserializer:
    @staticmethod
    def deserialize(xorb_bytes: bytes) -> XorbBlockData:
        """反序列化完整 xorb → 返回 chunk_offsets + data"""
        # 1. 循环读取所有 chunk header (8 bytes)
        # 2. 根据 compression_scheme 解压每个 chunk
        # 3. 拼接所有解压后的数据
        # 4. 返回 XorbBlockData(chunk_offsets, data)
        pass
    
    @staticmethod
    def _decompress(data: bytes, scheme: int, expected_size: int) -> bytes:
        """支持 3 种压缩方案"""
        if scheme == 0:  # COMPRESSION_NONE
            return data
        elif scheme == 1:  # COMPRESSION_LZ4
            return lz4.frame.decompress(data)
        elif scheme == 2:  # COMPRESSION_BYTE_GROUPING_4_LZ4
            lz4_data = lz4.frame.decompress(data)
            return _ungrouping_4byte(lz4_data)
```

**返回数据结构**:
```python
@dataclass
class XorbBlockData:
    chunk_offsets: List[Tuple[int, int]]  # [(chunk_idx, byte_offset), ...]
    data: bytes  # 所有解压后 chunk 的拼接数据
```

#### XET+ 当前状态 ❌
**位置**: `xet/storage/merkle_hash.py` - **未实现**

**需要的函数签名**:
```python
def decompress_xorb(xorb_bytes: bytes) -> Dict[str, bytes]:
    """解压 xorb 容器，提取内部的 chunks。
    
    Args:
        xorb_bytes: 压缩的 xorb 数据
        
    Returns:
        {chunk_hash: chunk_data} 映射
    """
    pass
```

**问题**:
- XET+ 期望返回 `{chunk_hash: chunk_data}` 字典
- ~/xet.py 返回 `XorbBlockData(chunk_offsets, data)` 整体数据
- **需要适配层转换格式**

---

### 2. Chunk 提取逻辑 (关键差异)

#### ~/xet.py 的方法
```python
# 解压后的数据是连续的 bytes，通过 chunk_offsets 索引
xorb_data = XorbDeserializer.deserialize(xorb_bytes)
# xorb_data.chunk_offsets = [(0, 0), (1, 65536), (2, 131072), ...]
# xorb_data.data = b'...' # 所有 chunk 拼接

# 提取特定 chunk
chunk_idx = 5
start_offset = xorb_data.chunk_offsets[chunk_idx][1]
if chunk_idx + 1 < len(xorb_data.chunk_offsets):
    end_offset = xorb_data.chunk_offsets[chunk_idx + 1][1]
else:
    end_offset = len(xorb_data.data)

chunk_data = xorb_data.data[start_offset:end_offset]
```

#### XET+ 期望的方法
```python
# 期望直接得到 chunk_hash → chunk_data 映射
chunks = decompress_xorb(xorb_bytes)
# chunks = {
#     "abc123...": b'chunk_0_data',
#     "def456...": b'chunk_1_data',
#     ...
# }

# 使用 chunk_hash 直接索引
chunk_data = chunks[term.chunk_hash]
```

**问题**:
- XET+ 的 `ChunkAssembler` 需要通过 `chunk_hash` 索引
- 但 ~/xet.py 返回的是 `chunk_offsets` (索引是数字)
- **需要计算每个 chunk 的 hash**

---

### 3. Chunk Hash 计算

#### ~/xet.py 实现 ✅
**位置**: `xet/merklehash.py`

```python
def compute_data_hash(data: bytes) -> str:
    """用 DATA_KEY 计算 chunk 的 keyed blake3 哈希。"""
    digest = blake3(data, key=DATA_KEY).digest()
    return _datahash_hex(digest)  # 返回 64 hex 字符
```

#### XET+ 当前状态 ❌
**位置**: `xet/storage/merkle_hash.py` - **未实现**

---

### 4. 完整的集成方案

#### 方案 A: 直接移植 ~/xet.py 代码 ✅ (推荐)

**实现步骤**:

1. **复制核心文件**:
   ```bash
   cp ~/xet.py/xet/xorb_deserializer.py ~/xetplus/xet/storage/
   cp ~/xet.py/xet/merklehash.py ~/xetplus/xet/storage/merkle_hash.py
   ```

2. **创建适配层** (`xet/storage/xorb_adapter.py`):
   ```python
   from typing import Dict
   from .xorb_deserializer import XorbDeserializer
   from .merkle_hash import compute_data_hash
   
   def decompress_xorb(xorb_bytes: bytes) -> Dict[str, bytes]:
       """XET+ 兼容接口：解压 xorb 并返回 chunk_hash → chunk_data 映射。"""
       # 1. 使用 ~/xet.py 的反序列化
       xorb_data = XorbDeserializer.deserialize(xorb_bytes)
       
       # 2. 提取每个 chunk 并计算 hash
       chunks = {}
       for i, (chunk_idx, byte_offset) in enumerate(xorb_data.chunk_offsets):
           # 确定 chunk 结束位置
           if i + 1 < len(xorb_data.chunk_offsets):
               next_offset = xorb_data.chunk_offsets[i + 1][1]
           else:
               next_offset = len(xorb_data.data)
           
           # 提取 chunk 数据
           chunk_data = xorb_data.data[byte_offset:next_offset]
           
           # 计算 chunk hash
           chunk_hash = compute_data_hash(chunk_data)
           
           chunks[chunk_hash] = chunk_data
       
       return chunks
   ```

3. **更新 ChunkAssembler**:
   ```python
   # xet/pipeline/chunk_assembler.py
   def _decompress_all_xorbs(self, xorb_data_map):
       from xet.storage.xorb_adapter import decompress_xorb
       
       chunk_cache = {}
       for xorb_hash, xorb_bytes in xorb_data_map.items():
           chunks = decompress_xorb(xorb_bytes)
           chunk_cache.update(chunks)
       
       return chunk_cache
   ```

**优点**:
- ✅ 代码已验证可用
- ✅ 性能最优 (LZ4 原生库)
- ✅ 实现简单 (只需复制文件)
- ✅ 完全兼容 XET 规范

**缺点**:
- ⚠️ 需要依赖 blake3 库
- ⚠️ 代码冗余 (两个 types.py)

---

#### 方案 B: 纯 Python 简化实现 (备选)

```python
import lz4.frame
import struct

def decompress_xorb_simple(xorb_bytes: bytes) -> Dict[str, bytes]:
    """简化版 xorb 解压 (不计算 hash)。"""
    chunks = {}
    offset = 0
    chunk_idx = 0
    
    while offset < len(xorb_bytes):
        # 读取 8 字节 header
        if offset + 8 > len(xorb_bytes):
            break
        
        header = xorb_bytes[offset:offset + 8]
        version = header[0]
        compressed_len = int.from_bytes(header[1:4], 'little')
        comp_scheme = header[4]
        decompressed_len = int.from_bytes(header[5:8], 'little')
        
        # 提取压缩数据
        data_start = offset + 8
        data_end = data_start + compressed_len
        comp_data = xorb_bytes[data_start:data_end]
        
        # 解压
        if comp_scheme == 0:  # NONE
            raw_data = comp_data
        elif comp_scheme == 1:  # LZ4
            raw_data = lz4.frame.decompress(comp_data)
        else:
            raise ValueError(f"不支持的压缩方案: {comp_scheme}")
        
        # 使用 chunk_idx 作为 key (临时方案)
        chunks[f"chunk_{chunk_idx}"] = raw_data
        
        offset = data_end
        chunk_idx += 1
    
    return chunks
```

**优点**:
- ✅ 实现简单
- ✅ 无需 blake3 库

**缺点**:
- ❌ 不计算真实 chunk_hash
- ❌ 与 XET 规范不完全一致
- ❌ 无法验证数据完整性

---

### 5. 其他功能对比

#### IP 优选 (~/xet.py 特有)

**~/xet.py 实现**:
```python
# http_utils.py
def select_fastest_ip(domain: str, timeout: float = 2.0) -> Optional[str]:
    """DNS 解析 + ping 测试，选择最快 IP"""
    pass
```

**XET+ 状态**: ❌ 未实现

**需要性**: ⚠️ 可选 (对国内用户有用，但非必需)

---

#### SHA256 校验 (两者都有)

**~/xet.py**: ✅ 在 reconstructor.py 中实现
**XET+**: ✅ 在 FileReconstructor 中实现

---

#### 断点续传 (两者都有)

**~/xet.py**: ✅ 使用 JSON checkpoint
**XET+**: ✅ 使用 CheckpointManager

---

#### Progress Bar (两者都有)

**~/xet.py**: ✅ 使用 tqdm
**XET+**: ✅ 使用 rich (更美观)

---

## 📝 待完成工作清单

### P0 - 阻塞下载完成

- [ ] **实现 xorb 解压适配层**
  - [ ] 复制 `xorb_deserializer.py`
  - [ ] 复制 `merklehash.py` → `merkle_hash.py`
  - [ ] 创建 `xorb_adapter.py` 适配层
  - [ ] 更新 `ChunkAssembler._decompress_all_xorbs()`
  - [ ] 添加依赖: `blake3>=0.3.0`

### P1 - 功能完善

- [ ] **repo/file 格式支持**
  - [ ] 实现从 HF HEAD 请求获取 xet_hash
  - [ ] 更新 download/info 命令参数解析

- [ ] **端到端测试**
  - [ ] 完整下载测试 (100MB 文件)
  - [ ] SHA256 校验
  - [ ] 断点续传测试

### P2 - 优化增强

- [ ] **IP 优选功能** (可选)
  - [ ] 移植 `select_fastest_ip()` 函数
  - [ ] 集成到 CASClient

- [ ] **错误处理改进**
  - [ ] 更友好的错误消息
  - [ ] 自动重试优化

### P3 - 文档和测试

- [ ] **补充测试**
  - [ ] xorb 解压单元测试
  - [ ] CLI 集成测试

- [ ] **文档完善**
  - [ ] 使用指南
  - [ ] API 文档

---

## 🎯 推荐实施方案

**第一步**: 使用方案 A 实现 xorb 解压
- 工作量: 2-3 小时
- 风险: 低 (代码已验证)
- 收益: 立即完成下载功能

**第二步**: 进行端到端测试
- 工作量: 1 小时
- 验证: 完整下载流程

**第三步**: 补充 repo/file 支持
- 工作量: 1-2 小时
- 收益: 用户体验提升

**总时间估算**: 4-6 小时完成所有 P0 和 P1 工作

---

## ✨ 总结

### 当前状态
- **完成度**: 95%
- **阻塞点**: xorb 解压函数
- **差距**: 只差一个适配层

### 关键发现
1. **~/xet.py 的 xorb 解压已完全实现**
   - 支持 3 种压缩方案
   - 包含完整的 chunk 提取逻辑
   - 代码质量高，可直接复用

2. **XET+ 架构更清晰**
   - 五层架构分离良好
   - 测试覆盖更完善
   - CLI 体验更好 (rich 进度条)

3. **只需要一个适配层**
   - `XorbBlockData` → `Dict[chunk_hash, chunk_data]`
   - 集成 `compute_data_hash()` 计算 hash
   - 10-20 行代码即可完成

### 下一步
**立即行动**: 实现 xorb 解压适配层，完成第一个完整的文件下载！

---

**报告日期**: 2026-06-20
**对比版本**: XET+ 0.1.0 vs ~/xet.py latest
