# XET Plus - 待办事项

## 🚀 立即行动（今天）

### Phase 1 - Task 1.1: 复制数据结构

```bash
# 1. 复制 types.py
cp ~/xet.py/xet/types.py ~/xetplus/xet/protocol/types.py

# 2. 添加类型注解头部
echo "from __future__ import annotations" > tmp && cat ~/xetplus/xet/protocol/types.py >> tmp && mv tmp ~/xetplus/xet/protocol/types.py

# 3. 验证
cd ~/xetplus
python3 -c "from xet.protocol.types import HttpRange; print('✅ Import OK')"
```

**预计时间**: 2 小时

---

## 📋 本周任务（Phase 1）

### Day 1-2: 数据结构 + 基础函数

- [ ] 复制 `types.py` 并添加类型注解
- [ ] 创建 `xorb_format.py`
- [ ] 实现 `parse_xorb_header()`
- [ ] 编写第一个单元测试

### Day 3-4: 核心解析逻辑

- [ ] 实现 `decompress_chunk()`（LZ4, BG4）
- [ ] 实现 `deserialize_xorb_stream()`
- [ ] 编写边界测试（truncated, corrupted）

### Day 5: 测试覆盖 + 文档

- [ ] 完善单元测试（目标 100%）
- [ ] 编写 `protocol/README.md`
- [ ] 运行 `pytest` + `mypy` 验证

---

## 📅 下周任务（Phase 2 预告）

- [ ] 设计 `FileWriter` 接口
- [ ] 实现 `SequentialWriter`
- [ ] 实现 `ParallelWriter`（解决 Windows 文件锁）

---

## 🔍 技术债务跟踪

### 来自旧版的已知问题

1. **xorb hash 校验缺失** - 协议层暂不实现，等待 HF 确认
2. **403 风暴** - 网络层用协调器解决
3. **Windows 文件锁** - 存储层用单 Writer 线程解决
4. **ACC 固定并发** - 管道层实现自适应 AIMD

---

## ✅ 完成记录

### 2026-06-20

- [x] 创建项目目录结构
- [x] 编写 8 个核心文档
  - [x] README.md / README_CN.md
  - [x] ARCHITECTURE.md
  - [x] ROADMAP.md
  - [x] PROJECT_SUMMARY.md
  - [x] QUICKSTART.md
  - [x] CONTRIBUTING.md
  - [x] ISSUES.md
  - [x] DESIGN_REVIEW.md
- [x] 配置 `pyproject.toml`
- [x] 创建目录结构（protocol/, network/, storage/, pipeline/, tests/）

---

## 💡 每日提醒

**开始开发前**:
```bash
cd ~/xetplus
cat docs/phase1-plan.md  # 查看今日任务
```

**完成任务后**:
```bash
# 运行测试
pytest -v

# 代码检查
black xet/ tests/
ruff check xet/
mypy xet/

# 提交
git add .
git commit -m "feat: xxx"
```

**每天结束时**:
- 更新此文件（勾选完成的任务）
- 记录遇到的问题到 `ISSUES.md`
- 推送代码（如果协作）

---

## 📞 需要帮助？

- 查看 `ARCHITECTURE.md` - 架构设计
- 查看 `docs/phase1-plan.md` - 详细计划
- 查看 `CONTRIBUTING.md` - 开发规范
- 在 Issues 中提问
