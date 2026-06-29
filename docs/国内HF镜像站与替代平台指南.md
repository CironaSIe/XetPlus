# 国内 HF 镜像站与替代平台指南

**日期**: 2026-06-29  
**目的**: 整理国内可用的 HuggingFace 镜像站、独立替代平台及国际专业平台的现状和实际效果评测

---

## 已知问题：为什么镜像站体验不稳定

| 问题 | 原因 | 影响 |
|------|------|------|
| 文件报不存在 | 镜像站同步滞后，新/冷门模型未及时同步 | 热门模型正常，冷门模型可能缺失 |
| XET 文件卡死/失败 | 镜像站对 XET CAS 域名支持不完整 | 大文件下载中断 |
| 高峰期限速 | 社区公益项目带宽有限 | 下载速度下降 |

**关键解决方案**：使用镜像站时强制走 LFS bridge：

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1     # ← 跳过 XET，走 HTTP 路径
huggingface-cli download org/model --local-dir ./model
```

`HF_HUB_DISABLE_XET=1` 让 `huggingface_hub` 跳过 XET 协议，服务端重建文件后通过传统 HTTP 返回。镜像站对这种路径的缓存效果好得多。

---

## HF 镜像站（完整镜像 HF 内容）

### ✅ 可用

| 镜像站 | 类型 | 用法 | 现状 |
|--------|------|------|------|
| **hf-mirror.com** | 社区公益 | `HF_ENDPOINT=https://hf-mirror.com` | 主力，更新活跃，但高峰期负载高 |
| **hf-cdn.sufy.com** | 社区公益 | `HF_ENDPOINT=https://hf-cdn.sufy.com` | 备选，负载不明，用法同上 |

### ❌ 已下线

| 镜像站 | 说明 |
|--------|------|
| mirror.sjtu.edu.cn/huggingface | 404，已死 |
| 清华 HF 镜像 | 已关闭 |
| 其他高校镜像 | 全部不可用 |

---

## 国内独立平台（非镜像，独立托管模型库）

这些不是 HF 的镜像，而是独立的模型托管平台。国产模型（Qwen、DeepSeek、GLM、Yi 等）通常同时在 HF 和这些平台发布。

### ModelScope（modelscope.cn / 魔搭社区）

| 项目 | 说明 |
|------|------|
| **背景** | 阿里智能计算研究院，国内最成熟的 HF 对标平台 |
| **规模** | ~80k 模型，~15k 数据集 |
| **下载方式** | `pip install modelscope` → `snapshot_download("org/model")` |
| **校验** | 自动 SHA256，失败抛 `FileIntegrityError` |
| **网络** | 阿里云 OSS，国内速度最快 |
| **优点** | SDK 完善，有 Studio/Notebook/MaaS，国产模型最全 |
| **缺点** | 大文件网络不稳时"integrity check failed"常见（需重试），国际模型覆盖不如 HF |
| **推荐度** | ★★★★★ 首选 |

**注意**：ModelScope 的 SHA256 校验是硬性的——下载完成后必比对，不一致就报错。这比 HF + XET 的静默失败安全，但也意味着网络不好时重试次数会多。

**⚠️ 完整性保证的实际差距**：和 XET 一样，ModelScope 的校验也是**全量下载后才比对**——没有逐 chunk 校验，没有部分验证。大文件花了几个小时下到 99% 断了，或者 hash 不匹配，就得全量重新下。`modelscope_hub` 虽然支持 HTTP Range 分块下载和断点续传，但最终的 SHA256 校验是文件级的，修复粒度和 XET 完全一致。

### Gitee AI（ai.gitee.com / 模力方舟）

| 项目 | 说明 |
|------|------|
| **背景** | Gitee（码云，中国版 GitHub）旗下的 AI 平台 |
| **规模** | 增长中，模型数量中等 |
| **下载方式** | **HF 兼容模式**：`export HF_ENDPOINT=https://hf-api.gitee.com` |
| **校验** | 透传 huggingface_hub 的 ETag/SHA256 校验机制 |
| **网络** | 国内 CDN，下载速度快 |
| **优点** | **零迁移成本**——改一行环境变量就能用现有的 `huggingface_hub`/`transformers`/`diffusers` 代码；独立 cache 不冲突 |
| **缺点** | 不是完整 HF 镜像，部分冷门模型可能缺失；gated 模型需用 Gitee token 而非 HF token |
| **推荐度** | ★★★★☆ 最佳 HF 兼容方案 |

