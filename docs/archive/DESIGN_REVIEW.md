# XET Plus 设计评审文档

> **目标读者**: 项目审查者、架构师、技术负责人

---

## 📋 执行摘要

### 问题陈述

旧版 `xet.py` 存在以下核心问题：

1. **架构混乱**: 单文件 2,363 行（reconstructor.py），God Class 职责不清
2. **无测试覆盖**: 0 个单元测试，调试靠分析 19,000+ 行生产日志
3. **维护困难**: "头疼医头" - 修一个 bug 影响全局，引入新 bug
4. **技术债务**: xorb 校验缺失、403 风暴、文件锁冲突等 20+ 已知问题

### 解决方案

重构为清晰的 4 层架构，每层职责单一、可独立测试：

```
CLI → Pipeline → (Network, Storage, Protocol)
```

### 预期收益

| 指标 | 当前 | 目标 | 改善 |
|------|------|------|------|
| 最大文件行数 | 2,363 | <500 | -80% |
| 测试覆盖率 | 0% | 80%+ | ∞ |
| Bug 修复时间 | 数小时（看日志） | 数分钟（单元测试） | 10x |
| 新功能开发 | 高风险（全局影响） | 低风险（模块隔离） | 安全 |

---

## 🏗️ 架构设计

### 整体架构图

```
                    ┌─────────────────┐
                    │   CLI Layer     │
                    │   (cli.py)      │
                    │  - 参数解析      │
                    │  - 进度条        │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Pipeline Layer  │
                    │ (pipeline/)     │
                    │  - Scheduler    │◄──────┐
                    │  - Downloader   │       │
                    │  - Assembler    │       │
                    │  - Concurrency  │       │
                    └────────┬────────┘       │
                             │                │
              ┌──────────────┼──────────┐     │
              │              │          │     │
     ┌────────▼────┐  ┌──────▼─────┐ ┌─▼─────▼──┐
     │  Network    │  │  Storage   │ │ Protocol │
     │  Layer      │  │  Layer     │ │  Layer   │
     │  (network/) │  │ (storage/) │ │(protocol)│
     │             │  │            │ │          │
     │ - CASClient │  │ - Writer   │ │ - Types  │
     │ - Retry     │  │ - Checkpt  │ │ - Xorb   │
     │ - Auth      │  │ - Cache    │ │  Format  │
     └─────────────┘  └────────────┘ └──────────┘
```

### 层次职责

#### 1. Protocol Layer（协议层）

**职责**: 纯协议解析，无任何 I/O

```python
# 纯函数：输入 bytes，输出解析结果
def deserialize_xorb_stream(data: bytes) -> Tuple[bytes, List[Tuple[int, int]]]:
    """解析 xorb 数据流。
    
    特点:
    - 无副作用（不读写文件、不修改全局状态）
    - 可预测（相同输入总是相同输出）
    - 易测试（单元测试覆盖 100%）
    """
    pass
```

**关键设计**:
- 所有函数纯函数化
- 类型注解完整
- 错误处理统一（抛出 ValueError）

**文件清单**:
- `types.py` - 数据结构（HttpRange, ChunkRange, etc.）
- `xorb_format.py` - Xorb 二进制解析
- `reconstruction.py` - Reconstruction 逻辑

#### 2. Network Layer（网络层）

**职责**: HTTP 通信抽象

```python
class CASAPIClient:
    """纯 API 调用，无业务逻辑。"""
    
    @with_retry(max_attempts=3)  # 装饰器处理重试
    def get_reconstruction(self, file_hash: str) -> Response:
        # 只负责 HTTP 调用
        return self.session.get(url)
```

**关键设计**:
- API 调用与重试解耦（装饰器模式）
- Session 工厂统一配置
- 错误分类（Transient vs Fatal）

**文件清单**:
- `session.py` - Session 工厂
- `cas_api.py` - CAS API 纯调用
- `retry.py` - 重试装饰器
- `auth.py` - Token 管理

#### 3. Storage Layer（存储层）

**职责**: 文件 I/O 抽象

```python
class FileWriter(ABC):
    """统一写入接口（策略模式）。"""
    
    @abstractmethod
    def write_at(self, offset: int, data: bytes) -> None:
        pass

# 使用
writer = create_writer(path, mode='sequential')  # 或 'parallel'
writer.write_at(0, data)
```

**关键设计**:
- 策略模式（顺序/并行模式统一接口）
- 解决 Windows 文件锁问题（全局单 Writer 线程）
- Checkpoint 管理独立

