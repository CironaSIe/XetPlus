"""XET 命令行工具主入口。"""
import sys
import logging
import argparse
from pathlib import Path

from xet.cli.commands import (
    register_download_command,
    register_info_command,
    register_config_command,
)


def setup_logging(verbose: int = 0):
    """配置日志系统。

    Args:
        verbose: 详细级别
            0 = WARNING
            1 = INFO
            2 = DEBUG
    """
    if verbose == 0:
        level = logging.WARNING
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s")
    )

    # 配置根 logger
    logging.basicConfig(
        level=level,
        handlers=[console_handler],
    )


def main():
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="xet",
        description="XetHub 文件管理工具",
        epilog="使用 'xet <command> --help' 查看命令帮助",
    )

    parser.add_argument(
        "-v", "--verbose",
        help="详细输出（可多次使用：-v, -vv, -vvv）",
        action="count",
        default=0,
    )

    parser.add_argument(
        "--version",
        help="显示版本信息",
        action="version",
        version="xet 0.1.0 (Phase 5 MVP)",
    )

    # 子命令
    subparsers = parser.add_subparsers(
        dest="command",
        help="可用命令",
        required=True,
    )

    # 注册子命令
    register_download_command(subparsers)
    register_info_command(subparsers)
    register_config_command(subparsers)

    # 解析参数
    args = parser.parse_args()

    # 设置日志
    setup_logging(args.verbose)

    # 执行命令
    try:
        exit_code = args.func(args)
        sys.exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\n⚠ 用户中断", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"✗ 未知错误: {e}", file=sys.stderr)
        if args.verbose >= 2:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
