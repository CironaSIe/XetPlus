# 快速开始

## 安装

### 开发环境

```bash
cd ~/xetplus

# 安装开发依赖
pip install -e ".[dev,cli]"

# 验证安装
python -c "import xet; print(xet.__version__)"
```

### 运行测试

```bash
# 运行所有测试
pytest

# 查看覆盖率
pytest --cov=xet --cov-report=html
open htmlcov/index.html

# 运行特定测试
pytest tests/unit/test_xorb_format.py -v

# 只运行快速测试
pytest -m "not slow"
```

### 代码质量检查

```bash
# 格式化代码
black xet/ tests/

# 检查代码质量
ruff check xet/ tests/

# 类型检查
mypy xet/

# 全部运行
black xet/ tests/ && ruff check xet/ tests/ && mypy xet/ && pytest
```

---

## 当前进度

### ✅ 已完成

- [x] 项目结构搭建
- [x] 文档框架（README, ARCHITECTURE, ROADMAP）
- [x] 开发规范（CONTRIBUTING, pyproject.toml）

### 🚧 进行中（Phase 1）

**当前任务**: 协议层纯函数提取

**下一步行动**:

```bash
# Step 1: 复制数据结构
cp ~/xet.py/xet/types.py ~/xetplus/xet/protocol/types.py

# Step 2: 开始提取 xorb_format.py
vim ~/xetplus/xet/protocol/xorb_format.py

# Step 3: 编写测试
vim ~/xetplus/tests/unit/test_xorb_format.py
```

---

## 项目结构速查

```
xetplus/
├── README.md              # 项目介绍
├── ARCHITECTURE.md        # 架构设计文档 ⭐
├── ROADMAP.md             # 开发路线图 ⭐
├── ISSUES.md              # 问题跟踪
├── CONTRIBUTING.md        # 贡献指南
├── pyproject.toml         # 项目配置
│
├── xet/                   # 核心库
│   ├── protocol/          # 协议层（纯逻辑）
│   ├── network/           # 网络层（HTTP）
│   ├── storage/           # 存储层（文件 I/O）
│   └── pipeline/          # 管道层（编排）
│
├── tests/                 # 测试套件
│   ├── unit/              # 单元测试
│   ├── integration/       # 集成测试
│   └── fixtures/          # 测试数据
│
└── docs/                  # 详细文档
    ├── phase1-plan.md     # Phase 1 详细计划 ⭐
    └── decisions/         # 设计决策记录
```

---

## 关键文档

### 🎯 立即阅读

1. **ARCHITECTURE.md** - 理解整体架构设计
2. **ROADMAP.md** - 查看完整开发计划（12 周）
3. **docs/phase1-plan.md** - 当前阶段详细任务

### 📚 参考文档

- **CONTRIBUTING.md** - 编码规范和提交流程
- **ISSUES.md** - 问题跟踪和模板

---

## 开发流程示例

### 添加新功能

```bash
# 1. 创建分支
git checkout -b feature/xorb-parser

# 2. 编写代码
vim xet/protocol/xorb_format.py

# 3. 编写测试
vim tests/unit/test_xorb_format.py

# 4. 运行测试
pytest tests/unit/test_xorb_format.py -v

# 5. 代码检查
black xet/ tests/
ruff check xet/
mypy xet/

# 6. 提交
git add .
git commit -m "feat: add xorb header parser"

# 7. 推送（如果是协作）
git push origin feature/xorb-parser
```

### 修复 Bug

```bash
# 1. 创建分支
git checkout -b fix/deserialize-truncated

# 2. 添加失败测试（TDD）
vim tests/unit/test_xorb_format.py
# def test_deserialize_truncated():
#     with pytest.raises(ValueError):
#         deserialize_xorb_stream(truncated_data)

# 3. 运行测试（应该失败）
pytest tests/unit/test_xorb_format.py::test_deserialize_truncated

# 4. 修复代码
vim xet/protocol/xorb_format.py

# 5. 验证测试通过
pytest tests/unit/test_xorb_format.py::test_deserialize_truncated

# 6. 提交
git commit -am "fix: handle truncated xorb data"
```

---

## 常见问题

### Q: 为什么要重构？

旧版 `xet.py` 存在：
- 单文件过大（2,363 行 reconstructor.py）
- 职责混乱（God Class）
- 无单元测试（调试靠 19k 行日志）
- Bug 修复困难（头疼医头）

新版目标：
- 模块化（每个文件 <500 行）
- 职责清晰（每个模块单一职责）
- 测试覆盖（80%+ 覆盖率）
- 易于维护（bug 修复范围小）

### Q: 会保持兼容吗？

是的，渐进式迁移：
- Phase 1-4: 独立开发新模块
- Phase 5: 实现 CLI 兼容层
- Phase 6: 性能对齐旧版

用户可以无缝切换。

### Q: 性能会下降吗？

不会。通过：
- Profile 找出热点
- 必要时用 Rust 扩展优化
- 内存管理优化（LRU 缓存）

目标：性能 ≥ 旧版。

---

## 联系方式

- **问题报告**: GitHub Issues
- **功能建议**: GitHub Discussions
- **紧急问题**: [邮件联系]

---

## License

MIT License - 查看 LICENSE 文件
