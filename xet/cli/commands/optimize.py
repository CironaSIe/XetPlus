"""optimize 命令 - IP 优选与网络诊断。"""
import argparse
import logging
import sys
from typing import Optional

from xet.network.host_optimizer import HostOptimizer
from xet.cli.config_manager import ConfigManager

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

    parser.add_argument(
        "--verbose",
        help="详细模式（显示所有测试的 IP 及其状态）",
        action="store_true",
    )

    parser.add_argument(
        "--token",
        help="HF Token（用于 CAS 认证和真实带宽测速）",
    )

    parser.add_argument(
        "--file-hash",
        help="文件 MerkleHash（用于 CAS reconstruction 端点延迟测速）",
    )

    parser.add_argument(
        "--cas-endpoint",
        help="CAS 服务地址（默认 https://cas-server.xethub.hf.co）",
    )

    parser.add_argument(
        "--repo",
        help="HuggingFace 仓库 ID（用于自动获取 token 和 file_hash）",
    )

    parser.add_argument(
        "--commit",
        help="Git revision（分支名或 commit hash，默认 main）",
    )

    parser.add_argument(
        "--file",
        help="文件名（配合 --repo 使用，指定单个文件进行 warm-up）",
    )

    parser.add_argument(
        "--hf-endpoint",
        help="HuggingFace API 端点（如 https://hf-mirror.com，默认 huggingface.co）",
    )

    parser.set_defaults(func=optimize_command)


