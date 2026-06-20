# Protocol Layer

协议解析和数据结构（纯逻辑，无 I/O）。

## 模块

- `types.py` - 数据类定义
- `xorb_format.py` - Xorb 二进制格式解析
- `reconstruction.py` - Reconstruction 逻辑

## 设计原则

所有函数都是**纯函数**：
- 无副作用
- 相同输入总是产生相同输出
- 易于单元测试

## 示例

```python
from xet.protocol.xorb_format import deserialize_xorb_stream

# 纯函数调用
data, offsets = deserialize_xorb_stream(raw_bytes)

# 可以直接测试
assert len(data) == expected_length
assert offsets[0] == (0, 0)
```

## 下一步

Phase 1 任务：
1. 从旧版复制 `types.py`
2. 提取 `xorb_format.py` 纯函数
3. 编写单元测试（目标 100% 覆盖）
