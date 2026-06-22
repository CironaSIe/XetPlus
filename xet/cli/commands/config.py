"""Config 命令实现。"""
import sys
from xet.cli.config_manager import ConfigManager, CONFIG_SCHEMA, CONFIG_SCHEMA


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
        "--list-all",
        help="列出所有可用配置项（包括未设置的）",
        action="store_true",
    )

    parser.add_argument(
        "--get",
        help="获取配置值",
        metavar="KEY",
    )

    parser.add_argument(
        "--unset",
        help="删除配置值",
        metavar="KEY",
    )

    parser.set_defaults(func=config_command)


def config_command(args):
    """执行 config 命令。"""
    try:
        config = ConfigManager()

        # 列出所有可用配置项（包括未设置的）
        if args.list_all:
            print("所有可用配置项：\n")
            print_config_schema(CONFIG_SCHEMA, config)
            return 0

        # 列出所有配置
        if args.list:
            all_config = config.list_all()
            if not all_config:
                print("无配置")
                print("\n💡 提示：使用 'xet config --list-all' 查看所有可用配置项")
                return 0

            print("当前配置：")
            print_config(all_config)
            print("\n💡 提示：使用 'xet config --list-all' 查看所有可用配置项")
            return 0

        # 获取配置
        if args.get:
            value = config.get(args.get)
            if value is None:
                print(f"✗ 配置不存在: {args.get}", file=sys.stderr)
                return 1
            print(value)
            return 0

        # 删除配置
        if args.unset:
            if config.unset(args.unset):
                print(f"✓ 已删除: {args.unset}")
                return 0
            else:
                print(f"✗ 配置不存在: {args.unset}", file=sys.stderr)
                return 1

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


def print_config_schema(schema: dict, config: ConfigManager):
    """打印配置项定义（带当前值）。"""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(show_header=True, header_style="bold cyan")

    table.add_column("配置项", style="cyan", no_wrap=True)
    table.add_column("说明", style="white")
    table.add_column("默认值", style="yellow")
    table.add_column("当前值", style="green")
    table.add_column("环境变量", style="dim")

    for key, info in sorted(schema.items()):
        description = info.get("description", "")
        default = info.get("default")
        env_var = info.get("env_var", "")

        # 获取当前值
        current = config.get(key)

        # 格式化显示
        default_str = str(default) if default is not None else "-"
        current_str = str(current) if current is not None else "-"

        # 如果当前值与默认值不同，高亮显示
        if current is not None and current != default:
            current_str = f"[bold green]{current_str}[/bold green]"

        table.add_row(
            key,
            description,
            default_str,
            current_str,
            env_var,
        )

    console.print(table)
    print("\n💡 用法：xet config <key> <value>")
    print("   示例：xet config xet.token hf_xxxxx")
    print("   查看：xet config --get <key>")
    print("   删除：xet config --unset <key>")

