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


def list_hf_files(repo_id: str, repo_type: str, token: str, session: requests.Session) -> List[str]:
    """列出 HuggingFace 仓库文件。"""
    # 根据 repo_type 构造 API URL
    if repo_type == "dataset":
        url = f"https://huggingface.co/api/datasets/{repo_id}"
    else:
        url = f"https://huggingface.co/api/models/{repo_id}"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        files = []
        for sibling in data.get("siblings", []):
            rpath = sibling.get("rfilename", "")
            if rpath:
                files.append(rpath)

        return files

    except requests.RequestException as e:
        logger.error(f"列出文件失败: {e}")
        return []


def match_files(files: List[str], pattern: str) -> List[str]:
    """使用 glob pattern 匹配文件。"""
    matched = []
    for f in files:
        if fnmatch.fnmatch(f, pattern):
            matched.append(f)
    return matched


def detect_xet_file(repo_id: str, repo_type: str, filename: str, token: str, session: requests.Session):
    """检测文件是否为 XET 文件并获取元数据。"""
    # 根据 repo_type 构造文件 URL
    if repo_type == "dataset":
        file_url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{filename}"
    else:
        file_url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"

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
                auth_url = f"https://huggingface.co{auth_url}"

        # 提取 xet-hash
        xet_hash = None
        match = re.search(r'<xet://([^>]+)>;\s*rel="xet-hash"', link_header)
        if match:
            xet_hash = match.group(1)

        if not xet_hash or not auth_url:
            return None

        # 文件大小
        content_length = resp.headers.get("Content-Length")
        size = int(content_length) if content_length else 0

        return {
            "xet_hash": xet_hash,
            "auth_url": auth_url,
            "size": size,
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
    print(f"{indent}📄 {filename}")
    print(f"{indent}  类型: XET ✅")
    print(f"{indent}  大小: {format_bytes(xet_info['size'])} ({xet_info['size']:,} bytes)")
    print(f"{indent}  Xet Hash: {xet_info['xet_hash'][:32]}...")

    if show_reconstruction:
        try:
            # 获取 reconstruction 信息
            recon = cas_client.get_reconstruction(xet_info["xet_hash"])

            terms = len(recon.terms)
            xorbs = len(recon.fetch_info)

            print(f"{indent}  Terms: {terms}")
            print(f"{indent}  Xorbs: {xorbs} (unique)")
            print(f"{indent}  Offset into first range: {recon.offset_into_first_range}")

            # 统计 term 大小
            if terms > 0:
                sizes = [t.unpacked_length for t in recon.terms]
                print(f"{indent}  Term 大小: min={format_bytes(min(sizes))}, "
                      f"max={format_bytes(max(sizes))}, "
                      f"avg={format_bytes(sum(sizes) // len(sizes))}")

        except Exception as e:
            print(f"{indent}  Reconstruction: ✗ {e}")


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

        if not hf_token:
            print("✗ 缺少 HF Token，请设置：xet config xet.token YOUR_TOKEN", file=sys.stderr)
            return 1

        # 2. 创建 session 并配置代理
        session = requests.Session()

        proxy = args.proxy if hasattr(args, 'proxy') and args.proxy else None
        if not proxy:
            proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')

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
            xet_info = detect_xet_file(repo_id, repo_type, filename, hf_token, session)

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
            # 批量查询: user/repo + --include
            if not args.include:
                print(f"✗ 批量查询需要 --include 参数指定文件匹配模式", file=sys.stderr)
                repo_label = f"datasets/{repo_id}" if repo_type == "dataset" else repo_id
                print(f"  示例: xet info {repo_label} --include '*.gguf'")
                return 1

            repo_label = f"datasets/{repo_id}" if repo_type == "dataset" else repo_id
            print(f"\n📦 仓库: {repo_label}")
            print(f"   匹配: {args.include}")
            print()

            # 列出文件
            all_files = list_hf_files(repo_id, repo_type, hf_token, session)
            if not all_files:
                print(f"✗ 无法列出仓库文件", file=sys.stderr)
                return 1

            matched = match_files(all_files, args.include)
            if not matched:
                print(f"✗ 没有匹配的文件", file=sys.stderr)
                return 1

            print(f"   找到 {len(matched)} 个匹配文件:\n")

            # 获取第一个文件的 CAS token（复用）
            first_xet = None
            cas_client = None

            for fname in matched[:20]:  # 最多显示 20 个
                xet_info = detect_xet_file(repo_id, repo_type, fname, hf_token, session)

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
