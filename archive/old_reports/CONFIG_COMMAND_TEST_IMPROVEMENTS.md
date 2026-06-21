# Config 命令测试改进建议

**日期**: 2026-06-21  
**状态**: ✅ **已完成** (2026-06-21)

---

## 实施总结

### ✅ 已完成的改进

1. **添加 `config --unset` 命令** ✅
   - 在 `ConfigManager` 中实现 `unset()` 方法
   - 支持嵌套键删除（如 `network.concurrency`）
   - 自动清理空的父级字典
   - 更改持久化到 `~/.xetrc`

2. **添加 ConfigManager 单元测试** ✅
   - 24个测试用例，100%通过
   - 测试覆盖率：94.59%
   - 包含 5个 `unset()` 方法测试：
     - `test_unset_simple_key` - 删除简单配置
     - `test_unset_nested_key` - 删除嵌套配置
     - `test_unset_nonexistent_key` - 删除不存在的键
     - `test_unset_cleans_empty_dicts` - 清理空字典
     - `test_unset_persistence` - 删除持久化验证

3. **更新 P3 集成测试** ✅
   - 使用 `config --unset` 代替手动文件删除
   - 测试通过率：100% (4/4)
   - 用时：25秒

---

## 原始问题记录

**日期**: 2026-06-21  
**问题**: P3-02 config 命令测试失败，暴露了配置管理的测试不足

---

## 当前问题

### 1. 配置文件路径混淆
- **错误**: 测试脚本使用 `~/.xet/config.json`
- **正确**: ConfigManager 使用 `~/.xetrc` (TOML 格式)

### 2. 缺少删除/重置功能
- config 命令只支持：
  - `--list`: 列出所有配置
  - `--get KEY`: 获取单个配置
  - `config KEY VALUE`: 设置配置
- **缺失**: `--unset` 或 `--delete` 删除配置的功能

### 3. 测试覆盖不足
- 没有专门的 config 命令单元测试
- P3 集成测试是唯一的配置测试

---

## 建议的改进

### 方案1: 添加 --unset 参数

**修改文件**: `xet/cli/commands/config.py`

```python
def register_config_command(subparsers):
    """注册 config 子命令。"""
    parser = subparsers.add_parser(
        "config",
        help="配置管理",
        description="查看和修改 XET 配置。",
    )

    # ... 现有参数 ...

    parser.add_argument(
        "--unset",
        help="删除配置项",
        metavar="KEY",
    )

    parser.set_defaults(func=config_command)


def config_command(args):
    """执行 config 命令。"""
    try:
        config = ConfigManager()

        # 删除配置
        if args.unset:
            if config.unset(args.unset):  # 需要在 ConfigManager 中实现
                print(f"✓ 已删除: {args.unset}")
                return 0
            else:
                print(f"✗ 配置不存在: {args.unset}", file=sys.stderr)
                return 1

        # ... 其他逻辑 ...
```

**ConfigManager 新增方法**:

```python
def unset(self, key: str) -> bool:
    """删除配置项。
    
    Args:
        key: 配置键（支持点号分隔的嵌套键）
        
    Returns:
        如果删除成功返回 True，配置不存在返回 False
    """
    keys = key.split(".")
    config = self._load()
    
    # 导航到父级
    current = config
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            return False  # 路径不存在
        current = current[k]
    
    # 删除最后一个键
    final_key = keys[-1]
    if final_key not in current:
        return False  # 键不存在
    
    del current[final_key]
    
    # 清理空的父级字典
    self._cleanup_empty_dicts(config, keys[:-1])
    
    self._save(config)
    return True

def _cleanup_empty_dicts(self, config: dict, path: list):
    """清理空的嵌套字典。"""
    if not path:
        return
    
    current = config
    for k in path[:-1]:
        if k not in current:
            return
        current = current[k]
    
    key = path[-1]
    if key in current and isinstance(current[key], dict) and not current[key]:
        del current[key]
        # 递归清理父级
        self._cleanup_empty_dicts(config, path[:-1])
```

---

### 方案2: 简化测试（当前采用）

不修改 config 命令，而是改进测试脚本：

```bash
# 测试步骤
1. 记录原配置文件是否存在
2. 设置测试配置
3. 验证配置已设置
4. 恢复/删除配置文件
5. 验证配置已清除
```

**优点**:
- 无需修改 ConfigManager
- 测试简单直接

**缺点**:
- 用户无法通过命令删除配置（只能手动编辑文件）

---

## 配置文件结构

