# XET Plus 开发路线图

## 总体策略

**渐进式重构** - 每个阶段都能独立运行和测试，不破坏现有功能。

---

## Phase 1: 基础设施（Week 1-2）

### 目标
建立项目骨架、测试框架、CI/CD

### 任务清单

- [ ] **项目初始化** (1 天)
  - [x] 创建目录结构
  - [ ] 配置 setup.py / pyproject.toml
  - [ ] 添加 .gitignore
  - [ ] 初始化 git 仓库

- [ ] **测试框架** (1 天)
  - [ ] 安装 pytest, pytest-cov, pytest-asyncio
  - [ ] 创建 tests/ 目录结构
  - [ ] 编写第一个示例测试
  - [ ] 配置 pytest.ini

- [ ] **协议层 - 纯函数提取** (3 天)
  - [ ] `protocol/types.py` - 从旧版复制数据结构
  - [ ] `protocol/xorb_format.py` - 提取 xorb 解析纯函数
    - [ ] `parse_xorb_header()`
    - [ ] `decompress_chunk()`
    - [ ] `deserialize_xorb_stream()`
  - [ ] 编写单元测试 (目标 100% 覆盖)
    - [ ] `test_parse_header_valid()`
    - [ ] `test_parse_header_truncated()`
    - [ ] `test_decompress_lz4()`
    - [ ] `test_deserialize_single_chunk()`
    - [ ] `test_deserialize_multipart()`

- [ ] **文档** (1 天)
  - [ ] `docs/architecture.md` - 架构图和设计说明
  - [ ] `docs/testing.md` - 测试指南
  - [ ] API 注释规范（所有函数必须有 docstring）

**验收标准**:
- ✅ 所有单元测试通过
- ✅ 测试覆盖率 ≥ 95%
- ✅ 文档完整（每个模块有 README）

---

## Phase 2: 存储层（Week 3-4）

### 目标
实现统一的文件写入接口，解决 Windows 文件锁问题

### 任务清单

- [ ] **Writer 接口设计** (2 天)
  - [ ] `storage/writer.py` - 抽象基类
    ```python
    class FileWriter(ABC):
        def write_at(self, offset: int, data: bytes) -> None
        def flush(self) -> None
        def close(self) -> None
        def get_bytes_written(self) -> int
    ```
  - [ ] `SequentialWriter` - 顺序写入实现
  - [ ] `ParallelWriter` - 并行写入实现（队列 + 线程）
  - [ ] `create_writer()` - 工厂函数

- [ ] **平台兼容** (1 天)
  - [ ] `storage/platform.py` - 平台相关函数
    - [ ] `open_file_shared_write()` - Windows FILE_SHARE_WRITE
    - [ ] `preallocate_file()` - 跨平台预分配

- [ ] **Checkpoint 管理** (2 天)
  - [ ] `storage/checkpoint.py`
    - [ ] `Checkpoint` 数据类
    - [ ] `save_checkpoint()`
    - [ ] `load_checkpoint()`
    - [ ] `validate_checkpoint()` - 完整性校验

- [ ] **单元测试** (2 天)
  - [ ] `test_sequential_writer()` - 顺序写入测试
  - [ ] `test_parallel_writer()` - 并行写入测试
  - [ ] `test_writer_error_handling()` - 错误处理
  - [ ] `test_checkpoint_roundtrip()` - checkpoint 序列化

**验收标准**:
- ✅ Writer 可以独立运行（不依赖下载逻辑）
- ✅ 并行模式在 Windows 上无文件锁冲突
- ✅ Checkpoint 保存/恢复正确
- ✅ 测试覆盖率 ≥ 90%

---

## Phase 3: 网络层（Week 5-6）

### 目标
分离 HTTP 调用、重试逻辑、认证管理

### 任务清单

- [ ] **Session 工厂** (1 天)
  - [ ] `network/session.py`
    - [ ] `create_robust_session()` - 从旧版迁移
    - [ ] 配置连接池、重试、超时

- [ ] **重试策略** (2 天)
  - [ ] `network/retry.py`
    - [ ] `@with_retry` 装饰器
    - [ ] `RetryPolicy` 类（可配置）
    - [ ] 指数退避 + jitter

- [ ] **CAS API 客户端** (3 天)
  - [ ] `network/cas_api.py`
    - [ ] `CASAPIClient` - 纯 API 调用
    - [ ] `get_reconstruction()` - 支持 V1/V2 自动切换
    - [ ] `fetch_xorb_part()` - 下载单个 part
    - [ ] `fetch_xorb()` - 协调 multipart
  - [ ] 错误分类
    - [ ] `FileNotFoundError` (404)
    - [ ] `PermissionError` (401/403)
    - [ ] `TransientError` (5xx, timeout)

- [ ] **认证管理** (1 天)
  - [ ] `network/auth.py` - 从旧版迁移
    - [ ] Token 自动刷新（提前 30s）
    - [ ] Thread-safe