**Gitee AI 的独特价值**：它是唯一一个通过 `HF_ENDPOINT` 直接兼容 HF 工具链的国内平台。你不用学新 SDK、不用改代码，设个环境变量就能让 huggingface_hub 走 Gitee 的 CDN。对有现成 HF 工作流的用户来说迁移成本最低。

**⚠️ 完整性保证的实际差距**：Gitee AI 本质是 HF 代理，不提供独立的完整性保证。它继承 HF 的所有问题（包括 XET #3643 静默失败 bug），还要额外承担镜像同步偏差的风险——huggingface_hub 的 ETag/SHA256 比对可能因为 Gitee 和服务端元数据不一致而失败。`HF_HUB_DISABLE_XET=1` 在这里同样适用且同样重要。

### WiseModel（wisemodel.cn / 始智AI）

| 项目 | 说明 |
|------|------|
| **背景** | 始智AI，中立开放的模型生态平台 |
| **规模** | 较小（~800 模型），但增长中 |
| **下载方式** | Git-based / 网页直下 |
| **校验** | 平台级，Git 方式可用标准 Git 校验 |
| **网络** | 国内 CDN |
| **优点** | 中立平台，支持 MaaS/算力/容器；不少国产模型三站同发（HF/MS/WM） |
| **缺点** | 规模小，不如 ModelScope 和 Gitee AI 覆盖广 |
| **推荐度** | ★★★☆☆ 补充选择 |

### AIFastHub（aifasthub.com）

专注 HF 模型免费加速下载，非独立平台，透传 HF 内容。无独立校验机制。作为加速通道可用，但不适合作为主要依赖。

---

## 国内独立平台详细对比

| 维度 | ModelScope | Gitee AI | WiseModel |
|------|-----------|----------|-----------|
| 与 HF 兼容度 | 需 SDK | **`HF_ENDPOINT` 一行搞定** | 不兼容 |
| 下载校验 | 自动 SHA256，硬性校验 | 透传 huggingface_hub 机制 | Git/平台级 |
| 国产模型覆盖 | 最全 | 中等 | 较少 |
| 国际模型 | 部分同步 | 通过 HF 兼容模式能访问 | 有限 |
| 额外能力 | Studio/Notebook/MaaS | Git 代码托管/CI | MaaS/算力 |
| 企业背书 | 阿里 | 开源中国（OSChina） | 创业公司 |

---

## 国际专业平台（特定领域）

这些不是通用的 HF 替代品，但在各自领域有独特优势。

### Ollama（ollama.com）

| 项目 | 说明 |
|------|------|
| **定位** | 本地模型运行时 + 精选模型库 |
| **模型格式** | GGUF（量化模型为主） |
| **下载方式** | `ollama pull <model>` |
| **校验机制** | **OCI manifest + SHA256 blob 验证**——当前最强校验方案 |
| **优点** | 校验可靠（manifest 声明每层 SHA256，下载后强制比对）；content-addressed 存储（`~/.ollama/models/blobs/sha256-xxx`）；去重（共享层只存一份）；开箱即用的本地推理 |
| **缺点** | 模型库是平台精选的（非 HF 的全量镜像）；GGUF 格式依赖上游 quantize 版本；Ollama API 有历史 CVE（路径穿越等），需保持更新 |
| **适用人群** | 想直接跑模型不想折腾下载的用户 |

**⚠️ 完整性保证的实际差距**：Ollama 的 SHA256 blob 校验本身是可靠的，但 manifests 是信任链的脆弱环节。2024-2026 年已披露多个相关 CVE：
- **CVE-2024-37032 (Probllama)**：恶意 registry 通过 manifest digest 路径遍历实现 RCE
- **CVE-2025-51471**：恶意 registry 伪造 `WWW-Authenticate` 头窃取 Ed25519 认证令牌
- **CVE-2026-7482 (Bleeding Llama)**：恶意 GGUF 通过 inflate tensor 大小造成堆内存越界读取，泄露敏感数据
- **#13775 等**: Linux/AMD ROCm 上大 GGUF 文件的 false-positive digest mismatch，需手动清缓存

另外，Ollama 的校验是 blob 级（每 blob 是完整 GGUF 文件或 config），**不是子文件级**。和 XET 一样，一个 50GB 的 GGUF 就是单个 blob，损坏了得全量重下。

### Civitai（civitai.com）

