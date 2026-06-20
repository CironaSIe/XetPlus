"""Config 命令实现。"""
import sys
from xet.cli.config_manager import ConfigManager


def register_config_command(subparsers):
    """注册 config 子命令。"""
    parser = subparsers.add_parser(
        "config",
        help="配置管理",
        description="查看和修改 XET 配置。",
    )

    parser.add_argument(
        "key",
        nargs="?",
        help="配置键（如 xet.endpoint）",
    )

    parser.add_argument(
        "value",
        nargs="?",
        help="配置值",
    )

    parser.add_argument(
        "--list",
        help="列出所有配置",
        action="store_true",
    )

    parser.add_argument(
        "--get",
        help="获取配置值",
        metavar="KEY",
    )

    parser.set_defaults(func=config_command)


def config_command(args):
    """执行 config 命令。"""
    try:
        config = ConfigManager()

        # 列出所有配置
        if args.list:
            all_config = config.list_all()
            if not all_config:
                print("无配置")
                return 0

            print("当前配置：")
            print_config(all_config)
            return 0

        # 获取配置
        if args.get:
            value = config.get(args.get)
            if value is None:
                print(f"✗ 配置不存在: {args.get}", file=sys.stderr)
                return 1
            print(value)
            return 0

        # 设置配置
        if args.key and args.value:
            config.set(args.key, args.value)
            print(f"✓ 已设置: {args.key} = {args.value}")
            return 0

        # 获取单个配置
        if args.key:
            value = config.get(args.key)
            if value is None:
                print(f"✗ 配置不存在: {args.key}", file=sys.stderr)
                return 1
            print(f"{args.key} = {value}")
            return 0

        # 没有参数，列出所有配置
        all_config = config.list_all()
        if not all_config:
            print("无配置")
            return 0

        print("当前配置：")
        print_config(all_config)
        return 0

    except Exception as e:
        print(f"✗ 配置操作失败: {e}", file=sys.stderr)
        return 1


def print_config(config: dict, indent: int = 0):
    """递归打印配置。"""
    for key, value in sorted(config.items()):
        if isinstance(value, dict):
            print("  " * indent + f"{key}:")
            print_config(value, indent + 1)
        else:
            print("  " * indent + f"{key} = {value}")
