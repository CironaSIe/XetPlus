# XET 文件检测修复与增强总结

## 📅 日期: 2026-06-21

---

## 🐛 原始问题

用户报告文件 `granite-embedding-97M-multilingual-r2-Q4_K_M.gguf` 被错误检测为"不是 XET 格式"，但该文件确实是有效的 XET 文件（已在 `~/xet.py/XET测试信息.md` 中确认）。

### 错误日志
```
WARNING: 文件不是 XET 格式: granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
✗ 文件不是 XET 格式: granite-embedding-97M-multilingual-r2-Q4_K_M.gguf
```

---

## 🔍 根本原因

`detect_xet_file()` 函数硬编码使用 `main` 分支：

```python
# 旧代码
file_url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
```

而实际文件在特定 commit 上：
```
commit: 45ce642d3fab2033d167ec09641a159010f7d9d9
```

当文件不在 `main` 分支或在特定 commit 上时，HEAD 请求会失败，导致误判为"不是 XET 格式"。

---

## ✅ 修复方案

### 1. 添加 `--revision` 参数

```python
parser.add_argument(
    "-r", "--revision",
    help="Git revision (分支名或 commit hash，默认: main)",
    default="main",
)
```

### 2. 更新 `detect_xet_file()` 函数

```python
def detect_xet_file(
    repo_id: str,
    repo_type: str,
    filename: str,
    token: str,
    session: requests.Session,
    revision: str = "main",  # 新增参数
) -> Optional[dict]:
    # 使用 revision 构造 URL
    file_url = f"https://huggingface.co/{repo_id}/resolve/{revision}/{filename}"
```

### 3. 更新所有调用点

```python
# 单文件下载
xet_info = detect_xet_file(repo_id, repo_type, filename, hf_token, session, revision=args.revision)

# 批量下载
xet_info = detect_xet_file(repo_id, repo_type, fname, hf_token, session, revision=args.revision)
```

---

## 🧪 测试验证

### 调试测试
```bash
$ python3 debug_xet_detection.py
✅ 状态码正确（重定向）: 302
✅ 有 X-Xet-Hash: e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02
✅ 有 xet-auth Link
✅ 这是一个有效的 XET 文件！
```

### 功能测试
```bash
$ python3 test_revision_fix.py
🧪 测试 1: 使用正确的 revision (commit hash)
✅ 检测成功！
   Xet Hash: e0aacd103e054264...
   Size: 105,467,232 bytes
   SHA256: 355f1f30ac3bdad0...
```

### 完整验证
```bash
$ python3 verify_revision_fix.py
1️⃣  测试模块导入...
   ✅ 模块导入成功

2️⃣  测试函数签名...
   参数列表: ['repo_id', 'repo_type', 'filename', 'token', 'session', 'revision']
   ✅ revision 参数存在
   默认值: main

3️⃣  测试实际调用...
   ✅ 检测成功
   Xet Hash: e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02
   Size: 105,467,232 bytes

🎉 所有测试通过！
```

---

## 📦 使用示例

### 使用 commit hash
```bash
xet download mykor/granite-embedding-97m-multilingual-r2-GGUF/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf \
  --revision 45ce642d3fab2033d167ec09641a159010f7d9d9
```

### 使用分支名
```bash
xet download user/repo/file.gguf --revision develop
```

### 使用默认 main（向后兼容）
```bash
xet download user/repo/file.gguf
```

---

## 🎯 成果

### 修复效果
- ✅ 文件正确识别为 XET 格式
- ✅ 支持任意 commit/branch 下载
- ✅ 向后兼容（默认 main 分支）
- ✅ 符合 git 工作流习惯
- ✅ **新增**: main 不存在时自动探测最新 commit

### 提交记录
- **Commit 1**: f3e5538 - 添加 --revision 参数支持
- **Commit 2**: e5da598 - 自动探测最新 commit（main 不存在时）
- **文档更新**: 16cdd63 (待修问题.md)

### 修改统计
- `xet/cli/commands/download.py`: +33 行新增, -3 行修改
- `待修问题.md`: +90 行文档

---

## 🚀 新增功能: 自动探测最新 commit

### 功能描述
当使用默认的 `main` 分支但该分支不存在时，自动调用 HuggingFace API 获取仓库的最新 commit，并使用该 commit 重试。

### 实现逻辑
```python
# 1. 首次尝试 main 分支
HEAD /resolve/main/file.gguf
→ 404 Not Found

# 2. 自动调用 API
GET /api/models/{repo_id}
→ {"sha": "abc123..."}

# 3. 使用最新 commit 重试
HEAD /resolve/abc123.../file.gguf
→ 302 Found (成功)
```

### 触发条件
- ✅ 仅当 `revision='main'` 时触发
- ✅ 仅当返回 404 时触发
- ❌ 用户明确指定的 revision 不会自动 fallback

### 使用场景
```bash
# 场景 1: 仓库使用 master 而非 main
xet download user/repo/file.gguf
# 自动检测到 main 不存在，使用最新 commit

# 场景 2: 仓库只有 develop 分支
xet download user/repo/file.gguf
# 自动使用最新 commit

# 场景 3: 用户明确指定 revision
xet download user/repo/file.gguf --revision develop
# 不会 fallback，尊重用户选择
```

### 测试验证
```bash
$ python3 test_fallback_simulation.py
📍 步骤 1: 尝试访问 main 分支 → 404
📍 步骤 2: 调用 API 获取最新 commit
📍 步骤 3: 使用最新 commit 重试
✅ 自动 fallback 成功！

HEAD 请求次数: 2
GET 请求次数: 1
```

---

## 📚 相关文档

- **问题跟踪**: `待修问题.md` - 问题 #12
- **测试脚本**: 
  - `debug_xet_detection.py` - HEAD 请求调试
  - `test_revision_fix.py` - 基础功能测试
  - `verify_revision_fix.py` - 完整验证
- **测试信息**: `~/xet.py/XET测试信息.md`

---

## 💡 技术要点

### HuggingFace XET 文件结构
```
HEAD https://huggingface.co/{repo}/{resolve}/{revision}/{file}
→ 302 重定向
→ 响应头包含:
  - X-Xet-Hash: XET 文件的哈希
  - Link: rel="xet-auth" (认证 URL)
  - X-Linked-Size: 原始文件大小
  - X-Linked-ETag: SHA256
```

### 关键修复点
1. URL 构造支持 revision 参数
2. 命令行参数传递链完整
3. 默认值保持向后兼容
4. 所有调用点统一更新

---

**修复者**: Claude & User  
**完成日期**: 2026-06-21  
**状态**: ✅ 完全修复并验证
