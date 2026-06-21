# XET+ 文档索引

> 完整文档导航 - 快速找到你需要的信息

---

## 🎯 新用户入门

**第一次接触项目？按此顺序阅读**：

1. 📖 [README.md](../README.md) - 5 分钟了解项目 ⭐
2. 🚀 [快速开始.md](快速开始.md) - 快速开始（安装、基本使用）
3. 👤 [用户指南.md](用户指南.md) - 完整使用指南
4. 🌐 [网络选项指南.md](网络选项指南.md) - 网络选项完整说明
5. 🏗️ [架构设计.md](架构设计.md) - 深入架构设计

---

## 📚 核心文档

### 用户文档

- **[快速开始.md](快速开始.md)** - 快速开始（安装、基本使用）
- **[用户指南.md](用户指南.md)** - 完整使用指南（命令、参数、示例）
- **[网络选项指南.md](网络选项指南.md)** - 网络选项完整说明（代理/HOST优选/镜像）

### 开发文档

- **[架构设计.md](架构设计.md)** - 系统架构设计 ⭐ 必读
- **[贡献指南.md](贡献指南.md)** - 贡献指南（编码规范、PR 流程）
- **[测试指南.md](测试指南.md)** - 测试指南（如何编写和运行测试）
- **[FEATURE_REQUESTS.md](FEATURE_REQUESTS.md)** - 功能请求

### 技术深入

- **[XET_Hash提取方法.md](XET_Hash提取方法.md)** - XET Hash 提取方法（HEAD 命令和三级 fallback）
- **[HuggingFace与hf-mirror对比.md](HuggingFace与hf-mirror对比.md)** - HuggingFace vs hf-mirror 完整对比
- **[XET_METADATA_EXTRACTION_IMPROVEMENTS.md](XET_METADATA_EXTRACTION_IMPROVEMENTS.md)** - XET 元数据提取完整改进报告
- **[CONFIG_COMMAND_TEST_IMPROVEMENTS.md](CONFIG_COMMAND_TEST_IMPROVEMENTS.md)** - Config 命令测试改进（已完成）
- **[VISUAL_IMPROVEMENTS_SUMMARY.md](VISUAL_IMPROVEMENTS_SUMMARY.md)** - 视觉优化和文档完善总结 ⭐ 新增

---

## 🧪 测试文档

### 最新测试报告

- **[P3_INTEGRATION_TEST_REPORT.md](reports/P3_INTEGRATION_TEST_REPORT.md)** - P3 集成测试报告（100% 通过）⭐

### 历史测试报告

- [P2_TEST_REPORT.md](reports/P2_TEST_REPORT.md) - P2 测试报告
- [P1_TEST_PROGRESS.md](reports/P1_TEST_PROGRESS.md) - P1 测试进度
- [P0_TEST_REPORT.md](reports/P0_TEST_REPORT.md) - P0 测试报告
- [OPTIMIZER_FIX_AND_P3.md](reports/OPTIMIZER_FIX_AND_P3.md) - 优化器修复和 P3 测试
- [XET_HASH_EXTRACTION_IMPROVEMENT.md](reports/XET_HASH_EXTRACTION_IMPROVEMENT.md) - Hash 提取改进设计
- [XET_HASH_IMPROVEMENT_SUMMARY.md](reports/XET_HASH_IMPROVEMENT_SUMMARY.md) - Hash 提取改进总结

### 开发者资源

