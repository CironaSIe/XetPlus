# 贡献指南

感谢你对 XET Plus 的贡献！

## 开发流程

1. **Fork 项目** - 创建你自己的分支
2. **创建特性分支** - `git checkout -b feature/your-feature`
3. **编写代码** - 遵循下面的编码规范
4. **编写测试** - 确保覆盖率不降低
5. **运行测试** - `pytest tests/`
6. **提交代码** - 使用清晰的 commit message
7. **发起 PR** - 描述你的改动

## 编码规范

### Python 风格

- 遵循 PEP 8
- 使用 `black` 格式化代码
- 使用 `ruff` 检查代码质量
- 使用 `mypy` 检查类型

运行：
```bash
black xet/ tests/
ruff check xet/ tests/
mypy xet/
```

### 文档规范

所有函数必须有 docstring：

```python
def function_name(param: str) -> int:
    """函数简短描述。
    
    详细说明（可选）。
    
    Args:
        param: 参数说明
    
    Returns:
        返回值说明
    
    Raises:
        ValueError: 错误条件说明
    """
    pass
```

### 测试规范

- 每个函数都要有单元测试
- 测试文件命名: `test_<module>.py`
- 测试函数命名: `test_<function>_<scenario>()`
- 目标覆盖率: 80%+

示例：
```python
def test_deserialize_single_chunk():
    """测试单 chunk 反序列化。"""
    data = load_fixture('single_chunk.xorb')
    result, offsets = deserialize_xorb_stream(data)
    assert len(result) == 65536
    assert offsets == [(0, 0), (0, 65536)]
```

## Commit Message 规范

格式：`<type>: <subject>`

类型：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `test`: 测试相关
- `refactor`: 重构
- `style`: 格式调整
- `chore`: 构建/工具相关

示例：
```
feat: add xorb format parser
fix: handle truncated xorb header
docs: update protocol specification
test: add multipart merge tests
```

## 问题报告

使用 GitHub Issues，包含：
- 问题描述
- 复现步骤
- 期望行为
- 实际行为
- 环境信息（Python 版本、OS）

## 疑问？

查看 `docs/` 目录或在 Issues 中提问。
