"""Info 命令实现 - 改进版。

支持:
1. user/repo/file 格式（显示详细信息）
2. user/repo + --include 批量查看
3. file_hash 直接查询
"""
import sys
import os
import re
import fnmatch
import logging
import requests
from typing import Optional, List

from xet.network.cas_client import CASClient
from xet.cli.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def register_info_command(subparsers):
    """注册 info 子命令。"""
    parser = subparsers.add_parser(
        "info",
        help="查看文件信息",
        description="显示 XET 文件的详细元数据和 reconstruction 信息。",
    )

    parser.add_argument(
        "path",
        help="文件路径（格式: user/repo/file.gguf, user/repo 或 file_hash）",
    )

    parser.add_argument(
        "-i", "--include",
        help="批量匹配 glob pattern（如 *.gguf）",
    )

    parser.add_argument(
        "--hf-endpoint",
        help="HuggingFace 端点（默认: https://huggingface.co）。"
             "示例: https://hf-mirror.com",
    )

    parser.add_argument(
        "--endpoint",
        help="CAS 服务器地址（覆盖配置）",
    )

    parser.add_argument(
        "--token",
        help="认证 Token（覆盖配置）",
    )

    parser.add_argument(
        "--proxy",
        help="HTTP/HTTPS 代理地址",
    )

    parser.set_defaults(func=info_command)


def parse_file_spec(path: str):
    """解析文件路径。

    Returns:
        (repo_id, filename, file_hash, repo_type)
    """
    # 检查是否是 64 字符的 hash
    if len(path) == 64 and all(c in "0123456789abcdef" for c in path.lower()):
        return None, None, path, "model"

    # 否则解析为 repo/file
    if "/" not in path:
        raise ValueError(f"无效的文件路径格式: {path}。期望 'user/repo/file' 或 64 字符 hash")

    parts = path.split("/")

    # 检查是否以 datasets/ 开头
    repo_type = "model"
    if parts[0] == "datasets":
        repo_type = "dataset"
        parts = parts[1:]  # 移除 datasets/ 前缀

    # user/repo/file
    if len(parts) >= 3:
        filename = parts[-1]
        repo_id = "/".join(parts[:-1])
        return repo_id, filename, None, repo_type

    # user/repo
    elif len(parts) == 2:
        repo_id = "/".join(parts)
        return repo_id, None, None, repo_type

    else:
        raise ValueError(f"无效的文件路径格式: {path}")


def list_hf_files(repo_id: str, repo_type: str, token: str, session: requests.Session, hf_endpoint: str = "https://huggingface.co"):
    """列出 HuggingFace 仓库文件（返回完整元数据）。

    Args:
        repo_id: 仓库 ID
        repo_type: 仓库类型
        token: HF token
        session: requests session
        hf_endpoint: HF 端点 URL

    Returns:
        (files, repo_metadata) 其中 files 是文件列表，repo_metadata 是仓库元数据
    """
    # 根据 repo_type 构造 API URL
    if repo_type == "dataset":
        url = f"{hf_endpoint}/api/datasets/{repo_id}"
    else:
        url = f"{hf_endpoint}/api/models/{repo_id}"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # 提取文件信息（包含大小）
        files = []
        for sibling in data.get("siblings", []):
            rpath = sibling.get("rfilename", "")
            if rpath:
                files.append({
                    "filename": rpath,
                    "size": sibling.get("size", 0),  # 文件大小（字节）
                })

        # 提取仓库元数据
        repo_metadata = {
            "id": data.get("id", repo_id),
            "author": data.get("author"),
            "pipeline_tag": data.get("pipeline_tag"),  # 任务类型
            "tags": data.get("tags", []),
            "downloads": data.get("downloads", 0),
            "likes": data.get("likes", 0),
            "created_at": data.get("createdAt"),
            "last_modified": data.get("lastModified"),
            # 衍生关系
            "base_model": None,
            "derived_from": [],
        }

        # 从 cardData 提取更多信息
        card_data = data.get("cardData", {})
        if card_data:
            # base_model 字段（单个或列表）
            base_model = card_data.get("base_model")
            if isinstance(base_model, list) and base_model:
                repo_metadata["base_model"] = base_model[0]
            elif isinstance(base_model, str):
                repo_metadata["base_model"] = base_model

        # 从 tags 中提取衍生关系
        # 例如: "base_model:meta-llama/Llama-2-7b-hf"
        for tag in repo_metadata["tags"]:
            if tag.startswith("base_model:"):
                parent = tag.split(":", 1)[1]
                if parent not in repo_metadata["derived_from"]:
                    repo_metadata["derived_from"].append(parent)

        return files, repo_metadata

    except requests.RequestException as e:
        logger.error(f"列出文件失败: {e}")
        return [], {}