**文件清单**:
- `writer.py` - 统一 Writer 接口
- `checkpoint.py` - 断点管理
- `cache.py` - 磁盘缓存

#### 4. Pipeline Layer（管道层）

**职责**: 编排下载流程

```python
class DownloadScheduler:
    """状态机协调整个下载流程。"""
    
    def __init__(self, api: CASAPIClient, writer: FileWriter, ...):
        # 依赖注入，易于测试
        self.api = api
        self.writer = writer
        self.state = State.INIT
    
    async def run(self) -> None:
        """运行状态机。"""
        while self.state != State.DONE:
            handler = self._handlers[self.state]
            self.state = await handler()
```

**关键设计**:
- 状态机清晰（Init → Auth → Recon → Download → Assemble → Verify → Done）
- 依赖注入（易于 mock 测试）
- 并发控制独立（ACC）

**文件清单**:
- `scheduler.py` - 状态机
- `downloader.py` - 并发下载
- `assembler.py` - 数据组装
- `concurrency.py` - 自适应并发控制

---

## 🎯 关键设计模式

### 1. 依赖注入（Dependency Injection）

**问题**: 旧版硬编码依赖，难以测试

```python
# 旧版：硬编码
class Reconstructor:
    def __init__(self):
        self.api = CASClient()  # 硬编码，无法 mock

# 新版：依赖注入
class DownloadScheduler:
    def __init__(self, api: CASAPIClient, writer: FileWriter):
        self.api = api      # 注入，易于 mock
        self.writer = writer
```

**收益**:
- 单元测试可以 mock 依赖
- 不同实现可以互换（如测试用的 MockWriter）

### 2. 策略模式（Strategy Pattern）

**问题**: 旧版顺序/并行模式代码交织

```python
# 旧版：if/else 判断
if mode == 'parallel':
    # 并行写入逻辑 (100 行)
else:
    # 顺序写入逻辑 (50 行)

# 新版：统一接口
writer = create_writer(path, mode)  # 工厂模式
writer.write_at(0, data)            # 统一接口
```

**收益**:
- 新增模式无需改旧代码
- 切换模式不影响业务逻辑

### 3. 装饰器模式（Decorator Pattern）

**问题**: 旧版重试逻辑散布各处

```python
# 旧版：重试逻辑混在业务中
def fetch(url):
    for attempt in range(5):
        try:
            return requests.get(url)
        except:
            time.sleep(2 ** attempt)

# 新版：装饰器统一
@with_retry(max_attempts=5, backoff_base=2)
def fetch(url):
    return requests.get(url)  # 业务逻辑清晰
```

**收益**:
- 重试逻辑统一
- 业务代码清晰
- 可配置性强

### 4. 状态机模式（State Machine）

**问题**: 旧版流程隐含在嵌套逻辑中

```python
# 新版：显式状态机
class State(Enum):
    INIT = auto()
    AUTH = auto()
    RECON = auto()
    DOWNLOAD = auto()
    ASSEMBLE = auto()
    VERIFY = auto()
    DONE = auto()

# 状态转换清晰
self.state = await handler()  # 每个状态返回下一个状态
```

**收益**:
- 流程清晰可见
- 状态转换可测试
- 易于添加新状态

---

## 🔬 测试策略

### 测试金字塔

```
       ┌──────────┐
       │ E2E Tests│  (少量，覆盖关键流程)
       └──────────┘
      ┌────────────┐
      │Integration │  (中等，测试模块协作)
      │   Tests    │
      └────────────┘
    ┌──────────────────┐
    │   Unit Tests     │  (大量，覆盖所有函数)
    └──────────────────┘
```

### 单元测试（目标 80%+ 覆盖）

```python
# protocol/xorb_format.py 纯函数测试
def test_deserialize_single_chunk():
    sample = load_fixture('single_chunk.xorb')
    data, offsets = deserialize_xorb_stream(sample)
    assert len(data) == 65536

def test_deserialize_corrupted():
    corrupted = load_fixture('corrupted.xorb')
    with pytest.raises(ValueError, match="corrupted"):
        deserialize_xorb_stream(corrupted)
```

### 集成测试（Mock 外部依赖）

```python
def test_download_small_file(tmp_path):
    # Mock API
    mock_api = Mock()
    mock_api.get_reconstruction.return_value = sample_recon()
    
    # 真实 Scheduler
    scheduler = DownloadScheduler(
        api=mock_api,
        writer=create_writer(tmp_path / "out", mode='sequential')
    )
    
    scheduler.run()
    
    # 验证结果
    assert (tmp_path / "out").read_bytes() == expected
```