| 项目 | 说明 |
|------|------|
| **定位** | 图像/视频生成模型社区（Stable Diffusion、Flux、LoRA） |
| **模型格式** | safetensors / ckpt |
| **下载方式** | `https://civitai.com/api/download/models/{versionId}` |
| **校验机制** | 每模型版本提供 **SHA256 + BLAKE3 + CRC32** 三种 hash；API 支持 hash lookup（`/api/v1/model-versions/by-hash/{hash}`） |
| **优点** | 多重 hash 验证；有 virusScan/pickleScan 结果；社区活跃，创作领域最全 |
| **缺点** | 仅限图像/视频生成模型；ckpt 格式的 pickle 安全风险历史 |
| **适用人群** | SD/Flux 用户 |

**⚠️ 完整性保证的实际差距**：2025 年是 Civitai 基础设施最差的一年——反复的 502/504 错误、Cloudflare 中断、2026 年初还有 LoRA 下载失败 bug（2026-02-13 修复）。hash 不匹配的常见原因：API 没传 token 导致拿到 placeholder 文件、CDN 中断导致截断、服务器端 hash 元数据错误。多重 hash 存在但需要用户自己去比对，平台不会自动校验。

### modelregistry.io

| 项目 | 说明 |
|------|------|
| **定位** | **BitTorrent P2P 模型分发** + HF web seed fallback |
| **状态** | WIP（2026-06 新发布） |
| **下载方式** | `.torrent` 文件 + P2P 客户端（qBittorrent 等） |
| **校验机制** | BitTorrent v1+v2 内置 hash（逐 piece 校验） |
| **优点** | P2P 分发减轻 HF 服务器压力；缺种时自动回退 HF web seed；理论上最快的下载方式（人越多越快） |
| **缺点** | WIP，模型数量有限；没有种子的模型速度可能不如直连；需要 BitTorrent 客户端 |
| **适合场景** | 热门大模型的批量分发 |

**BitTorrent v2 内置 Merkle tree 逐 piece 校验**——比 XET 还细，每个 piece（通常 512KB-1MB）都能独立验证完整性。而且下载的同时在上传，为社区做贡献。

### Replicate / Together AI

| 平台 | 定位 | 模型来源 |
|------|------|---------|
| **Replicate** | 推理 API 平台 | 从 HF/Civitai 导入，非独立模型库 |
| **Together AI** | 推理优化平台 | 同上，自有优化版本 |

这两个是推理服务平台，不是模型下载/分发平台。不适合作为模型文件获取来源，但适合想直接跑模型不想管部署的用户。

### Cloudsmith ML Registry

企业级私有模型 Registry，可代理/缓存 HF 模型，提供治理、访问控制、审计。适合企业使用但个人用户不适用。

---

## ⚠️ 完整性保证的现实真相

### 核心结论

**所有平台（XET、ModelScope、Ollama、Civitai、Gitee AI）声称的"文件完整性保证"，在校验粒度上没有任何本质区别——全都是文件级 SHA256。**

没有任何模型分发平台提供**子文件级别**（chunk/piece/block 级）的增量校验。这意味着：

- 大文件（>10GB）下到 99% 断了或 hash 不匹配 → 全量重下，没有"只重下坏的部分"
- 下载过程中无法判断某个 chunk 对不对 → 必须等到全部下完
- 服务端不暴露中间节点 hash → 没有二进制二分定位坏块的可能

这在技术原理上**和 XET 完全一致**。区别只在于失败行为：

| 平台 | 失败时 | 行为 |
|------|--------|------|
| **ModelScope** | 报错 `FileIntegrityError` | 用户知道坏了，但得全量重下 |
| **Ollama** | 报错 "digest mismatch" | 用户知道坏了，但得全量重下 |
| **HF XET** | #3643: 曾有静默成功 | 用户不知道坏了 |
| **Civitai** | 可能报错，可能直接拿到坏文件 | 用户可能不知道 |

### 唯一的例外：BitTorrent v2

```
BitTorrent v2: 16KB piece 级 Merkle 树
    ├── 下载中逐 piece 独立验证
    ├── 坏 piece 重下粒度 16KB（不是整个文件）
    ├── root hash 即信任锚点（不需要信 manifest server）
    └── modelregistry.io 是唯一尝试此方案的模型平台
```

### 更深层的问题：Trust 链上的脆弱环节

就算平台做了文件级 SHA256，这份信任最终落在：

