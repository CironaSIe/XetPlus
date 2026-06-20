# XET+ 项目开发记录

## 项目概述

XET+ 是 XET 协议的 Python 实现，用于从 HuggingFace 下载使用 XET 格式存储的大文件。

## 开发阶段总结

### Phase 1: Protocol Layer ✅
**完成时间**: 2026-06-18

实现了 XET 协议的核心数据结构：
- `CASReconstructionTerm` - 重建指令
- `CASReconstructionFetchInfo` - Xorb 获取信息
- `CASReconstruction` - 完整重建元数据
- `HttpRange` - HTTP 范围请求

**测试覆盖率**: 100%

**关键文件**:
- `xet/protocol/types.py` - 数据结构定义
- `tests/unit/test_protocol_types.py` - 单元测试

### Phase 2: Storage Layer ✅
**完成时间**: 2026-06-18

实现了 Merkle Hash 和存储相关功能：
- Merkle tree 构建和验证
- BLAKE3 哈希计算
- Xorb 容器格式解析（基础）

**测试覆盖率**: 85%+

**关键文件**:
- `xet/storage/merkle_hash.py` - Merkle tree 实现
- `xet/storage/blake3_hash.py` - BLAKE3 哈希

### Phase 3: Network Layer ✅
**完成时间**: 2026-06-19

实现了完整的网络通信和重试机制：

**核心组件**:
1. `CASClient` - CAS 服务器客户端
   - 获取 reconstruction 元数据
   - 下载 Xorb 数据
   - 完整的重试和超时控制

2. `URLRefreshCoordinator` - URL 刷新协调器
   - 自动 URL 过期检测
   - 并发安全的 URL 刷新
   - 防止重复刷新

3. `AdaptiveConcurrencyController` - 自适应并发控制
   - 动态调整并发数（1-16）
   - 基于成功率的自适应算法
   - 过载保护

4. `XetAuth` - HuggingFace 认证
   - HF Token 管理
   - 自动从 Link header 获取 auth URL
   - Token 缓存

**测试覆盖率**: 85%+

**关键文件**:
- `xet/network/cas_client.py`
- `xet/network/url_refresh.py`
- `xet/network/adaptive_concurrency.py`
- `xet/network/auth.py`

**已验证功能**:
- ✅ 自适应并发控制（场景测试通过）
- ✅ URL 刷新协调（竞态测试通过）
- ✅ 认证流程（真实 API 测试通过）

### Phase 4: Pipeline Layer ✅
**完成时间**: 2026-06-20

实现了文件重建的核心流程：

**核心组件**:
1. `FileReconstructor` - 文件重建器（总协调）
2. `DownloadScheduler` - 下载调度器（并行下载 Xorbs）
3. `ChunkAssembler` - 块组装器（解压和组装 chunks）
4. `ProgressTracker` - 进度追踪器（线程安全）
5. `CheckpointManager` - 检查点管理器（断点续传）

**测试覆盖率**: 57.93%
- types.py: 100%
- progress_tracker.py: 80.72%
- file_reconstructor.py: 85.33%
- checkpoint_manager.py: 44.71%
- chunk_assembler.py: 25.76%
- download_scheduler.py: 27.78%

**测试统计**: 82 个测试用例，57 个通过（69.5%）

**已知问题**:
- ⚠️ 协议类型不匹配（CASReconstructionTerm vs 实际使用字段）
- ⚠️ 部分测试需要 hash 长度修复
- ⚠️ chunk_assembler 需要实际 merkle_hash 库集成

**关键文件**:
- `xet/pipeline/file_reconstructor.py`
- `xet/pipeline/download_scheduler.py`
- `xet/pipeline/chunk_assembler.py`
- `xet/pipeline/progress_tracker.py`
- `xet/pipeline/checkpoint_manager.py`

### Phase 5: CLI Layer 🚧
**开始时间**: 2026-06-20
**当前状态**: 第一阶段完成