def match_files(files: List[dict], pattern: str) -> List[dict]:
    """使用 glob pattern 匹配文件。

    Args:
        files: 文件列表（dict 格式，包含 filename 和 size）
        pattern: glob pattern

    Returns:
        匹配的文件列表
    """
    matched = []
    for f in files:
        if fnmatch.fnmatch(f["filename"], pattern):
            matched.append(f)
    return matched


def detect_xet_file(repo_id: str, repo_type: str, filename: str, token: str, session: requests.Session, hf_endpoint: str = "https://huggingface.co"):
    """检测文件是否为 XET 文件并获取元数据。

    Args:
        repo_id: 仓库 ID
        repo_type: 仓库类型
        filename: 文件名
        token: HF token
        session: requests session
        hf_endpoint: HF 端点 URL
    """
    # 根据 repo_type 构造文件 URL
    if repo_type == "dataset":
        file_url = f"{hf_endpoint}/datasets/{repo_id}/resolve/main/{filename}"
    else:
        file_url = f"{hf_endpoint}/{repo_id}/resolve/main/{filename}"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = session.head(file_url, headers=headers, allow_redirects=False, timeout=30)

        if resp.status_code not in (301, 302, 307, 308):
            return None

        link_header = resp.headers.get("Link", "")
        if not link_header:
            return None

        # 提取 auth URL
        auth_url = None
        match = re.search(r'<([^>]+)>;\s*rel="xet-auth"', link_header)
        if match:
            auth_url = match.group(1)
            if not auth_url.startswith("http"):
                auth_url = f"{hf_endpoint}{auth_url}"

        # 提取 xet-hash（多级 fallback，支持未来协议变化）
        xet_hash = None

        # 方法1: 标准 xet:// 协议格式 (rel="xet-hash")
        match = re.search(
            r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
            link_header,
            re.IGNORECASE
        )
        if match:
            xet_hash = match.group(1)

        # 方法2: reconstruction-info URL 中的 hash（通用版本）
        if not xet_hash:
            match = re.search(
                r'<https?://[^/]+/[^/]*/reconstructions?/([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-reconstruction',
                link_header,
                re.IGNORECASE
            )
            if match:
                xet_hash = match.group(1)

        # 方法3: 任何 URL 中的 64 字符 hex 串（最后的 fallback）
        if not xet_hash:
            match = re.search(
                r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
                link_header,
                re.IGNORECASE
            )
            if match:
                xet_hash = match.group(1)

        if not xet_hash or not auth_url:
            return None

        # 文件大小（优先使用 X-Linked-Size，它是真实文件大小）
        linked_size = resp.headers.get("X-Linked-Size")
        content_length = resp.headers.get("Content-Length")
        size = int(linked_size) if linked_size else (int(content_length) if content_length else 0)

        # SHA256（从 X-Linked-ETag 提取，去掉引号）
        sha256 = None
        linked_etag = resp.headers.get("X-Linked-ETag")
        if linked_etag:
            sha256 = linked_etag.strip('"')

        return {
            "xet_hash": xet_hash,
            "auth_url": auth_url,
            "size": size,
            "sha256": sha256,
        }

    except requests.RequestException as e:
        logger.error(f"检测文件失败: {e}")
        return None