def optimize_command(args) -> int:
    """执行 optimize 命令。"""
    # 安静模式：抑制日志
    if args.quiet:
        logging.getLogger().setLevel(logging.CRITICAL)

    # 抑制本地代理的 HTTPS 警告（HTTP 代理做 CONNECT 隧道属于正常行为）
    if args.proxy:
        import urllib3
        import warnings
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 解析 DNS 服务器
    dns_servers = None
    if args.dns_servers:
        dns_servers = [s.strip() for s in args.dns_servers.split(",")]

    # ---- 自动获取 token 和 file_hash（如果提供了 --repo）----
    _access_token = None
    _file_hash = args.file_hash
    _cas_endpoint = args.cas_endpoint or "https://cas-server.xethub.hf.co"
    _hf_endpoint = getattr(args, 'hf_endpoint', None) or ConfigManager().get_hf_endpoint()

    if args.repo:
        from xet.cli.commands.download import (
            detect_xet_file, list_hf_files, match_files,
        )
        from xet.network.auth import XetAuth

        config = ConfigManager()
        hf_token = args.token or config.get_token()
        if not hf_token:
            print("✗ 缺少 HF Token，请用 --token 或设置 xet.token", file=sys.stderr)
            return 1

        # 创建基本 session 用于 API 调用（支持 --proxy）
        session = __import__("requests").Session()
        session.trust_env = False
        if args.proxy:
            session.proxies = {
                "http": args.proxy,
                "https": args.proxy,
            }

        # 检测文件获取 auth_url 和 xet_hash
        repo_id = args.repo
        repo_type = "model" if "/" not in args.repo or len(args.repo.split("/")) == 2 else "dataset"
        if "/" in args.repo and len(args.repo.split("/")) > 2:
            parts = args.repo.rsplit("/", 1)
            repo_id, filename = parts[0], parts[1]
        else:
            filename = None

        auth_url = None  # 先初始化

        try:
            if filename:
                if not args.quiet:
                    print(f"  📂 检测文件: {repo_id}/{filename}")
                xet_info = detect_xet_file(
                    repo_id, repo_type, filename,
                    hf_token, session, hf_endpoint=_hf_endpoint,
                )
                if xet_info:
                    _file_hash = xet_info.get("xet_hash") or _file_hash
                    auth_url = xet_info.get("auth_url")
                    if not args.quiet:
                        print(f"  ✅ 检测为 XET 文件 (hash={_file_hash[:16]}...)")
            else:
                # 列出文件，遍历找到第一个 xet 格式文件
                if not args.quiet:
                    print(f"  📂 枚举仓库文件: {repo_id} ...", end="", flush=True)
                all_files = list_hf_files(repo_id, repo_type, hf_token, session, hf_endpoint=_hf_endpoint)
                matched = match_files(all_files, "*")
                if not args.quiet:
                    print(f" {len(matched)} 个文件")

                if matched:
                    # 逐个尝试检测 xet 文件（优先选较大的/常见模型格式）
                    def _file_priority(f):
                        """排序优先级：大文件、模型格式优先。"""
                        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                        priority_exts = {"gguf": 0, "safetensors": 1, "bin": 2, "pt": 3}
                        return priority_exts.get(ext, 99)

                    sorted_matched = sorted(matched, key=_file_priority)
                    for candidate in sorted_matched:
                        if not args.quiet:
                            print(f"  🔍 检测: {candidate} ...", end="", flush=True)
                        xet_info = detect_xet_file(
                            repo_id, repo_type, candidate,
                            hf_token, session, hf_endpoint=_hf_endpoint,
                        )
                        if xet_info:
                            _file_hash = xet_info.get("xet_hash") or _file_hash
                            auth_url = xet_info.get("auth_url")
                            if not args.quiet:
                                print(f" ✅ XET 文件! (hash={_file_hash[:16]}...)")
                            logger.info(f"选中 xet 文件: {candidate} (hash={_file_hash[:16]}...)")
                            break
                        elif not args.quiet:
                            print(" 非 XET")
                    else:
                        if not args.quiet:
                            print("  ⚠ 未找到 XET 格式文件（将使用基础测速）")
                        logger.debug("仓库中未找到任何 xet 格式文件")

            # 获取 CAS token
            if auth_url:
                if not args.quiet:
                    print(f"  🔑 正在获取 CAS token ...", end="", flush=True)
                auth = XetAuth(hf_token=hf_token, session=session, hf_endpoint=_hf_endpoint)
                token_info = auth.get_token(repo_id=repo_id, repo_type=repo_type, auth_url=auth_url)
                _access_token = token_info.access_token
                _cas_endpoint = token_info.endpoint or _cas_endpoint
                if not args.quiet:
                    print(f" ✅ (endpoint={_cas_endpoint})")
        except Exception as e:
            print(f"⚠ 自动获取 token 失败: {e}（将使用基础测速）", file=sys.stderr)

    elif args.token and not _file_hash:
        # 有 token 但没 hash：仅传 token 做 DATA 测速（无 CAS 延迟测速）
        _access_token = args.token

    # 提取 warm-up 上下文
    _optimize_repo = args.repo if hasattr(args, 'repo') else None
    _optimize_commit = args.commit if hasattr(args, 'commit') else None
    _optimize_filename = getattr(args, 'file', None)  # --file 参数
    _optimize_hf_token = args.token or ConfigManager().get_token() if hasattr(args, 'token') else None

    # 创建优选器
    optimizer = HostOptimizer(
        proxy=args.proxy or "",
        dns_servers=dns_servers,
        access_token=_access_token,
        file_hash=_file_hash,
        cas_endpoint=_cas_endpoint,
        repo=_optimize_repo,
        commit=_optimize_commit,
        filename=_optimize_filename,
        hf_token=_optimize_hf_token,
    )
    optimizer.set_quiet(args.quiet)  # 安静模式：抑制实时测速输出

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
        _print_human_readable(
            mappings,
            optimizer.detailed_results,
            used_opt_cache,
            used_doh_cache,
            args.quiet,
            args.verbose,
        )

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
    detailed_results: dict,
    used_opt_cache: bool,
    used_doh_cache: bool,
    quiet: bool,
    verbose: bool,
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

            if not quiet:
                if speed > 0:
                    speed_str = _format_speed(speed)
                    print(f"  ✅ {domain:<30} → {ip:<15} {mode}  RTT={rtt*1000:>5.0f}ms  {speed_str:>10}")
                else:
                    print(f"  ✅ {domain:<30} → {ip:<15} {mode}  RTT={rtt*1000:>5.0f}ms")

                # 详细模式：显示所有候选 IP
                if verbose and domain in detailed_results:
                    candidates = detailed_results[domain]
                    if len(candidates) > 1:  # 有多个候选才显示
                        print(f"     所有候选 IP ({len(candidates)} 个):")
                        for candidate in candidates:
                            cand_ip = candidate["ip"]
                            cand_proxy = candidate["use_proxy"]
                            cand_rtt = candidate["rtt"]
                            cand_speed = candidate.get("speed", 0)
                            cand_status = candidate.get("status", "unknown")

                            # 状态图标
                            if cand_status == "ok":
                                status_icon = "✅"
                                status_text = "可用"
                            elif cand_status == "transfer_failed":
                                status_icon = "❌"
                                status_text = "TLS失败"
                            else:
                                status_icon = "❓"
                                status_text = cand_status

                            cand_mode = "代理" if cand_proxy else "直连"

                            # 标记当前选中的 IP
                            selected = "★" if cand_ip == ip else " "

                            if cand_speed > 0:
                                speed_str = _format_speed(cand_speed)
                                print(f"       {selected} {status_icon} {cand_ip:<15} {cand_mode:<4} RTT={cand_rtt*1000:>5.0f}ms {speed_str:>10} [{status_text}]")
                            else:
                                print(f"       {selected} {status_icon} {cand_ip:<15} {cand_mode:<4} RTT={cand_rtt*1000:>5.0f}ms             [{status_text}]")

        if not quiet:
            print()

    if not quiet:
        print("=" * 80)
        print()
        print("💡 提示:")
        print("  1. 使用 --hosts 输出 hosts 格式（适合写入 /etc/hosts）")
        print("  2. 使用 --refresh 强制重新测速（忽略缓存）")
        print("  3. 使用 --proxy 指定代理进行测速对比")
        if not verbose:
            print("  4. 使用 --verbose 查看所有候选 IP 的详细状态")
        print()


def _format_speed(bps: float) -> str:
    """格式化速度为人类可读格式。"""
    if bps >= 1024 * 1024:
        return f"{bps / (1024*1024):.1f}MB/s"
    elif bps >= 1024:
        return f"{bps / 1024:.1f}KB/s"
    else:
        return f"{bps:.0f}B/s"
