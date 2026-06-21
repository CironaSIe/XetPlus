# XET Plus 架构设计

## 设计原则

1. **单一职责** - 每个模块只做一件事
2. **依赖倒置** - 核心逻辑不依赖具体实现
3. **开闭原则** - 对扩展开放，对修改封闭
4. **可测试性** - 每层都能独立 mock 测试

---

## 层次架构

```
┌─────────────────────────────────────────────┐
│            CLI Layer (cli.py)               │
│  - 命令行参数解析                            │
│  - 进度条显示                                │
│  - 配置加载                                  │
└─────────────────┬───────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│         Pipeline Layer (pipeline/)          │
│  - DownloadScheduler (状态机)               │
│  - XorbDownloader (并发下载)                │
│  - FileAssembler (数据组装)                 │
│  - ConcurrencyController (ACC)              │
└─────────────────┬───────────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌────────┐   ┌─────────┐   ┌────────┐
│Network │   │Storage  │   │Protocol│
│Layer   │   │Layer    │   │Layer   │
└────────┘   └─────────┘   └────────┘
```

---

## 模块职责

### 1. Protocol Layer (protocol/)

**职责**: 协议解析和数据结构（纯逻辑，无 I/O）

#### types.py
- 数据类定义（HttpRange, ChunkRange, etc.）
- JSON 序列化/反序列化
- V1/V2 格式自动转换

#### xorb_format.py
- Xorb 二进制格式解析
- 压缩/解压算法（LZ4, BG4）
- **纯函数设计** - 输入 bytes，输出 (data, offsets)

#### reconstruction.py
- Reconstruction 响应处理逻辑
- Terms 覆盖度验证
- Chunk 范围计算

**关键设计**:
```python
# 纯函数，易于测试
def deserialize_xorb_stream(data: bytes, base_chunk_index: int = 0) 
    -> Tuple[bytes, List[Tuple[int, int]]]:
    """解析 xorb 数据流。
    
    Args:
        data: 原始二进制数据
        base_chunk_index: 起始 chunk 索引（multipart 合并时用）
    
    Returns:
        (merged_data, chunk_offsets)
    """
    # 无副作用，可以单元测试
```

---

### 2. Network Layer (network/)

**职责**: HTTP 通信和认证（封装网络细节）

#### session.py
- Session 工厂函数
- 连接池配置
- 代理设置

#### retry.py
- 重试装饰器 `@with_retry`
- 可配置的退避策略
- 错误分类（transient vs fatal）

#### cas_api.py
- CAS API 纯调用（无业务逻辑）
- 方法：
  - `get_reconstruction()` - 获取重建信息
  - `fetch_xorb_part()` - 下载单个 part
  - `fetch_xorb()` - 协调 multipart

#### auth.py
- Token 管理
- 自动刷新（提前 30s）
- Thread-safe

**关键设计**:
```python
class CASAPIClient:
    """纯 API 调用，职责单一。"""
    
    def __init__(self, endpoint: str, token: str, session: Session):
        self.endpoint = endpoint
        self.token = token
        self.session = session
    
    @with_retry(max_attempts=3)
    def get_reconstruction(self, file_hash: str) -> QueryReconstructionResponse:
        """获取 reconstruction（装饰器处理重试）。"""
        # 只负责 HTTP 调用和响应解析
        resp = self.session.get(f"{self.endpoint}/v2/reconstructions/{file_hash}")
        return QueryReconstructionResponse.from_dict(resp.json())
```

---

### 3. Storage Layer (storage/)

**职责**: 文件 I/O 和持久化（抽象存储细节）

#### writer.py
- 统一写入接口（抽象基类）
- `SequentialWriter` - 顺序模式（HDD 友好）
- `ParallelWriter` - 并行模式（SSD 优化）
- 工厂函数 `create_writer()`

#### checkpoint.py
- Checkpoint 数据结构
- 保存/加载/验证
- 支持分段模式

#### cache.py
- 磁盘缓存管理
- LRU 淘汰策略

**关键设计**:
```python
class FileWriter(ABC):
    """统一写入接口（策略模式）。"""
    
    @abstractmethod
    def write_at(self, offset: int, data: bytes) -> None:
        """在指定偏移写入数据（原子操作）。"""
        pass
    
    @abstractmethod
    def get_bytes_written(self) -> int:
        """获取已写入字节数（用于进度报告）。"""
        pass

# 使用
writer = create_writer(path, mode='sequential')  # 或 'parallel'
writer.write_at(0, data)
writer.close()
```

---

### 4. Pipeline Layer (pipeline/)

**职责**: 协调下载流程（编排各层）

#### scheduler.py
- `DownloadScheduler` - 顶层状态机
- 状态：Init → Auth → Recon → Download → Assemble → Verify → Done
- 进度报告接口

#### downloader.py
- `XorbDownloader` - 并发下载管理
- Single-flight 去重
- 与 `ConcurrencyController` 集成

#### assembler.py
- `FileAssembler` - 按 terms 顺序组装
- 从 xorb cache 提取数据
- 处理 `offset_into_first_range`