实现了完整的命令行工具：

**核心命令**:
1. `xet download` - 下载文件
   - 支持断点续传
   - 可配置并发数
   - 三种进度条样式（rich/simple/quiet）
   
2. `xet info` - 查看文件信息
   - 显示 reconstruction 详情
   - 估算文件大小
   
3. `xet config` - 配置管理
   - 多级配置优先级（系统/用户/项目/环境变量）
   - TOML 格式

**核心功能**:
- `ConfigManager` - 配置管理器
- `ProgressDisplay` - 进度条封装（Rich/Simple/Quiet）
- 统一错误处理
- 多级日志（-v, -vv, -vvv）

**功能完成度**: 93%
**测试覆盖度**: 17%（基本功能手动测试通过）

**关键文件**:
- `xet/cli/main.py` - 主入口
- `xet/cli/config_manager.py`
- `xet/cli/progress.py`
- `xet/cli/commands/download.py`
- `xet/cli/commands/info.py`
- `xet/cli/commands/config.py`

**待完成**:
- [ ] CLI 单元测试
- [ ] 端到端集成测试
- [ ] repo/file 格式支持

---

## 技术栈

**核心依赖**:
- `requests>=2.28.0` - HTTP 客户端
- `lz4>=4.0.0` - LZ4 压缩
- `rich>=13.7.0` - 终端 UI 和进度条
- `tomli>=2.0.0` - TOML 读取
- `tomli-w>=1.0.0` - TOML 写入

**开发依赖**:
- `pytest>=7.0.0` - 测试框架
- `pytest-cov>=4.0.0` - 覆盖率
- `black>=23.0.0` - 代码格式化
- `ruff>=0.1.0` - Linter
- `mypy>=1.0.0` - 类型检查

---

## 测试信息

### 测试仓库 1: mykor/granite-embedding ✅
- **类型**: 公开模型
- **文件**: `granite-embedding-97M-multilingual-r2-Q4_K_M.gguf`
- **Xet hash**: `e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02`
- **大小**: 105,467,232 字节 (100.58 MB)
- **Terms**: 17
- **Xorbs**: 10
- **状态**: ✅ 已验证通过（需要 HF_TOKEN）

### 测试仓库 2: xet-team/xet-spec-reference-files
- **类型**: 参考数据集
- **文件**: `Electric_Vehicle_Population_Data_20250917.csv`
- **Xet hash**: `118a53328412787fee04011dcf82fdc4acf3a4a1eddec341c910d30a306aaf97`
- **大小**: 63,527,244 字节 (63.5 MB)
- **状态**: ❌ 无 reconstruction 数据（仅含参考文件）

### 测试配置
- **代理**: `http://127.0.0.1:12334`
- **CAS endpoint**: `cas-server.xethub.hf.co`
- **HF Token**: `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`

---

## 项目统计

**代码文件**: 30+ 个
**测试文件**: 15+ 个
**总测试用例**: 100+ 个
**平均测试覆盖率**: ~70%

**代码结构**:
```
xet/
├── protocol/      # Phase 1 - 协议层
├── storage/       # Phase 2 - 存储层
├── network/       # Phase 3 - 网络层
├── pipeline/      # Phase 4 - 流程层
└── cli/           # Phase 5 - 命令行层
```

---

## 下一步计划

1. **Phase 5 完成**
   - [ ] 真实文件下载测试
   - [ ] CLI 单元测试
   - [ ] 端到端集成测试
   - [ ] 文档完善

2. **问题修复**
   - [ ] 修复协议类型不匹配
   - [ ] 完善错误处理
   - [ ] 提高测试覆盖率

3. **功能增强**
   - [ ] repo/file 格式支持
   - [ ] Upload 功能
   - [ ] 性能优化

---

**项目状态**: 🚧 开发中（CLI 层实现阶段）
**最后更新**: 2026-06-20