def print_file_info(
    filename: str,
    xet_info: dict,
    cas_client: CASClient,
    indent: str = "",
    show_reconstruction: bool = True,
):
    """打印单个文件的信息。"""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    # 创建信息表格
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("属性", style="cyan")
    table.add_column("值", style="white")

    # 基本信息
    table.add_row("📄 文件名", filename)
    table.add_row("✅ 类型", "XET")
    table.add_row("📦 大小", f"{format_bytes(xet_info['size'])} ({xet_info['size']:,} bytes)")
    table.add_row("🔑 XET Hash", f"{xet_info['xet_hash'][:32]}...")

    # SHA256（用于完整文件校验）
    if xet_info.get('sha256'):
        table.add_row("🔐 SHA256", xet_info['sha256'])

    if show_reconstruction:
        try:
            # 获取 reconstruction 信息
            recon = cas_client.get_reconstruction(xet_info["xet_hash"])

            terms = len(recon.terms)
            xorbs = len(recon.fetch_info)

            table.add_row("📑 Terms", str(terms))
            table.add_row("🧩 Xorbs", f"{xorbs} (unique)")
            table.add_row("📍 Offset", str(recon.offset_into_first_range))

            # 统计 term 大小
            if terms > 0:
                sizes = [t.unpacked_length for t in recon.terms]
                size_info = (f"min={format_bytes(min(sizes))}, "
                           f"max={format_bytes(max(sizes))}, "
                           f"avg={format_bytes(sum(sizes) // len(sizes))}")
                table.add_row("📏 Term 大小", size_info)

        except Exception as e:
            table.add_row("⚠️  Reconstruction", f"✗ {e}")

    # 用 Panel 包裹表格
    console.print(Panel(table, title=f"[bold cyan]XET 文件信息[/bold cyan]", border_style="cyan"))