### E2E 测试（关键路径）

```python
def test_full_download_workflow():
    """端到端测试：真实 API + 真实文件系统。"""
    result = subprocess.run([
        'xetplus', 'download',
        '--url', test_file_url,
        '--output', tmp_path / 'file.bin'
    ])
    assert result.returncode == 0
    assert verify_sha256(tmp_path / 'file.bin') == expected_sha
```

---

## 📊 性能考虑

### 内存优化

| 场景 | 旧版 | 新版 | 改进 |
|------|------|------|------|
| Xorb 缓存 | OrderedDict 全部缓存 | LRU + 引用计数 | 节省数 GB |
| 解压缓冲 | 每次分配 16MB | 缓冲池复用 | 减少 GC |
| 数据流转 | 多次拷贝 | 零拷贝（memoryview） | 提升吞吐 |

### 并发优化

| 维度 | 旧版 | 新版 |
|------|------|------|
| 并发数 | 固定（10） | 自适应 ACC (1-64) |
| 失败处理 | 全局重试 | 单个 xorb 重试 |
| 403 处理 | 各自刷新 | 协调器去重 |

### I/O 优化

| 优化 | 实现 | 收益 |
|------|------|------|
| 文件预分配 | `fallocate()` (Linux) | 减少碎片 |
| 异步刷盘 | `aio_write()` | 提升吞吐 |
| 零拷贝写入 | `sendfile()` (Linux) | 减少 CPU |

---

## ⚠️ 风险评估

### 技术风险

| 风险 | 可能性 | 影响 | 缓解措施 | 状态 |
|------|--------|------|---------|------|
| 协议理解偏差 | 中 | 高 | 对比 Rust 代码，调试验证 | ✅ 已缓解 |
| 性能低于旧版 | 低 | 中 | Profile 对比，Rust 扩展 | 📋 监控中 |
| Windows 兼容问题 | 中 | 中 | 专门测试，FILE_SHARE_WRITE | 📋 待测试 |
| 测试数据不足 | 低 | 低 | 从生产提取真实 xorb | ✅ 已准备 |

### 项目风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 开发周期超期 | 中 | 中 | 渐进式交付，每阶段可用 |
| 资源不足 | 低 | 高 | 优先级排序，核心功能优先 |
| 需求变更 | 低 | 中 | 模块化设计，易于调整 |

---

## 📅 交付计划

### 阶段交付

| Phase | 时间 | 可交付成果 | 验收标准 |
|-------|------|-----------|---------|
| Phase 1 | Week 2 | 协议层纯函数 | 测试覆盖 100% |
| Phase 2 | Week 4 | 存储层 Writer | Windows 兼容 |
| Phase 3 | Week 6 | 网络层 API | Mock 测试通过 |
| Phase 4 | Week 9 | 管道层完整 | 可下载小文件 |
| Phase 5 | Week 10 | CLI 可用 | 功能对齐旧版 |
| Phase 6 | Week 12 | v1.0.0 发布 | 性能 ≥ 旧版 |

### 里程碑

- **M1 (Week 2)**: 协议层完成，证明架构可行
- **M4 (Week 9)**: 核心功能完成，可内部测试
- **M6 (Week 12)**: 生产就绪，可替换旧版

---

## ✅ 推荐决策

### 批准理由

1. **架构清晰**: 4 层设计职责明确，易于理解和维护
2. **测试完善**: 80%+ 覆盖率，质量有保证
3. **风险可控**: 渐进式交付，每阶段独立验证
4. **收益明显**: 代码量 -80%，维护性大幅提升

### 后续行动

1. **立即开始**: Phase 1 协议层提取（Week 1-2）
2. **每周回顾**: 检查进度，调整计划
3. **里程碑验收**: M1/M4/M6 各阶段审查

---

## 📞 联系方式

- **技术负责人**: [待定]
- **项目 Repo**: `~/xetplus/`
- **文档索引**: `README_CN.md`

---

**审批签名**:

- [ ] 技术负责人: ________________  日期: ________
- [ ] 架构师: ________________  日期: ________
- [ ] 项目经理: ________________  日期: ________

---

**附录**:
- [A] 详细架构图 → `ARCHITECTURE.md`
- [B] 开发路线图 → `ROADMAP.md`
- [C] Phase 1 计划 → `docs/phase1-plan.md`