- [ ] **集成测试** (2 天)
  - [ ] Mock CAS API 响应
  - [ ] 测试 V1/V2 格式转换
  - [ ] 测试 403 重试逻辑
  - [ ] 测试 Token 刷新

**验收标准**:
- ✅ API 客户端可独立使用（不依赖 Reconstructor）
- ✅ 重试逻辑可配置（最大次数、退避策略）
- ✅ Mock 测试覆盖所有错误路径
- ✅ 测试覆盖率 ≥ 85%

---

## Phase 4: 管道层（Week 7-9）

### 目标
实现下载调度、并发控制、数据组装

### 任务清单

- [ ] **并发控制** (2 天)
  - [ ] `pipeline/concurrency.py`
    - [ ] `ConcurrencyController` - 简化版 ACC
    - [ ] `acquire()` / `release()`
    - [ ] `report_success()` / `report_failure()`
    - [ ] AIMD 算法（成功+1，失败×0.5）

- [ ] **下载器** (3 天)
  - [ ] `pipeline/downloader.py`
    - [ ] `XorbDownloader` - 协调并发下载
    - [ ] `download_all()` - Single-flight 去重
    - [ ] 与 `ConcurrencyController` 集成

- [ ] **组装器** (3 天)
  - [ ] `pipeline/assembler.py`
    - [ ] `FileAssembler` - 按 terms 顺序组装
    - [ ] `assemble()` - 从 xorb cache 提取数据
    - [ ] 处理 `offset_into_first_range`

- [ ] **调度器** (3 天)
  - [ ] `pipeline/scheduler.py`
    - [ ] `DownloadScheduler` - 顶层协调
    - [ ] 状态机（Init → Auth → Recon → Download → Assemble → Verify → Done）
    - [ ] 进度报告接口

- [ ] **集成测试** (3 天)
  - [ ] 端到端测试（小文件）
  - [ ] 测试分段模式
  - [ ] 测试断点续传
  - [ ] 测试并发控制

**验收标准**:
- ✅ 可以完整下载一个小文件（<100MB）
- ✅ 状态机清晰（每个状态可单独测试）
- ✅ 支持进度回调
- ✅ 测试覆盖率 ≥ 80%

---

## Phase 5: CLI 集成（Week 10）

### 目标
实现 CLI，保持与旧版兼容

### 任务清单

- [ ] **CLI 入口** (2 天)
  - [ ] `cli.py` - 主入口
  - [ ] 命令行参数解析（复用旧版）
  - [ ] 进度条集成（tqdm）

- [ ] **兼容层** (2 天)
  - [ ] 支持旧版的所有参数
  - [ ] 配置文件支持
  - [ ] 环境变量支持

- [ ] **端到端测试** (3 天)
  - [ ] 测试所有模式（auto/xet/direct）
  - [ ] 测试分段模式
  - [ ] 测试并行模式
  - [ ] 测试中断续传

**验收标准**:
- ✅ CLI 功能与旧版一致
- ✅ 可以替换旧版使用
- ✅ 所有旧版 bug 已修复

---

## Phase 6: 性能优化与文档（Week 11-12）

### 任务清单

- [ ] **性能优化** (3 天)
  - [ ] Profile 找出热点
  - [ ] 优化内存使用
  - [ ] 优化 xorb 解压（考虑 Rust 扩展）

- [ ] **文档完善** (3 天)
  - [ ] API 参考文档
  - [ ] 用户手册
  - [ ] 故障排查手册
  - [ ] 迁移指南（从旧版升级）

- [ ] **打包发布** (2 天)
  - [ ] PyPI 打包
  - [ ] Docker 镜像
  - [ ] 发布 v1.0.0

**验收标准**:
- ✅ 性能不低于旧版
- ✅ 文档完整
- ✅ 可以通过 pip 安装

---

## 里程碑

| 里程碑 | 时间 | 目标 |
|--------|------|------|
| M1: 协议层完成 | Week 2 | 纯函数可用，测试覆盖 100% |
| M2: 存储层完成 | Week 4 | Writer 可用，Checkpoint 工作 |
| M3: 网络层完成 | Week 6 | API 客户端可用，重试健壮 |
| M4: 管道层完成 | Week 9 | 可下载小文件，状态机清晰 |
| M5: CLI 可用 | Week 10 | 功能对齐旧版 |
| M6: v1.0.0 发布 | Week 12 | 生产就绪 |

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 协议理解偏差 | 高 | 参考 Rust 代码，调试对比 |
| 性能不如旧版 | 中 | 提前 Profile，必要时用 Rust 扩展 |
| 兼容性问题 | 中 | 保留兼容层，逐步迁移 |
| 测试不充分 | 高 | 每个阶段都要达到覆盖率目标 |

---

## 下一步

1. **立即开始**: Phase 1 - 协议层纯函数提取
2. **第一个 PR**: `protocol/xorb_format.py` + 单元测试
3. **每周回顾**: 检查进度，调整计划
