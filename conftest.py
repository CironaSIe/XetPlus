"""
pytest 配置文件

配置项：
- 测试目录结构
- 标记（markers）定义
- fixture 配置
- 日志配置
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """pytest 配置钩子"""
    # 注册自定义标记
    config.addinivalue_line(
        "markers", "integration: 标记集成测试（需要真实环境）"
    )
    config.addinivalue_line(
        "markers", "unit: 标记单元测试（独立运行，无外部依赖）"
    )
    config.addinivalue_line(
        "markers", "slow: 标记慢速测试（运行时间 > 1 秒）"
    )
    config.addinivalue_line(
        "markers", "network: 标记需要网络连接的测试"
    )
