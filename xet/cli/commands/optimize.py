"""optimize 命令 - IP 优选与网络诊断。"""
import argparse
import logging
import sys
from typing import Optional

from xet.network.host_optimizer import HostOptimizer

logger = logging.getLogger(__name__)


def register_optimize_command(subparsers):
    """注册 optimize 子命令。"""
    parser = subparsers.add_parser(
        "optimize",
        help="IP 优选: DoH 查询 + 测速，输出 hosts 格式",
        description="执行 HOST 优选，通过 DoH 查询和测速选择最优 IP，可输出 hosts 格式用于加速访问。",
    )

    parser.add_argument(
        "--refresh",
        help="强制刷新优选结果（重新测速）",
        action="store_true",
    )

    parser.add_argument(
        "--refresh-doh",
        help="仅强制刷新 DoH 缓存（重新查询 IP）",
        action="store_true",
    )

    parser.add_argument(
        "--proxy",
        help="HTTP/HTTPS 代理地址（如 http://127.0.0.1:7890）",
    )

    parser.add_argument(
        "--dns-servers",
        help="自定义 DoH 服务器列表（逗号分隔）",
    )

    parser.add_argument(
        "--hosts",
        help="输出 hosts 格式（适合写入 /etc/hosts）",
        action="store_true",
    )

    parser.add_argument(
        "--quiet",
        help="安静模式（仅输出 hosts 格式，无日志）",
        action="store_true",
    )

    parser.set_defaults(func=optimize_command)


def optimize_command(args) -> int:
    """执行 optimize 命令。"""
    # 安静模式：抑制日志
    if args.quiet:
        logging.getLogger().setLevel(logging.CRITICAL)

    # 解析 DNS 服务器
    dns_servers = None
    if args.dns_servers:
        dns_servers = [s.strip() for s in args.dns_servers.split(",")]

    # 创建优选器
    optimizer = HostOptimizer(
        proxy=args.proxy or "",
        dns_servers=dns_servers,
    )

    # 执行优选
    try:
        mappings, used_opt_cache, used_doh_cache = optimizer.optimize(
            force_refresh=args.refresh,
            force_doh=args.refresh_doh,
        )
    except Exception as e:
        logger.error(f"HOST 优选失败: {e}")
        return 1

    if not mappings:
        if not args.quiet:
            print("⚠️  HOST 优选无结果（DoH 查询或测速失败）", file=sys.stderr)
        return 1

    # 输出结果
    if args.hosts:
        # hosts 格式输出
        _print_hosts_format(mappings)
    else:
        # 人类可读格式
        _print_human_readable(mappings, used_opt_cache, used_doh_cache, args.quiet)

    return 0


def _print_hosts_format(mappings: dict) -> None:
    """输出 hosts 格式。"""
    print("# XET+ HOST 优选结果")
    print("# 生成时间:", end=" ")
    import datetime
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()

    for domain, info in sorted(mappings.items()):
        ip = info["ip"]
        print(f"{ip:<15} {domain}")


def _print_human_readable(
    mappings: dict,
    used_opt_cache: bool,
    used_doh_cache: bool,
    quiet: bool,
) -> None:
    """输出人类可读格式。"""
    if not quiet:
        print()
        print("=" * 80)
        print(f"{'HOST 优选结果':^80}")
        print("=" * 80)
        print()

        # 缓存状态
        if used_opt_cache:
            print("📦 使用优选缓存（1小时有效）")
        elif used_doh_cache:
            print("📦 使用 DoH 缓存（24小时有效）")
        else:
            print("🔍 执行完整优选（DoH 查询 + 测速）")
        print()

    # 按组分类显示
    from xet.network.host_optimizer import HOST_GROUPS

    for group_name, domains in HOST_GROUPS.items():
        group_has_result = any(d in mappings for d in domains)
        if not group_has_result:
            continue

        if not quiet:
            print(f"【{group_name.upper()}】")

        for domain in domains:
            if domain not in mappings:
                continue

            info = mappings[domain]
            ip = info["ip"]
            rtt = info["rtt"]
            speed = info.get("speed", 0)
            use_proxy = info["use_proxy"]

            mode = "🔒 代理" if use_proxy else "🚀 直连"

            if speed > 0:
                speed_str = _format_speed(speed)
                if not quiet:
                    print(f"  {domain:<30} → {ip:<15} {mode}  RTT={rtt*1000:>5.0f}ms  {speed_str:>10}")
            else:
                if not quiet:
                    print(f"  {domain:<30} → {ip:<15} {mode}  RTT={rtt*1000:>5.0f}ms")

        if not quiet:
            print()

    if not quiet:
        print("=" * 80)
        print()
        print("💡 提示:")
        print("  1. 使用 --hosts 输出 hosts 格式（适合写入 /etc/hosts）")
        print("  2. 使用 --refresh 强制重新测速（忽略缓存）")
        print("  3. 使用 --proxy 指定代理进行测速对比")
        print()


def _format_speed(bps: float) -> str:
    """格式化速度为人类可读格式。"""
    if bps >= 1024 * 1024:
        return f"{bps / (1024*1024):.1f}MB/s"
    elif bps >= 1024:
        return f"{bps / 1024:.1f}KB/s"
    else:
        return f"{bps:.0f}B/s"
