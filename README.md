# XET Plus - 重构版 XET 下载器

> **设计原则**: 模块化、可测试、易维护

## 项目目标

基于 `xet.py` 的经验教训，重新设计一个清晰、健壮的 XET 协议下载器：

1. **职责分离** - 每个模块只做一件事
2. **测试优先** - 每层都可独立测试
3. **渐进迁移** - 保持与旧版兼容
4. **生产就绪** - 完善的错误处理和日志

## 架构设计

```
xetplus/
├── xet/                      # 核心库
│   ├── protocol/             # 协议层（纯逻辑，无 I/O）
│   │   ├── types.py          # 数据结构
│   │   ├── xorb_format.py    # Xorb 二进制解析
│   │   └── reconstruction.py # Reconstruction 逻辑
│   │
│   ├── network/              # 网络层（HTTP 抽象）
│   │   ├── session.py        # Session 工厂
│   │   ├── cas_api.py        # CAS API 调用
│   │   ├── retry.py          # 重试策略
│   │   └── auth.py           # Token 管理
│   │
│   ├── storage/              # 存储层（文件 I/O）
│   │   ├── writer.py         # 统一写入接口
│   │   ├── checkpoint.py     # 断点管理
│   │   └── cache.py          # 磁盘缓存
│   │
│   ├── pipeline/             # 管道层（协调下载）
│   │   ├── scheduler.py      # 下载调度
│   │   ├── downloader.py     # 并发下载
│   │   ├── assembler.py      # 数据组装
│   │   └── concurrency.py    # 并发控制
│   │
│   └── __init__.py           # 对外 API
│
├── tests/                    # 测试套件
│   ├── unit/                 # 单元测试
│   ├── integration/          # 集成测试
│   └── fixtures/             # 测试数据
│
├── docs/                     # 文档
│   ├── architecture.md       # 架构设计
│   ├── api.md                # API 参考
│   └── migration.md          # 迁移指南
│
├── cli.py                    # CLI 入口
└── setup.py                  # 打包配置
```

## 与旧版对比

| 维度 | xet.py (旧版) | xetplus (新版) |
|------|--------------|----------------|
| **单文件行数** | 2,363 (reconstructor) | <500 per file |
| **测试覆盖** | 0% (无测试) | 目标 80%+ |
| **模块耦合** | 高（God Class） | 低（单一职责） |
| **Bug 修复** | 头疼医头 | 隔离影响 |
| **调试难度** | 看 19k 行日志 | 单元测试快速定位 |

## 核心改进

### 1. 协议层纯函数化

```python
# 旧版：解析 + I/O + 状态管理混在一起
class XorbDeserializer:
    def deserialize(self, data):
        # 200+ 行混杂逻辑

# 新版：纯函数，易测试
def deserialize_xorb_stream(data: bytes) -> Tuple[bytes, List[Tuple[int, int]]]:
    """解析 xorb（纯函数，无副作用）"""
    # 清晰的输入输出，可独立测试
```

### 2. Writer 接口统一

```python
# 旧版：顺序/并行模式代码交织，GlobalWriter 在 xet_dl.py
# 新版：统一接口，策略模式
class FileWriter(ABC):
    def write_at(self, offset: int, data: bytes) -> None: ...
    def flush(self) -> None: ...

# 使用
writer = create_writer(path, mode='sequential')  # 或 'parallel'
writer.write_at(0, data)
writer.close()
```

### 3. 网络层职责单一

```python
# 旧版：CASClient 包含 API调用+重试+ACC+URL刷新+日志...
# 新版：各司其职
api = CASAPIClient(endpoint, token)        # 纯 API 调用
api = with_retry(api, max_attempts=5)      # 装饰器加重试
downloader = XorbDownloader(api, cc)       # 并发控制
```

## 开发计划

见 `ROADMAP.md`

## 设计决策记录

见 `docs/decisions/` 目录

## 问题跟踪

见 `ISSUES.md`
