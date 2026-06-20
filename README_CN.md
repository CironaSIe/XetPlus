# XET Plus - XET 协议下载器（重构版）

> **为什么重构？** 旧版 xet.py 虽然能用，但代码混乱、难以维护。重构目标：清晰架构、完善测试、易于扩展。

[English](README.md) | **中文**

---

## ⚡ 快速导航

- **新手入门**: 阅读 [QUICKSTART.md](QUICKSTART.md)
- **架构设计**: 阅读 [ARCHITECTURE.md](ARCHITECTURE.md)
- **开发计划**: 阅读 [ROADMAP.md](ROADMAP.md)
- **项目总结**: 阅读 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) ⭐

---

## 🎯 项目目标

基于 `xet.py` 的经验教训，重新设计一个：

1. **模块化** - 每个模块只做一件事，单文件 <500 行
2. **可测试** - 80%+ 测试覆盖率，单元测试快速定位问题
3. **易维护** - 清晰的架构，bug 修复影响范围小
4. **生产就绪** - 完善的错误处理、日志、文档

---

## 📊 与旧版对比

| 维度 | xet.py | xetplus | 改善 |
|------|--------|---------|------|
| **最大文件** | 2,363 行 | <500 行/文件 | -80% |
| **测试** | 0 个 | 100+ 个 | ∞ |
| **覆盖率** | 0% | 80%+ | 质量保证 |
| **架构** | 单体混杂 | 4 层分离 | 易于理解 |
| **调试** | 看日志猜 | 单元测试定位 | 高效 |

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────┐
│         CLI Layer (cli.py)          │  命令行接口
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│    Pipeline Layer (pipeline/)       │  编排下载流程
│  - Scheduler, Downloader, Assembler │
└──────────────┬──────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │          │
    ▼          ▼          ▼
┌────────┐ ┌─────────┐ ┌──────────┐
│Network │ │Storage  │ │ Protocol │
│ Layer  │ │ Layer   │ │  Layer   │
│ HTTP   │ │ File I/O│ │纯逻辑    │
└────────┘ └─────────┘ └──────────┘
```

**核心改进**:
- **Protocol Layer**: 纯函数，易于测试
- **Storage Layer**: 统一 Writer 接口（顺序/并行模式）
- **Network Layer**: API 调用 + 重试解耦
- **Pipeline Layer**: 状态机清晰，可观测

详见 [ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📅 开发计划

**总计 12 周，分 6 个阶段**：

| Phase | 时间 | 目标 | 状态 |
|-------|------|------|------|
| Phase 1 | Week 1-2 | 协议层纯函数提取 | 🚧 进行中 |
| Phase 2 | Week 3-4 | 存储层（Writer + Checkpoint） | 📋 待开始 |
| Phase 3 | Week 5-6 | 网络层（API + 重试） | 📋 待开始 |
| Phase 4 | Week 7-9 | 管道层（调度 + 并发） | 📋 待开始 |
| Phase 5 | Week 10 | CLI 集成 | 📋 待开始 |
| Phase 6 | Week 11-12 | 性能优化 + 文档 | 📋 待开始 |

详见 [ROADMAP.md](ROADMAP.md)

---

## 🚀 快速开始

### 1. 克隆项目

```bash
cd ~/xetplus
```

### 2. 安装依赖

```bash
pip install -e ".[dev,cli]"
```

### 3. 运行测试

```bash
pytest tests/ -v
```

### 4. 开始开发

```bash
# 查看当前任务
cat docs/phase1-plan.md

# 开始第一个任务
cp ~/xet.py/xet/types.py xet/protocol/types.py
```

详见 [QUICKSTART.md](QUICKSTART.md)

---

## 📚 文档索引

### 核心文档

- [README.md](README.md) - 项目介绍（英文）
- [README_CN.md](README_CN.md) - 项目介绍（中文）⭐
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - 项目总结 ⭐
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [ROADMAP.md](ROADMAP.md) - 开发路线图
- [QUICKSTART.md](QUICKSTART.md) - 快速开始

### 开发文档

- [CONTRIBUTING.md](CONTRIBUTING.md) - 贡献指南
- [ISSUES.md](ISSUES.md) - 问题跟踪
- [docs/phase1-plan.md](docs/phase1-plan.md) - Phase 1 详细计划

---

## 💡 设计亮点

### 1. 纯函数优先

```python
# 易于测试，无副作用
def deserialize_xorb_stream(data: bytes) -> Tuple[bytes, List]:
    """纯函数：输入 bytes，输出解析结果"""
    pass

# 测试简单
assert deserialize_xorb_stream(sample)[0] == expected_data
```

### 2. 策略模式 Writer

```python
# 统一接口，模式切换无需改代码
writer = create_writer(path, mode='sequential')  # 或 'parallel'
writer.write_at(0, data)
writer.close()
```

### 3. 装饰器重试

```python
# 重试逻辑统一，业务代码清晰
@with_retry(max_attempts=5)
def fetch_data(url: str) -> bytes:
    return requests.get(url).content
```

---

## 🎯 当前进度

### ✅ 已完成

- [x] 项目结构搭建
- [x] 文档框架（8 个核心文档）
- [x] 开发规范配置（pytest, black, ruff, mypy）

### 🚧 进行中（Phase 1）

**当前任务**: 协议层纯函数提取

**下一步**:
1. 复制 `types.py` 到新项目
2. 提取 `xorb_format.py` 的纯函数
3. 编写单元测试（目标 100% 覆盖）

**预计完成**: 5 个工作日

---

## 🤝 贡献

欢迎贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

**参与方式**:
1. Fork 项目
2. 创建特性分支
3. 编写代码 + 测试
4. 提交 PR

---

## 📄 许可证

MIT License

---

## 🙏 致谢

本项目基于 `xet.py` 的经验教训重新设计。

感谢所有贡献者！
