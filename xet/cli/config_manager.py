"""配置管理模块。"""
import os
import tomli
import tomli_w
from pathlib import Path
from typing import Any, Optional


class ConfigManager:
    """统一配置管理器，按优先级加载配置。

    优先级（从高到低）：
    1. 环境变量
    2. 项目配置 (./.xet/config.toml)
    3. 用户配置 (~/.xetrc)
    4. 系统配置 (/etc/xet/config.toml)
    """

    def __init__(self):
        self.config = {}
        self._load_all_configs()

    def _load_all_configs(self):
        """按优先级加载所有配置。"""
        # 1. 系统配置（最低优先级）
        system_config = Path("/etc/xet/config.toml")
        if system_config.exists():
            self._merge_config(self._load_toml(system_config))

        # 2. 用户配置
        user_config = Path.home() / ".xetrc"
        if user_config.exists():
            self._merge_config(self._load_toml(user_config))

        # 3. 项目配置
        project_config = Path.cwd() / ".xet" / "config.toml"
        if project_config.exists():
            self._merge_config(self._load_toml(project_config))

        # 4. 环境变量（最高优先级）
        self._load_env_vars()

    def _load_toml(self, path: Path) -> dict:
        """加载 TOML 配置文件。"""
        try:
            with open(path, "rb") as f:
                return tomli.load(f)
        except Exception as e:
            print(f"Warning: 无法加载配置文件 {path}: {e}")
            return {}

    def _merge_config(self, new_config: dict):
        """合并配置（深度合并）。"""
        self._deep_merge(self.config, new_config)

    def _deep_merge(self, base: dict, updates: dict):
        """深度合并两个字典。"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _load_env_vars(self):
        """从环境变量加载配置。"""
        env_mapping = {
            "XET_ENDPOINT": ("xet", "endpoint"),
            "XET_TOKEN": ("xet", "token"),
            "XET_CONCURRENCY": ("download", "concurrency"),
            "XET_LOG_LEVEL": ("logging", "level"),
        }

        for env_var, path in env_mapping.items():
            value = os.environ.get(env_var)
            if value is not None:
                # 设置嵌套配置
                current = self.config
                for key in path[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]

                # 处理类型转换
                if env_var == "XET_CONCURRENCY":
                    value = int(value)

                current[path[-1]] = value

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值。

        支持点号分隔的嵌套键：
        - "xet.endpoint"
        - "download.concurrency"

        Args:
            key: 配置键（支持点号分隔）
            default: 默认值

        Returns:
            配置值，如果不存在返回 default
        """
        keys = key.split(".")
        current = self.config

        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return default

        return current

    def set(self, key: str, value: Any):
        """设置配置值（保存到用户配置）。

        Args:
            key: 配置键（支持点号分隔）
            value: 配置值
        """
        # 更新内存中的配置
        keys = key.split(".")
        current = self.config

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value

        # 保存到用户配置文件
        self._save_user_config()

    def _save_user_config(self):
        """保存配置到用户配置文件。"""
        user_config = Path.home() / ".xetrc"

        try:
            user_config.parent.mkdir(parents=True, exist_ok=True)
            with open(user_config, "wb") as f:
                tomli_w.dump(self.config, f)
        except Exception as e:
            print(f"Warning: 无法保存配置到 {user_config}: {e}")

    def list_all(self) -> dict:
        """列出所有配置。"""
        return self.config.copy()

    def get_endpoint(self) -> str:
        """获取 CAS endpoint（便捷方法）。"""
        return self.get("xet.endpoint", "https://cas.xethub.com")

    def get_token(self) -> Optional[str]:
        """获取认证 token（便捷方法）。"""
        return self.get("xet.token")

    def get_concurrency(self) -> int:
        """获取默认并发数（便捷方法）。"""
        return self.get("download.concurrency", 4)

    def get_log_level(self) -> str:
        """获取日志级别（便捷方法）。"""
        return self.get("logging.level", "INFO")