def format_bytes(n: int) -> str:
    """格式化字节数。"""
    if n == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def info_command(args):
    """执行 info 命令。"""
    try:
        # 1. 加载配置
        config = ConfigManager()
        endpoint = args.endpoint or config.get_endpoint()
        hf_token = args.token or config.get_token()
        hf_endpoint = getattr(args, 'hf_endpoint', None) or config.get_hf_endpoint()
        proxy = getattr(args, 'proxy', None) or config.get_proxy()

        if not hf_token:
            print("✗ 缺少 HF Token，请设置：xet config xet.token YOUR_TOKEN", file=sys.stderr)
            return 1

        # 2. 创建 session 并配置代理
        session = requests.Session()

        if proxy:
            session.proxies = {
                'http': proxy,
                'https': proxy,
            }
            logger.info(f"使用代理: {proxy}")

        # 3. 解析路径
        repo_id, filename, file_hash, repo_type = parse_file_spec(args.path)

        # 4. 处理不同情况
        if file_hash:
            # 直接查询 hash（需要 dummy repo 获取 CAS token）
            print("⚠ 直接使用 hash 查询需要指定 repo_id 来获取 CAS token")
            print("  建议使用: xet info user/repo/file.gguf")
            return 1

        elif filename:
            # 单个文件: user/repo/file
            xet_info = detect_xet_file(repo_id, repo_type, filename, hf_token, session, hf_endpoint)

            if not xet_info:
                print(f"✗ 文件不是 XET 格式: {filename}", file=sys.stderr)
                return 1

            # 获取 CAS token
            from xet.network.auth import XetAuth
            auth = XetAuth(hf_token=hf_token, session=session)
            token_info = auth.get_token(
                repo_id=repo_id,
                repo_type=repo_type,
                auth_url=xet_info["auth_url"]
            )

            cas_client = CASClient(
                endpoint=token_info.endpoint,
                access_token=token_info.access_token,
                session=session,
                auth=auth,
                repo_id=repo_id,
            )

            print()
            print_file_info(filename, xet_info, cas_client)

        else:
            # 批量查询: user/repo (可选 --include)
            repo_label = f"datasets/{repo_id}" if repo_type == "dataset" else repo_id

            # 列出文件
            all_files, repo_meta = list_hf_files(repo_id, repo_type, hf_token, session, hf_endpoint)
            if not all_files:
                print(f"✗ 无法列出仓库文件", file=sys.stderr)
                return 1

            # 显示仓库信息
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel

            console = Console()

            print(f"\n📦 仓库: [bold cyan]{repo_label}[/bold cyan]")

            # 仓库元数据
            if repo_meta:
                meta_parts = []
                if repo_meta.get("pipeline_tag"):
                    meta_parts.append(f"🏷️  任务: {repo_meta['pipeline_tag']}")
                if repo_meta.get("downloads"):
                    meta_parts.append(f"⬇️  下载: {repo_meta['downloads']:,}")
                if repo_meta.get("likes"):
                    meta_parts.append(f"❤️  点赞: {repo_meta['likes']:,}")

                if meta_parts:
                    print("   " + " | ".join(meta_parts))

                # 衍生关系
                if repo_meta.get("base_model"):
                    print(f"   🔗 基于: [yellow]{repo_meta['base_model']}[/yellow]")
                elif repo_meta.get("derived_from"):
                    derived = ", ".join(repo_meta["derived_from"])
                    print(f"   🔗 衍生自: [yellow]{derived}[/yellow]")

            # 如果没有 --include，列出所有文件的简要信息
            if not args.include:
                print(f"   找到 {len(all_files)} 个文件\n")

                # 创建文件列表表格
                table = Table(show_header=True, box=None)
                table.add_column("文件名", style="cyan", no_wrap=False)
                table.add_column("大小", justify="right", style="yellow")
                table.add_column("类型", justify="center", style="dim")

                xet_count = 0
                for file_info in all_files:
                    fname = file_info["filename"]
                    file_size = file_info["size"]

                    # 快速检测是否为 XET 文件
                    xet_info = detect_xet_file(repo_id, repo_type, fname, hf_token, session, hf_endpoint)

                    if xet_info:
                        # XET 文件：显示解压后大小
                        size_str = format_bytes(xet_info['size'])
                        table.add_row(fname, size_str, "XET")
                        xet_count += 1
                    else:
                        # 非 XET 文件：显示原始大小
                        if file_size > 0:
                            size_str = format_bytes(file_size)
                            table.add_row(fname, size_str, "")
                        else:
                            table.add_row(fname, "-", "")

                console.print(table)
                print(f"\n   💡 {xet_count} 个 XET 文件 / {len(all_files)} 总文件")
                print(f"   💡 使用 --include 'pattern' 查看详细信息")
                return 0

            # 有 --include，显示匹配文件的详细信息
            print(f"   匹配: {args.include}")
            print()

            matched = match_files(all_files, args.include)
            if not matched:
                print(f"✗ 没有匹配的文件", file=sys.stderr)
                return 1

            print(f"   找到 {len(matched)} 个匹配文件:\n")

            # 获取第一个文件的 CAS token（复用）
            first_xet = None
            cas_client = None

            for file_info in matched[:20]:  # 最多显示 20 个
                fname = file_info["filename"]
                xet_info = detect_xet_file(repo_id, repo_type, fname, hf_token, session, hf_endpoint)

                if not xet_info:
                    print(f"  ⊘ {fname}: 非 XET 文件")
                    continue

                # 初始化 CAS 客户端（首次）
                if cas_client is None:
                    from xet.network.auth import XetAuth
                    auth = XetAuth(hf_token=hf_token, session=session)
                    token_info = auth.get_token(
                        repo_id=repo_id,
                        repo_type=repo_type,
                        auth_url=xet_info["auth_url"]
                    )
                    cas_client = CASClient(
                        endpoint=token_info.endpoint,
                        access_token=token_info.access_token,
                        session=session,
                        auth=auth,
                        repo_id=repo_id,
                    )

                print_file_info(fname, xet_info, cas_client, indent="  ")
                print()

            if len(matched) > 20:
                print(f"  ... 还有 {len(matched) - 20} 个文件未显示")

        return 0

    except Exception as e:
        print(f"✗ 获取信息失败: {e}", file=sys.stderr)
        if logger.level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        return 1
