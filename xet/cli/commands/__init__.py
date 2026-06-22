"""XET CLI 子命令模块。"""
from xet.cli.commands.download import register_download_command
from xet.cli.commands.info import register_info_command
from xet.cli.commands.config import register_config_command
from xet.cli.commands.optimize import register_optimize_command

__all__ = [
    "register_download_command",
    "register_info_command",
    "register_config_command",
    "register_optimize_command",
]
