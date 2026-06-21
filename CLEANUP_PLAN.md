# 文档清理计划

## 📋 文档分类

### ✅ 保留 - 核心文档（必须保留）

#### 根目录
1. `README.md` - 项目主文档
2. `README_CN.md` - 中文说明
3. `待修问题.md` - 问题跟踪（已全部修复）
4. `CHUNK_CACHE_FIX_COMPLETION.md` - 最新修复总结

#### docs/
5. `INDEX.md` - 文档索引
6. `QUICKSTART.md` - 快速开始
7. `USER_GUIDE.md` - 用户指南
8. `ARCHITECTURE.md` - 架构文档
9. `CONTRIBUTING.md` - 贡献指南
10. `TESTING_GUIDE.md` - 测试指南

#### debug_materials/
11. `COMPLETE_FIX_SUMMARY.md` - chunk cache 完整修复总结（最新最全）

---

### 🗄️ 归档 - 历史文档（移到 archive）

#### 根目录 → docs/archive/
- `CLI_IMPROVEMENTS_FINAL.md` - CLI 改进（已完成）
- `CODE_REVIEW_2026-06-21.md` - 代码审查（已完成）
- `DESIGN_COMPARISON.md` - 设计对比
- `INFO_XETPY.md` - xetpy 信息
- `LOGGING_GUIDE.md` - 日志指南
- `RELEASE_v0.4.1.md` - 发布记录
- `XETPY_VS_XETPLUS_COMPARISON.md` - 对比分析

#### docs/ → docs/archive/
- `CACHE_DESIGN_ANALYSIS.md` - 缓存设计分析（被 COMPLETE_FIX_SUMMARY 替代）
- `CAS_API_DEBUG.md` - CAS API 调试
- `CHUNK_CACHE_IMPLEMENTATION.md` - chunk cache 实现（旧版）
- `CHUNK_CACHE_QUICKSTART.md` - chunk cache 快速开始（旧版）
- `CHUNK_CACHE_REFACTOR_PLAN.md` - 重构计划（已完成）
- `CLI_PARAMETERS_COMPARISON.md` - CLI 参数对比
- `DOCUMENTATION_CLEANUP_2026-06-21.md` - 文档清理记录
- `FIX_SUMMARY_20260621.md` - 修复总结
- `ISSUE_SUMMARY_20260621.md` - 问题总结
- `LOGGING_COMPARISON.md` - 日志对比
- `LOGGING_FIX_SUMMARY.md` - 日志修复
- `PARALLEL_WRITE_DESIGN_ANALYSIS.md` - 并行写设计
- `PARALLEL_WRITE_IMPLEMENTATION.md` - 并行写实现
- `TESTING_PLAN.md` - 测试计划（被 TESTING_GUIDE 替代）
- `XETCORE分析.md` - xetcore 分析
- `XETPLUS_COMPARISON.md` - xetplus 对比
- `XETPY分析.md` - xetpy 分析

#### debug_materials/ → debug_materials/archive/
- `CHUNK_CACHE_STATUS.md` - 部分修复状态（被 COMPLETE_FIX_SUMMARY 替代）
- `FIX_SUMMARY.md` - 初始修复记录（被 COMPLETE_FIX_SUMMARY 替代）

---

### ❌ 删除 - 完全过期（可以删除）

无 - 所有文档都有历史价值，建议归档而不是删除

---

## 🎯 清理后的文档结构

```
.
├── README.md                           # 项目主文档
├── README_CN.md                        # 中文说明
├── 待修问题.md                         # 问题跟踪（已全部修复）
├── CHUNK_CACHE_FIX_COMPLETION.md      # 最新修复总结
│
├── docs/
│   ├── INDEX.md                       # 文档索引（需更新）
│   ├── QUICKSTART.md                  # 快速开始
│   ├── USER_GUIDE.md                  # 用户指南
│   ├── ARCHITECTURE.md                # 架构文档
│   ├── CONTRIBUTING.md                # 贡献指南
│   ├── TESTING_GUIDE.md               # 测试指南
│   ├── FEATURE_REQUESTS.md            # 功能请求
│   │
│   └── archive/                       # 历史文档
│       ├── [根目录归档的 7 个文件]
│       ├── [docs 归档的 16 个文件]
│       └── [原有的 13 个文件]
│
└── debug_materials/
    ├── COMPLETE_FIX_SUMMARY.md        # 完整修复总结（保留）
    ├── [测试脚本和数据文件]
    │
    └── archive/                       # 旧版总结
        ├── CHUNK_CACHE_STATUS.md
        └── FIX_SUMMARY.md
```

---

## 📝 执行步骤

1. 创建 `debug_materials/archive/` 目录
2. 移动根目录的 7 个过期文档到 `docs/archive/`
3. 移动 docs/ 的 16 个过期文档到 `docs/archive/`
4. 移动 debug_materials/ 的 2 个旧版总结到 `debug_materials/archive/`
5. 更新 `docs/INDEX.md` 反映新的文档结构
6. 提交所有更改

---

## ✨ 清理后的优势

- ✅ 核心文档清晰，易于查找
- ✅ 历史文档归档保存，随时可查
- ✅ 减少根目录和 docs/ 的混乱
- ✅ 新用户不会被过期文档困扰