- [dev/已知问题.md](dev/已知问题.md) - 已知问题跟踪
- [dev/测试计划.md](dev/测试计划.md) - 测试计划
- [dev/HOST_OPTIMIZER_DESIGN.md](dev/HOST_OPTIMIZER_DESIGN.md) - HOST 优选器设计
- [dev/HOST_OPTIMIZER_ANALYSIS_FINAL.md](dev/HOST_OPTIMIZER_ANALYSIS_FINAL.md) - HOST 优选器完整分析

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
xetplus/
├── README.md                              # 项目主文档 ⭐
├── README_CN.md                           # 中文说明
│
├── docs/                                  # 文档目录
│   ├── INDEX.md                          # 本文件（文档索引）
│   │
│   ├── 用户文档
│   │   ├── 快速开始.md                 # 快速开始
│   │   ├── 用户指南.md                 # 完整使用指南
│   │   └── 网络选项指南.md      # 网络选项完整说明
│   │
│   ├── 开发文档
│   │   ├── 架构设计.md               # 系统架构
│   │   ├── 贡献指南.md               # 贡献指南
│   │   ├── 测试指南.md              # 测试指南
│   │   └── FEATURE_REQUESTS.md           # 功能请求
│   │
│   ├── 技术文档
│   │   ├── XET_Hash提取方法.md       # Hash 提取方法
│   │   ├── HuggingFace与hf-mirror对比.md           # 端点对比
│   │   ├── XET_METADATA_EXTRACTION_IMPROVEMENTS.md  # 元数据提取改进
│   │   └── CONFIG_COMMAND_TEST_IMPROVEMENTS.md  # Config 命令改进
│   │
│   ├── 测试报告 (reports/)
│   │   ├── P3_INTEGRATION_TEST_REPORT.md  # P3 测试报告（最新）⭐
│   │   ├── P2_TEST_REPORT.md             # P2 测试报告
│   │   ├── P1_TEST_PROGRESS.md           # P1 测试进度
│   │   └── P0_TEST_REPORT.md             # P0 测试报告
│   │
│   ├── 开发资源 (dev/)
│   │   ├── KNOWN_ISSUES.md               # 已知问题
│   │   ├── TEST_PLAN.md                  # 测试计划
│   │   ├── HOST_OPTIMIZER_DESIGN.md      # 优选器设计
│   │   └── HOST_OPTIMIZER_ANALYSIS_FINAL.md  # 优选器分析
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
├── tests/                                 # 测试套件
│   └── test_cli_p3_integration.sh        # P3 集成测试脚本
│
└── archive/                               # 历史代码归档
```

---

## 🔍 按主题查找

### 想快速上手使用？
→ [快速开始.md](快速开始.md) ⭐

### 国内网络如何优化？
→ [网络选项指南.md](网络选项指南.md) ⭐

### 想深入了解功能？
→ [用户指南.md](用户指南.md)

### 想理解系统架构？
→ [架构设计.md](架构设计.md) ⭐

### 想贡献代码？
→ [贡献指南.md](贡献指南.md) + [测试指南.md](测试指南.md)

### 想了解 XET 协议细节？
→ [spec/XET.SPEC.md](spec/XET.SPEC.md)

### 想了解最新测试结果？
→ [reports/P3_INTEGRATION_TEST_REPORT.md](reports/P3_INTEGRATION_TEST_REPORT.md) ⭐

### 想了解 XET Hash 提取？
→ [XET_Hash提取方法.md](XET_Hash提取方法.md)

### HuggingFace 和 hf-mirror 有什么区别？
→ [HuggingFace与hf-mirror对比.md](HuggingFace与hf-mirror对比.md)

---

## 📊 文档状态

| 文档 | 状态 | 最后更新 | 说明 |
|------|------|---------|------|
| README.md | ✅ 完整 | 2026-06-21 | v0.5.0-dev |
| 快速开始.md | ✅ 完整 | 2026-06-21 | |
| 用户指南.md | ✅ 完整 | 2026-06-20 | |
| 网络选项指南.md | ✅ 完整 | 2026-06-21 | 新增 |
| 架构设计.md | ✅ 完整 | 2026-06-18 | |
| 测试指南.md | ✅ 完整 | 2026-06-20 | |
| P3_INTEGRATION_TEST_REPORT.md | ✅ 完整 | 2026-06-21 | 100% 通过 |
| XET_Hash提取方法.md | ✅ 完整 | 2026-06-21 | 新增 |
| HuggingFace与hf-mirror对比.md | ✅ 完整 | 2026-06-21 | 新增 |
| spec/*.md | ✅ 完整 | 2026-06-18 | |

---

## 🔄 最近更新

### 2026-06-21 - v0.5.0-dev 里程碑 ✨

**重大改进**：
- ✅ **XET Hash 提取健壮性大幅提升** - 三级 fallback 策略
- ✅ **SHA256 校验支持** - 完整文件校验
- ✅ **HuggingFace + hf-mirror 双支持** - 国内外网络全兼容
- ✅ **P3 集成测试 100% 通过** - 4/4 测试用例全部通过

**文档更新**：
- ✅ 更新 README.md - 反映 v0.5.0-dev 状态
- ✅ 新增 网络选项指南.md - 网络选项完整说明
- ✅ 新增 XET_Hash提取方法.md - Hash 提取方法详解
- ✅ 新增 HuggingFace与hf-mirror对比.md - 端点对比
- ✅ 新增 XET_METADATA_EXTRACTION_IMPROVEMENTS.md - 元数据提取改进
- ✅ 新增 CONFIG_COMMAND_TEST_IMPROVEMENTS.md - Config 命令改进建议
- ✅ 新增 P3_INTEGRATION_TEST_REPORT.md - P3 测试报告
- ✅ 文档整理 - 移动临时文档到 reports/ 和 dev/

**技术细节**：
- ✅ 改进 xet/cli/commands/info.py - 三级 fallback
- ✅ 改进 xet/cli/commands/download.py - 四级 fallback
- ✅ 改进 xet/protocol/types.py - XetFileInfo.from_headers()
- ✅ 修复 test_cli_p3_integration.sh - 配置文件路径修正

### 2026-06-20
- ✅ 更新 用户指南.md - 完善使用指南
- ✅ 更新 测试指南.md - 添加测试示例

### 2026-06-18
- ✅ 创建 架构设计.md - 系统架构文档
- ✅ 创建 贡献指南.md - 贡献指南

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

## 📝 文档贡献

发现文档问题或想要改进？

1. 在 [Issues](https://github.com/yourusername/xetplus/issues) 中报告
2. 提交 Pull Request
3. 遵循 [贡献指南](贡献指南.md)

---

## 🔗 外部资源

- [XetHub 官方文档](https://xethub.com/docs)
- [HuggingFace XET 支持](https://huggingface.co/docs/hub/xet)
- [hf-mirror.com](https://hf-mirror.com) - 国内镜像（完整支持 XET）

---

**文档维护者**: XET+ Team  
**最后更新**: 2026-06-21  
**项目状态**: v0.5.0-dev - P3 测试 100% 通过 ✅  
**核心功能**: 已完成 🎉