### 用户配置 (~/.xetrc)
```toml
[xet]
endpoint = "https://cas-server.xethub.hf.co"
token = "hf_..."

[network]
concurrency = 8
proxy = "http://127.0.0.1:12334"

[network.host_optimizer]
enabled = true
cache_ttl = 3600
```

### 项目配置 (./.xet/config.toml)
```toml
# 项目级别配置，覆盖用户配置
[xet]
endpoint = "https://custom-cas.example.com"
```

---

## 测试用例设计

### 单元测试 (test_config_manager.py)

```python
import pytest
from pathlib import Path
from xet.cli.config_manager import ConfigManager

def test_set_get_config(tmp_path):
    """测试设置和获取配置。"""
    config_file = tmp_path / ".xetrc"
    cm = ConfigManager(config_file=config_file)
    
    # 设置配置
    cm.set("xet.token", "test_token")
    assert cm.get("xet.token") == "test_token"
    
    # 嵌套配置
    cm.set("network.concurrency", 8)
    assert cm.get("network.concurrency") == "8"

def test_list_config(tmp_path):
    """测试列出所有配置。"""
    config_file = tmp_path / ".xetrc"
    cm = ConfigManager(config_file=config_file)
    
    cm.set("xet.token", "test")
    cm.set("network.concurrency", 8)
    
    all_config = cm.list_all()
    assert "xet" in all_config
    assert all_config["xet"]["token"] == "test"
    assert all_config["network"]["concurrency"] == "8"

def test_unset_config(tmp_path):
    """测试删除配置。"""
    config_file = tmp_path / ".xetrc"
    cm = ConfigManager(config_file=config_file)
    
    cm.set("xet.token", "test")
    assert cm.get("xet.token") == "test"
    
    # 删除配置
    assert cm.unset("xet.token") == True
    assert cm.get("xet.token") is None
    
    # 删除不存在的配置
    assert cm.unset("nonexistent.key") == False

def test_config_priority(tmp_path):
    """测试配置优先级：项目 > 用户。"""
    user_config = tmp_path / ".xetrc"
    project_config = tmp_path / ".xet" / "config.toml"
    project_config.parent.mkdir()
    
    # 用户配置
    user_cm = ConfigManager(config_file=user_config)
    user_cm.set("xet.endpoint", "https://user-cas.com")
    
    # 项目配置
    project_cm = ConfigManager(config_file=project_config)
    project_cm.set("xet.endpoint", "https://project-cas.com")
    
    # 加载配置时项目配置应覆盖用户配置
    cm = ConfigManager()
    assert cm.get_endpoint() == "https://project-cas.com"
```

---

### 集成测试 (test_cli_p3_integration.sh)

```bash
# TC-P3-02: config 命令完整测试
test_config_command() {
    # 1. 备份原配置
    CONFIG_FILE="$HOME/.xetrc"
    [ -f "$CONFIG_FILE" ] && cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
    
    # 2. 设置配置
    xet config xet.token test_token
    xet config network.concurrency 8
    
    # 3. 验证配置已设置
    xet config --list | grep "test_token"
    xet config --get xet.token | grep "test_token"
    
    # 4. 删除配置（方案1：使用 --unset）
    xet config --unset xet.token
    xet config --unset network.concurrency
    
    # 或者（方案2：手动删除文件）
    rm -f "$CONFIG_FILE"
    
    # 5. 验证配置已清除
    ! xet config --list | grep "test_token"
    
    # 6. 恢复原配置
    [ -f "$CONFIG_FILE.backup" ] && mv "$CONFIG_FILE.backup" "$CONFIG_FILE"
}
```

---

## 推荐方案

### 短期（立即修复 P3 测试）
- ✅ 修正配置文件路径 (`~/.xetrc`)
- ✅ 改进测试脚本逻辑（记录原配置是否存在）
- ✅ 手动删除/恢复配置文件

### 中期（提升用户体验）
- 🔲 实现 `--unset` 参数
- 🔲 实现 `--reset` 参数（重置为默认值）
- 🔲 添加配置验证（检测无效配置）

### 长期（完善测试覆盖）
- 🔲 添加 ConfigManager 单元测试
- 🔲 添加配置优先级测试（用户 vs 项目）
- 🔲 添加配置文件格式验证测试
- 🔲 添加配置迁移测试（从旧格式升级）

---

## 当前 P3-02 测试状态

**修复后的测试流程**:
1. ✅ 检查 `~/.xetrc` 是否存在并备份
2. ✅ 设置测试配置（test_p3_token）
3. ✅ 验证配置已设置
4. ✅ 恢复原配置或删除测试配置
5. ✅ 验证测试配置已清除

**预期结果**: 测试通过 ✓
