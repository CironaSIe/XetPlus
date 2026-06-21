"""ConfigManager 单元测试。"""
import pytest
import os
import tempfile
from pathlib import Path
from xet.cli.config_manager import ConfigManager


@pytest.fixture
def temp_config_dir(monkeypatch):
    """创建临时配置目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 设置临时 HOME 目录
        monkeypatch.setenv("HOME", tmpdir)
        # 设置临时工作目录
        temp_cwd = Path(tmpdir) / "project"
        temp_cwd.mkdir()
        monkeypatch.chdir(temp_cwd)
        yield tmpdir


@pytest.fixture
def clean_env(monkeypatch):
    """清理 XET 相关环境变量。"""
    env_vars = [
        "XET_ENDPOINT",
        "XET_TOKEN",
        "XET_CONCURRENCY",
        "XET_LOG_LEVEL",
        "XET_OPTIMIZE_HOSTS",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)


class TestConfigManager:
    """ConfigManager 测试套件。"""

    def test_empty_config(self, temp_config_dir, clean_env):
        """测试空配置（无配置文件）。"""
        cm = ConfigManager()

        # 默认值
        assert cm.get("xet.endpoint", "default") == "default"
        assert cm.get("nonexistent.key") is None
        assert cm.get("nonexistent.key", "default") == "default"

    def test_set_and_get(self, temp_config_dir, clean_env):
        """测试设置和获取配置。"""
        cm = ConfigManager()

        # 设置简单配置
        cm.set("xet.token", "test_token")
        assert cm.get("xet.token") == "test_token"

        # 设置嵌套配置
        cm.set("network.concurrency", 8)
        assert cm.get("network.concurrency") == 8

    def test_nested_key(self, temp_config_dir, clean_env):
        """测试嵌套键访问。"""
        cm = ConfigManager()

        cm.set("a.b.c", "deep_value")
        assert cm.get("a.b.c") == "deep_value"
        assert cm.get("a.b", {}).get("c") == "deep_value"

    def test_list_all(self, temp_config_dir, clean_env):
        """测试列出所有配置。"""
        cm = ConfigManager()

        cm.set("xet.token", "test")
        cm.set("network.concurrency", 8)

        all_config = cm.list_all()
        assert "xet" in all_config
        assert all_config["xet"]["token"] == "test"
        assert all_config["network"]["concurrency"] == 8

    def test_persistence(self, temp_config_dir, clean_env):
        """测试配置持久化。"""
        # 第一个实例：设置配置
        cm1 = ConfigManager()
        cm1.set("xet.token", "persistent_token")
        cm1.set("network.concurrency", 16)

        # 第二个实例：读取配置
        cm2 = ConfigManager()
        assert cm2.get("xet.token") == "persistent_token"
        assert cm2.get("network.concurrency") == 16

    def test_env_var_override(self, temp_config_dir, monkeypatch):
        """测试环境变量覆盖配置文件。"""
        # 设置配置文件
        cm1 = ConfigManager()
        cm1.set("xet.token", "file_token")

        # 设置环境变量
        monkeypatch.setenv("XET_TOKEN", "env_token")

        # 环境变量应该优先
        cm2 = ConfigManager()
        assert cm2.get("xet.token") == "env_token"

    def test_env_var_type_conversion(self, temp_config_dir, monkeypatch):
        """测试环境变量类型转换。"""
        monkeypatch.setenv("XET_CONCURRENCY", "32")
        monkeypatch.setenv("XET_OPTIMIZE_HOSTS", "true")

        cm = ConfigManager()

        # 整数转换
        assert cm.get("download.concurrency") == 32
        assert isinstance(cm.get("download.concurrency"), int)

        # 布尔转换
        assert cm.get("network.optimize_hosts") is True
        assert isinstance(cm.get("network.optimize_hosts"), bool)

    def test_env_var_bool_values(self, temp_config_dir, monkeypatch):
        """测试布尔值的多种表示。"""
        test_cases = [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ]

        for value, expected in test_cases:
            monkeypatch.setenv("XET_OPTIMIZE_HOSTS", value)
            cm = ConfigManager()
            assert cm.get("network.optimize_hosts") == expected, f"Failed for value: {value}"

    def test_convenience_methods(self, temp_config_dir, clean_env):
        """测试便捷方法。"""
        cm = ConfigManager()

        cm.set("xet.endpoint", "https://test.endpoint.com")
        cm.set("xet.token", "test_token")
        cm.set("download.concurrency", 8)
        cm.set("logging.level", "DEBUG")
        cm.set("network.optimize_hosts", True)

        assert cm.get_endpoint() == "https://test.endpoint.com"
        assert cm.get_token() == "test_token"
        assert cm.get_concurrency() == 8
        assert cm.get_log_level() == "DEBUG"
        assert cm.get_optimize_hosts() is True

    def test_convenience_methods_defaults(self, temp_config_dir, clean_env):
        """测试便捷方法的默认值。"""
        cm = ConfigManager()

        assert cm.get_endpoint() == "https://cas.xethub.com"
        assert cm.get_token() is None
        assert cm.get_concurrency() == 4
        assert cm.get_log_level() == "INFO"
        assert cm.get_optimize_hosts() is False

    def test_deep_merge(self, temp_config_dir, clean_env):
        """测试深度合并配置。"""
        cm = ConfigManager()

        # 设置第一层配置
        cm.set("network.concurrency", 8)
        cm.set("network.timeout", 30)

        # 设置第二层配置（应该保留第一层）
        cm.set("network.proxy", "http://proxy.com")

        assert cm.get("network.concurrency") == 8
        assert cm.get("network.timeout") == 30
        assert cm.get("network.proxy") == "http://proxy.com"

    def test_config_file_priority(self, temp_config_dir, clean_env, monkeypatch):
        """测试配置文件优先级。"""
        # 创建用户配置
        user_config = Path.home() / ".xetrc"
        user_config.write_text('[xet]\ntoken = "user_token"\nendpoint = "user_endpoint"\n')

        # 创建项目配置
        project_config = Path.cwd() / ".xet" / "config.toml"
        project_config.parent.mkdir(exist_ok=True)
        project_config.write_text('[xet]\ntoken = "project_token"\n')

        cm = ConfigManager()

        # 项目配置应该覆盖用户配置的 token
        assert cm.get("xet.token") == "project_token"

        # 用户配置的 endpoint 应该保留（项目配置没有覆盖）
        assert cm.get("xet.endpoint") == "user_endpoint"

    def test_nonexistent_nested_key(self, temp_config_dir, clean_env):
        """测试访问不存在的嵌套键。"""
        cm = ConfigManager()

        cm.set("xet.token", "test")

        # 访问不存在的嵌套路径
        assert cm.get("xet.nonexistent.key") is None
        assert cm.get("xet.nonexistent.key", "default") == "default"

    def test_overwrite_value(self, temp_config_dir, clean_env):
        """测试覆盖已有值。"""
        cm = ConfigManager()

        cm.set("xet.token", "old_token")
        assert cm.get("xet.token") == "old_token"

        cm.set("xet.token", "new_token")
        assert cm.get("xet.token") == "new_token"

    def test_config_isolation(self, temp_config_dir, clean_env):
        """测试配置实例隔离。"""
        cm1 = ConfigManager()
        cm1.set("xet.token", "token1")

        cm2 = ConfigManager()
        cm2.set("xet.token", "token2")

        # 两个实例最终都会反映最新的持久化配置
        assert cm1.get("xet.token") == "token1"  # cm1 的内存配置
        assert cm2.get("xet.token") == "token2"  # cm2 的内存配置

        # 重新加载应该得到最后保存的值
        cm3 = ConfigManager()
        assert cm3.get("xet.token") == "token2"

    def test_unset_simple_key(self, temp_config_dir, clean_env):
        """测试删除简单配置。"""
        cm = ConfigManager()

        # 设置配置
        cm.set("xet.token", "test_token")
        assert cm.get("xet.token") == "test_token"

        # 删除配置
        result = cm.unset("xet.token")
        assert result is True
        assert cm.get("xet.token") is None

    def test_unset_nested_key(self, temp_config_dir, clean_env):
        """测试删除嵌套配置。"""
        cm = ConfigManager()

        # 设置多个嵌套配置
        cm.set("network.concurrency", 8)
        cm.set("network.timeout", 30)
        cm.set("network.proxy", "http://proxy.com")

        # 删除其中一个
        result = cm.unset("network.timeout")
        assert result is True
        assert cm.get("network.timeout") is None

        # 其他配置应该保留
        assert cm.get("network.concurrency") == 8
        assert cm.get("network.proxy") == "http://proxy.com"

    def test_unset_nonexistent_key(self, temp_config_dir, clean_env):
        """测试删除不存在的配置。"""
        cm = ConfigManager()

        # 删除不存在的键应该返回 False
        result = cm.unset("nonexistent.key")
        assert result is False

    def test_unset_cleans_empty_dicts(self, temp_config_dir, clean_env):
        """测试删除配置时清理空字典。"""
        cm = ConfigManager()

        # 设置配置
        cm.set("network.timeout", 30)
        assert "network" in cm.list_all()

        # 删除唯一的配置项
        cm.unset("network.timeout")

        # 空的 network 字典应该被清理
        assert "network" not in cm.list_all()

    def test_unset_persistence(self, temp_config_dir, clean_env):
        """测试删除配置后的持久化。"""
        # 设置配置
        cm1 = ConfigManager()
        cm1.set("xet.token", "test_token")
        cm1.set("network.concurrency", 8)

        # 删除一个配置
        cm1.unset("xet.token")

        # 重新加载，验证删除已持久化
        cm2 = ConfigManager()
        assert cm2.get("xet.token") is None
        assert cm2.get("network.concurrency") == 8


class TestConfigManagerEdgeCases:
    """ConfigManager 边缘案例测试。"""

    def test_empty_key(self, temp_config_dir, clean_env):
        """测试空键。"""
        cm = ConfigManager()

        # 空字符串键的行为：split(".") 会得到 [""]，查找失败返回 None
        result = cm.get("")
        assert result is None  # 当前实现返回 None

        # 使用默认值
        result_with_default = cm.get("", default="default")
        assert result_with_default == "default"

    def test_special_characters_in_value(self, temp_config_dir, clean_env):
        """测试值中的特殊字符。"""
        cm = ConfigManager()

        special_values = [
            "http://proxy:8080",
            "token_with-dashes",
            "value with spaces",
            "unicode_中文_测试",
        ]

        for value in special_values:
            cm.set("test.key", value)
            assert cm.get("test.key") == value

    def test_numeric_string_values(self, temp_config_dir, clean_env):
        """测试数字字符串值（不应自动转换）。"""
        cm = ConfigManager()

        cm.set("test.port", "8080")  # 字符串，不是整数
        result = cm.get("test.port")

        assert result == "8080"
        assert isinstance(result, str)

    def test_none_value(self, temp_config_dir, clean_env):
        """测试 None 值。"""
        cm = ConfigManager()

        cm.set("test.none_value", None)
        assert cm.get("test.none_value") is None

        # None 和不存在的键应该有区别
        assert cm.get("test.none_value") is None
        assert cm.get("test.nonexistent") is None

        # 但通过 list_all 可以区分
        all_config = cm.list_all()
        assert "none_value" in all_config.get("test", {})
        assert "nonexistent" not in all_config.get("test", {})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
