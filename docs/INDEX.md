# XET Plus 文档索引

> 快速导航 - 一站式查找所有文档

---

## 🎯 新用户入门

**第一次接触项目？按此顺序阅读**：

1. 📖 [README.md](../README.md) - 5 分钟了解项目 ⭐
2. 🚀 [QUICKSTART.md](QUICKSTART.md) - 快速开始（安装、基本使用）
3. 👤 [USER_GUIDE.md](USER_GUIDE.md) - 完整使用指南
4. 🏗️ [ARCHITECTURE.md](ARCHITECTURE.md) - 深入架构设计

---

## 📚 核心文档

### 用户文档

- **[QUICKSTART.md](QUICKSTART.md)** - 快速开始（安装、基本使用）
- **[USER_GUIDE.md](USER_GUIDE.md)** - 完整使用指南（命令、参数、示例）

### 开发文档

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - 系统架构设计 ⭐ 必读
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - 贡献指南（编码规范、PR 流程）
- **[TESTING_GUIDE.md](TESTING_GUIDE.md)** - 测试指南（如何编写和运行测试）
- **[FEATURE_REQUESTS.md](FEATURE_REQUESTS.md)** - 功能请求

---

## 📖 规范文档

### XET 协议规范（spec/ 目录）

- **[XET.SPEC.md](spec/XET.SPEC.md)** - XET 协议完整规范
- **[XET.HASH.md](spec/XET.HASH.md)** - XET Merkle 哈希规范
- **[XET.BLAKE3.md](spec/XET.BLAKE3.md)** - Blake3 哈希使用规范
- **[XET.ALIGNMENT.md](spec/XET.ALIGNMENT.md)** - Python 实现与 Rust 对齐检查清单

### 参考文档

- **[RUST_MERKLEHASH_REFERENCE.md](RUST_MERKLEHASH_REFERENCE.md)** - Rust MerkleHash 参考实现
- **[XET_ARCHITECTURE_REFERENCE.md](XET_ARCHITECTURE_REFERENCE.md)** - XET 架构参考
- **[XET_PIPELINE_ANALYSIS.md](XET_PIPELINE_ANALYSIS.md)** - Pipeline 分析文档

### API 规范

- **[cas.openapi.yaml](cas.openapi.yaml)** - CAS API OpenAPI 规范
- **[guide.md](guide.md)** - API 使用指南

---

## 🗂️ 文档组织

```
.
├── README.md                              # 项目主文档
├── README_CN.md                           # 中文说明
├── 待修问题.md                            # 问题跟踪（已全部修复）
├── CHUNK_CACHE_FIX_COMPLETION.md         # Chunk cache 修复总结
│
├── docs/
│   ├── INDEX.md                          # 本文件（文档索引）
│   │
│   ├── 用户文档
│   │   ├── QUICKSTART.md                 # 快速开始
│   │   └── USER_GUIDE.md                 # 完整使用指南
│   │
│   ├── 开发文档
│   │   ├── ARCHITECTURE.md               # 系统架构
│   │   ├── CONTRIBUTING.md               # 贡献指南
│   │   ├── TESTING_GUIDE.md              # 测试指南
│   │   └── FEATURE_REQUESTS.md           # 功能请求
│   │
│   ├── 规范文档 (spec/)
│   │   ├── XET.SPEC.md                   # 协议规范
│   │   ├── XET.HASH.md                   # 哈希规范
│   │   ├── XET.BLAKE3.md                 # Blake3 规范
│   │   └── XET.ALIGNMENT.md              # 对齐检查清单
│   │
│   └── archive/                          # 历史文档（已归档）
│       ├── [Phase 1-5 报告]
│       ├── [设计分析文档]
│       └── [实现总结文档]
│
└── debug_materials/
    ├── COMPLETE_FIX_SUMMARY.md           # Chunk cache 完整修复总结 ⭐
    ├── [测试脚本和数据]
    └── archive/                          # 旧版修复记录
```

---

## 🔍 按主题查找

### 想快速上手使用？
→ [QUICKSTART.md](QUICKSTART.md) ⭐

### 想深入了解功能？
→ [USER_GUIDE.md](USER_GUIDE.md)

### 想理解系统架构？
→ [ARCHITECTURE.md](ARCHITECTURE.md) ⭐

### 想贡献代码？
→ [CONTRIBUTING.md](CONTRIBUTING.md) + [TESTING_GUIDE.md](TESTING_GUIDE.md)

### 想了解 XET 协议细节？
→ [spec/XET.SPEC.md](spec/XET.SPEC.md)

### 想对齐 Rust 实现？
→ [spec/XET.ALIGNMENT.md](spec/XET.ALIGNMENT.md)

### 想了解最新修复？
→ [../CHUNK_CACHE_FIX_COMPLETION.md](../CHUNK_CACHE_FIX_COMPLETION.md) ⭐

---

## 📊 文档状态

| 文档 | 状态 | 最后更新 | 说明 |
|------|------|---------|------|
| USER_GUIDE.md | ✅ 完整 | 2026-06-20 | |
| QUICKSTART.md | ✅ 完整 | 2026-06-21 | |
| ARCHITECTURE.md | ✅ 完整 | 2026-06-18 | |
| TESTING_GUIDE.md | ✅ 完整 | 2026-06-20 | |
| CONTRIBUTING.md | ✅ 完整 | 2026-06-18 | |
| CHUNK_CACHE_FIX_COMPLETION.md | ✅ 完整 | 2026-06-21 | 最新 |
| spec/*.md | ✅ 完整 | 2026-06-18 | |

---

## 🔄 最近更新

### 2026-06-21 - 文档清理 & Chunk Cache 完整修复 ✨

**文档清理**：
- ✅ 清理根目录：移动 7 个历史文档到 `docs/archive/`
- ✅ 清理 docs/：移动 17 个历史文档到 `docs/archive/`
- ✅ 根目录现在只保留 5 个核心文档
- ✅ docs/ 现在只保留 6 个核心文档
- ✅ 所有历史文档已归档，随时可查

**Chunk Cache 修复**：
- ✅ 完整修复 chunk cache - 支持不连续 chunk ranges
- ✅ 缓存成功率：0% → 100%
- ✅ 所有 11 个待修问题已全部解决
- ✅ 新增 `CHUNK_CACHE_FIX_COMPLETION.md` - 完整修复总结
- ✅ 新增 `debug_materials/COMPLETE_FIX_SUMMARY.md` - 技术细节

### 2026-06-20
- ✅ 更新 USER_GUIDE.md - 完善使用指南
- ✅ 更新 TESTING_GUIDE.md - 添加测试示例

### 2026-06-18
- ✅ 创建 ARCHITECTURE.md - 系统架构文档
- ✅ 创建 CONTRIBUTING.md - 贡献指南

---

## 📂 已归档文档

所有历史文档已移至 `docs/archive/`，包括：

- Phase 1-5 的各阶段报告
- 设计分析和对比文档
- CLI 改进和日志修复总结
- 并行写入设计和实现文档
- Chunk cache 的早期设计文档

**访问归档**：`docs/archive/` 目录

---

**文档维护者**: XET+ Team  
**最后更新**: 2026-06-21  
**项目状态**: v0.5.0 - 所有核心功能已完成 ✅  
**待修问题**: 0 个（已全部解决）🎉