#### concurrency.py
- `ConcurrencyController` - 自适应并发控制
- AIMD 算法（成功+1，失败×0.5）
- 动态调整并发度

**关键设计**:
```python
class DownloadScheduler:
    """顶层状态机（协调各层）。"""
    
    def __init__(self, api: CASAPIClient, writer: FileWriter, ...):
        self.api = api          # 依赖注入
        self.writer = writer
        self.downloader = XorbDownloader(api, ...)
        self.assembler = FileAssembler(writer)
        self.state = State.INIT
    
    async def run(self) -> None:
        """运行状态机。"""
        while self.state != State.DONE:
            handler = self._handlers[self.state]
            self.state = await handler()  # 每个状态返回下一个状态
```

---

## 数据流

### 完整下载流程

```
1. CLI 解析参数
   ↓
2. Scheduler.run()
   ├─ State.AUTH: 获取 CAS token
   ├─ State.RECON: 获取 reconstruction
   ├─ State.DOWNLOAD: 并发下载所有 xorbs
   │   ├─ ConcurrencyController 控制并发度
   │   ├─ XorbDownloader 协调下载
   │   └─ protocol/xorb_format 解析二进制
   ├─ State.ASSEMBLE: 按 terms 顺序组装
   │   └─ FileWriter 写入数据
   ├─ State.VERIFY: SHA256 校验
   └─ State.DONE: 完成
```

### 断点续传流程

```
1. Checkpoint.load() 读取断点
   ↓
2. 恢复状态（已下载的 xorbs 跳过）
   ↓
3. Writer 从断点位置继续写入
   ↓
4. 每 N terms 保存 checkpoint
```

---

## 错误处理

### 错误分类

```python
class TransientError(Exception):
    """可重试的错误（网络超时、5xx）。"""
    pass

class FatalError(Exception):
    """不可重试的错误（404、401、数据损坏）。"""
    pass

class CheckpointError(Exception):
    """断点相关错误。"""
    pass
```

### 错误传播

```
Protocol Layer → 抛出 ValueError (数据格式错误)
    ↓
Network Layer → 捕获，转换为 TransientError/FatalError
    ↓
Pipeline Layer → 根据错误类型决定重试或失败
    ↓
CLI Layer → 显示用户友好的错误信息
```

---

## 测试策略

### 单元测试

每个纯函数都要测试：

```python
# protocol/xorb_format.py
def test_deserialize_single_chunk():
    sample = load_fixture('single_chunk.xorb')
    data, offsets = deserialize_xorb_stream(sample)
    assert len(data) == 65536
    assert offsets == [(0, 0), (0, 65536)]

def test_deserialize_corrupted():
    corrupted = load_fixture('corrupted.xorb')
    with pytest.raises(ValueError, match="chunk corrupted"):
        deserialize_xorb_stream(corrupted)
```

### 集成测试

Mock 网络层，测试完整流程：

```python
def test_download_small_file(tmp_path):
    # Mock CAS API
    mock_api = Mock()
    mock_api.get_reconstruction.return_value = sample_reconstruction()
    mock_api.fetch_xorb.return_value = sample_xorb_data()
    
    # 真实的 Scheduler
    scheduler = DownloadScheduler(
        api=mock_api,
        writer=create_writer(tmp_path / "output", mode='sequential'),
        ...
    )
    
    scheduler.run()
    
    # 验证
    assert (tmp_path / "output").read_bytes() == expected_data
```

---

## 性能考虑

### 内存使用

- **旧版问题**: `OrderedDict` 缓存所有 xorb，大文件占用数 GB
- **新版方案**: 
  - 引用计数，不再使用的 xorb 立即释放
  - 可配置的 LRU 缓存
  - 流式处理，不保留完整数据

### 并发控制

- **旧版问题**: 固定并发数，无法适应网络波动
- **新版方案**:
  - ACC 自适应调整（AIMD）
  - 成功时缓慢增加，失败时快速降低
  - 避免 403 风暴

### I/O 优化

- **旧版问题**: 并行模式每个段独立打开文件（Windows 锁冲突）
- **新版方案**:
  - 全局单 Writer 线程
  - Windows 使用 FILE_SHARE_WRITE
  - SSD 预分配文件（避免碎片）

---

## 与旧版对比

| 维度 | xet.py (旧版) | xetplus (新版) |
|------|--------------|----------------|
| **架构** | 单体，职责混乱 | 分层，职责清晰 |
| **reconstructor.py** | 2,363 行 | 拆分为 4 个模块，各 <500 行 |
| **CASClient** | 955 行（API+重试+ACC+...） | 拆分为 3 个模块 |
| **测试** | 0 个单元测试 | 目标 80%+ 覆盖率 |
| **调试** | 看 19k 行日志 | 单元测试快速定位 |
| **扩展** | 改一处影响全局 | 模块隔离，影响范围小 |

---

## 下一步

1. **阅读本文档** - 理解架构设计
2. **开始 Phase 1** - 提取协议层纯函数
3. **编写第一个测试** - `test_deserialize_single_chunk()`
