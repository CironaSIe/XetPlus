# XET Plus 文档索引

> 快速导航 - 一页找到所有文档

---

## 🎯 新人入门路径

**第一次接触项目？按此顺序阅读**：

1. 📖 [README_CN.md](README_CN.md) - 5 分钟了解项目（中文）⭐
2. 📊 [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - 10 分钟理解改进对比 ⭐
3. 🏗️ [ARCHITECTURE.md](ARCHITECTURE.md) - 30 分钟深入架构设计 ⭐
4. 🚀 [QUICKSTART.md](QUICKSTART.md) - 5 分钟开始开发

---

## 📚 核心文档（11 个）

### 项目概览

- **[README.md](README.md)** - 项目介绍（英文版）
- **[README_CN.md](README_CN.md)** - 项目介绍（中文版）⭐ 推荐阅读
- **[PROJECT_STATUS.txt](PROJECT_STATUS.txt)** - 项目状态速览

### 设计与规划

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - 架构设计文档 ⭐ 必读
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - 项目对比总结 ⭐ 必读
- **[DESIGN_REVIEW.md](DESIGN_REVIEW.md)** - 设计评审文档（技术负责人用）
- **[ROADMAP.md](ROADMAP.md)** - 12 周开发路线图

### 开发指南

- **[QUICKSTART.md](QUICKSTART.md)** - 快速开始指南
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - 贡献指南与编码规范
- **[TODO.md](TODO.md)** - 每日待办清单 ⭐ 每天查看
- **[ISSUES.md](ISSUES.md)** - 问题跟踪与模板

### 总结报告

- **[FINAL_REPORT.md](FINAL_REPORT.md)** - Phase 0 完成报告 ⭐ 阶段总结

---

## 📁 目录结构

```
xetplus/
├── 📄 11 个核心文档（本页列出）
├── 📁 xet/                   核心库
│   ├── protocol/             协议层（纯逻辑）
│   ├── network/              网络层（HTTP）
│   ├── storage/              存储层（文件 I/O）
│   └── pipeline/             管道层（编排）
├── 📁 tests/                 测试套件
│   ├── unit/                 单元测试
│   ├── integration/          集成测试
│   └── fixtures/             测试数据
└── 📁 docs/                  详细文档
    ├── phase1-plan.md        Phase 1 详细计划 ⭐
    └── decisions/            设计决策记录
```

---

## 🔍 按用途查找

### 我想了解项目

→ [README_CN.md](README_CN.md)  
→ [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)

### 我想理解架构

→ [ARCHITECTURE.md](ARCHITECTURE.md)  
→ [DESIGN_REVIEW.md](DESIGN_REVIEW.md)

### 我想开始开发

→ [QUICKSTART.md](QUICKSTART.md)  
→ [TODO.md](TODO.md)  
→ [docs/phase1-plan.md](docs/phase1-plan.md)

### 我想了解进度

→ [PROJECT_STATUS.txt](PROJECT_STATUS.txt)  
→ [ROADMAP.md](ROADMAP.md)  
→ [FINAL_REPORT.md](FINAL_REPORT.md)

### 我想贡献代码

→ [CONTRIBUTING.md](CONTRIBUTING.md)  
→ [ISSUES.md](ISSUES.md)

---

## 📊 文档统计

| 类型 | 数量 | 总行数 |
|------|------|--------|
| 核心文档 | 11 | 2,594 |
| 代码模块 | 4 层 | 0（待开发） |
| 测试代码 | 3 类 | 0（待开发） |
| 详细计划 | 1 | 168 |

---

## ⭐ 推荐阅读组合

### 快速了解（30 分钟）

1. README_CN.md（5 min）
2. PROJECT_SUMMARY.md（10 min）
3. TODO.md（5 min）
4. docs/phase1-plan.md（10 min）

### 深度理解（2 小时）

1. README_CN.md（5 min）
2. PROJECT_SUMMARY.md（10 min）
3. ARCHITECTURE.md（30 min）
4. DESIGN_REVIEW.md（45 min）
5. ROADMAP.md（20 min）
6. FINAL_REPORT.md（10 min）

### 立即开发（10 分钟）

1. QUICKSTART.md（5 min）
2. TODO.md（2 min）
3. 开始第一个任务（立即）

---

## 📞 快速链接

### 外部资源

- 旧版代码：`~/xet.py/`
- 文档参考：`~/xet.py/docs/`

### 内部模块

- Protocol Layer：`xet/protocol/README.md`
- 其他层文档：待创建（Phase 2-4）

---

## 🎯 当前状态

**Phase**: 0 完成 ✅，1 就绪 🚧  
**里程碑**: M0 完成，M1 进行中  
**下一步**: 复制 `types.py`，开始协议层提取

详见：[TODO.md](TODO.md)

---

**更新时间**: 2026-06-20  
**版本**: v0.1.0-dev
