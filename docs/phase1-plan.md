# Phase 1 开发计划 - 协议层纯函数提取

## 目标

从旧版 `xet.py` 提取协议解析纯函数到 `xetplus/xet/protocol/`，并达到 100% 测试覆盖率。

---

## 任务清单

### Task 1.1: 复制数据结构（1 天）

**文件**: `xet/protocol/types.py`

**步骤**:
1. 从旧版复制 `types.py` 全部内容
2. 添加类型注解（使用 `from __future__ import annotations`）
3. 确保所有类有完整的 docstring

**验收标准**:
- [ ] 所有数据类可以正常 import
- [ ] `mypy` 类型检查通过
- [ ] Docstring 完整

**预计时间**: 2 小时

---

### Task 1.2: 提取 Xorb 格式解析（3 天）

**文件**: `xet/protocol/xorb_format.py`

#### Step 1: 提取纯函数（1 天）

从 `xet.py/xet/xorb_deserializer.py` 提取以下函数：

```python
def parse_xorb_header(data: bytes) -> dict:
    """解析 8 字节 xorb chunk header。"""
    pass

def decompress_chunk(payload: bytes, scheme: int) -> bytes:
    """解压 chunk payload（支持 LZ4/BG4）。"""
    pass

def deserialize_xorb_stream(
    data: bytes, 
    base_chunk_index: int = 0
) -> Tuple[bytes, List[Tuple[int, int]]]:
    """解析完整 xorb 数据流。"""
    pass

def merge_xorb_parts(
    parts: List[Tuple[int, bytes]]
) -> Tuple[bytes, List[Tuple[int, int]]]:
    """合并 multipart xorb 数据。"""
    pass
```

**改进点**:
- 所有函数无副作用（不读写文件、不修改全局状态）
- 参数和返回值类型完整
- 错误处理统一（抛出 `ValueError`）

#### Step 2: 编写单元测试（2 天）

**文件**: `tests/unit/test_xorb_format.py`

测试用例清单：

```python
# 基础功能测试
def test_parse_header_valid()
def test_parse_header_truncated()
def test_parse_header_invalid_version()

def test_decompress_none()
def test_decompress_lz4()
def test_decompress_bg4()
def test_decompress_unknown_scheme()

def test_deserialize_single_chunk()
def test_deserialize_multiple_chunks()
def test_deserialize_empty_data()

# 边界条件测试
def test_deserialize_truncated_header()
def test_deserialize_truncated_payload()
def test_deserialize_corrupted_chunk()
def test_deserialize_size_mismatch()

# Multipart 测试
def test_merge_xorb_parts_sequential()
def test_merge_xorb_parts_non_sequential()
def test_merge_xorb_parts_overlapping()

# 性能测试
def test_deserialize_large_xorb()  # 用 16MB 数据测试
```

**测试数据**:
- 从旧版项目复制真实的 xorb 样本到 `tests/fixtures/`
- 手工构造边界用例（truncated, corrupted）

**验收标准**:
- [ ] 所有测试通过
- [ ] 代码覆盖率 100%
- [ ] 性能测试通过（16MB 数据 <1s）

**预计时间**: 16 小时

---

### Task 1.3: 文档完善（1 天）

**文件**: 
- `xet/protocol/README.md` - 模块说明
- `docs/protocol-spec.md` - 协议规范（从旧版迁移）

**内容**:
1. 模块使用示例
2. 函数 API 文档（自动生成）
3. Xorb 格式规范（图示）
4. 常见问题 FAQ

**验收标准**:
- [ ] README 完整
- [ ] 所有函数有示例代码
- [ ] 协议规范清晰

**预计时间**: 4 小时

---

## 时间估算

| 任务 | 预计时间 |
|------|---------|
| Task 1.1 | 2 小时 |
| Task 1.2 Step 1 | 8 小时 |
| Task 1.2 Step 2 | 16 小时 |
| Task 1.3 | 4 小时 |
| **总计** | **30 小时** |

按每天工作 6 小时计算 = **5 个工作日**

---

## 验收标准（Phase 1 完成）

- [ ] `xet/protocol/types.py` 完成，类型检查通过
- [ ] `xet/protocol/xorb_format.py` 完成，所有函数纯函数化
- [ ] `tests/unit/test_xorb_format.py` 完成，覆盖率 100%
- [ ] 所有测试通过（`pytest` 无失败）
- [ ] 文档完整（README + 协议规范）
- [ ] 代码格式化（`black` + `ruff`）
- [ ] 类型检查通过（`mypy`）

---

## 下一步（Phase 2）

完成 Phase 1 后，开始 Storage Layer 开发：
- `storage/writer.py` - 统一写入接口
- `storage/checkpoint.py` - 断点管理

---

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 旧版代码理解偏差 | 中 | 高 | 对比 Rust 代码，调试验证 |
| 测试数据不足 | 低 | 中 | 从生产日志提取真实 xorb |
| 性能不如旧版 | 低 | 中 | Profile 对比，必要时优化 |

---

## 开始时间

**立即开始** Task 1.1 - 复制数据结构

命令：
```bash
cd ~/xetplus
# 复制 types.py
cp ~/xet.py/xet/types.py xet/protocol/types.py
# 开始修改...
```