| 依赖点 | 问题 |
|--------|------|
| **manifest / 元数据服务器** | 服务器说 hash 是 X，你没法独立验证 X（除非对比第二个来源）。Ollama 的 4 个 CVE 证明 manifest 本身可被篡改 |
| **config.json / tokenizer.json** | CVE-2026-4372：即使 `trust_remote_code=False`，恶意 `config.json` 也能 RCE |
| **模型格式本身** | safetensors 防不了此问题，因为攻击路径不走 weights 而走 metadata |
| **客户端实现** | HF #3643：客户端 bug 导致静默写坏数据不报错。Ollama #13775：false-positive digest mismatch 浪费带宽 |

### 实际意义

**你需要的不是"换一个平台"，而是理解所有平台的完整性保证都止步于文件级 SHA256。** 如果你：
- **能接受文件级校验**（下完算一次 hash） → 哪个平台都行，选网络最快的
- **想要子文件级校验** → 目前只有 modelregistry.io (BitTorrent v2) 或自己 split + per-chunk shasum

---

## 各平台校验机制综合对比

| 平台 | 声称的校验 | 实际校验粒度 | 子文件级？ | 已知问题 |
|------|-----------|------------|-----------|---------|
| **modelregistry.io** | BitTorrent Merkle | **piece 级 (16KB)** | ✅ 是 | WIP，模型太少 |
| **Ollama** | OCI manifest SHA256 | blob 级（每 blob 即完整文件） | ❌ 否 | 4 个 registry CVE；#13775 false-positive |
| **ModelScope** | 自动 SHA256 | 文件级 | ❌ 否 | 大文件 integrity check 频繁失败，需全量重下 |
| **Civitai** | SHA256/BLAKE3/CRC32 | 文件级（元数据字段） | ❌ 否 | 2025 基础设施崩塌；缺 API token 拿 placeholder |
| **HuggingFace XET** | Merkle 树 + SHA256 | 文件级（全量重建后） | ❌ 否 | #3643 静默写坏数据 |
| **Gitee AI** | 透传 huggingface_hub | 文件级（继承 HF） | ❌ 否 | 继承 HF bug；镜像同步偏差 |
| **HF 镜像站** | 透传 HF | 文件级（继承 HF） | ❌ 否 | XET 支持不完整 |
| **WiseModel** | 平台级 | — | ❌ 否 | 信息不透明 |

---

## 推荐策略

```
1. 在 ModelScope 搜索
   ├── 找到 → snapshot_download()，SHA256 自动校验
   └── 国内最快，校验硬性，失败必报

2. ModelScope 没有 → Gitee AI
   ├── export HF_ENDPOINT=https://hf-api.gitee.com
   ├── export HF_HUB_DISABLE_XET=1  （可选，建议加）
   └── 零迁移成本，继续用 huggingface-cli

3. 还是下不到 → hf-mirror.com + 禁用 XET
   ├── export HF_ENDPOINT=https://hf-mirror.com
   ├── export HF_HUB_DISABLE_XET=1
   └── huggingface-cli download ...

4. 热门大模型（>50GB）→ modelregistry.io
   ├── BitTorrent P2P，人越多越快
   └── piece 级校验，中断不浪费

5. 图像生成模型 → Civitai
   ├── 多重 hash + 安全扫描
   └── 图像/视频模型最全

6. 想直接跑不想管下载 → Ollama
   ├── manifest SHA256 最强校验
   └── ollama pull <model> 一步到位
```

---

## 为什么 `HF_HUB_DISABLE_XET=1` 是关键

XET 协议依赖 CAS 域名（`cas-bridge.xethub.hf.co`、`cas-server.xethub.hf.co`），镜像站和中国平台对这类域名的代理/缓存支持不完整。`HF_HUB_DISABLE_XET=1` 强制 huggingface_hub 退回到 LFS bridge——服务端把 XET 文件重建为完整文件后通过传统 HTTP 返回。

- 镜像站能缓存 HTTP 响应 → 加速效果好
- 不需要与 CAS 服务器交互 → 减少"文件不存在"错误
- 文件级 SHA256 验证仍然有效 → 安全性不变
- 在 Gitee AI 的 `hf-api.gitee.com` 上也适用

唯一的代价：失去了 XET 的 chunk 级去重和断点续传精细度。但对于"可靠下载"这个目标而言，这是可接受的取舍。

---

## 不推荐的下载方式

| 方式 | 问题 |
|------|------|
| 浏览器直接下载 HF 大文件 | 无断点续传，容易中断 |
| 直连 HF 不用代理不用镜像 | 国内大概率超时/被墙 |
| 镜像站 + 不开 DISABLE_XET | XET 文件可能卡死 |
| 依赖已死镜像（高校镜像） | 全部 404 |
