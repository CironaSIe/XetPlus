"""Info 命令实现。"""
import sys
import os
import logging
import requests
from xet.network.cas_client import CASClient
from xet.cli.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def register_info_command(subparsers):
    """注册 info 子命令。"""
    parser = subparsers.add_parser(
        "info",
        help="查看文件信息",
        description="显示 XetHub 文件的详细信息。",
    )

    parser.add_argument(
        "path",
        help="文件路径（格式: repo/file 或 file_hash）",
    )

    parser.add_argument(
        "--endpoint",
        help="CAS 服务器地址（覆盖配置）",
    )

    parser.add_argument(
        "--token",
        help="认证 Token（覆盖配置）",
    )

    parser.set_defaults(func=info_command)


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

        # 从环境变量读取代理
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        if https_proxy:
            session.proxies = {
                'http': https_proxy,
                'https': https_proxy,
            }
            logger.info(f"使用代理: {https_proxy}")

        # 3. 解析文件路径
        path = args.path

        # 检查是否是 hash
        if len(path) == 64 and all(c in "0123456789abcdef" for c in path.lower()):
            file_hash = path
            repo_id = None
        elif "/" in path:
            print(f"✗ 暂不支持通过 repo/file 查询，请使用 file_hash", file=sys.stderr)
            return 1
        else:
            print(f"✗ 无效的文件路径: {path}", file=sys.stderr)
            return 1

        # 4. 对于直接使用 hash 的情况，我们需要一个 dummy repo_id 来获取 CAS token
        # 使用测试仓库作为默认
        if not repo_id:
            repo_id = "mykor/granite-embedding-97m-multilingual-r2-GGUF"
            # 使用一个已知存在的文件来获取 auth URL
            dummy_file = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
            logger.info(f"使用默认 repo_id: {repo_id}")

        # 5. 使用 XetAuth 获取 CAS token
        # 先通过 HEAD 请求获取 auth URL
        from xet.network.auth import XetAuth

        # 构造文件 URL 来获取 auth URL
        file_url = f"https://huggingface.co/mykor/granite-embedding-97m-multilingual-r2-GGUF/resolve/main/{dummy_file}"
        headers = {"Authorization": f"Bearer {hf_token}"}

        logger.info(f"获取 auth URL from: {file_url}")
        resp = session.head(file_url, headers=headers, allow_redirects=False, timeout=30)

        if resp.status_code not in (301, 302, 307, 308):
            print(f"✗ 无法获取 auth URL，状态码: {resp.status_code}", file=sys.stderr)
            return 1

        # 从 Link header 提取 auth URL
        link_header = resp.headers.get("Link", "")
        auth_url = None
        if link_header:
            import re
            match = re.search(r'<([^>]+)>;\s*rel="xet-auth"', link_header)
            if match:
                auth_url = match.group(1)
                if not auth_url.startswith("http"):
                    auth_url = f"https://huggingface.co{auth_url}"
                logger.info(f"找到 auth URL: {auth_url}")

        if not auth_url:
            print(f"✗ Link header 中未找到 xet-auth URL", file=sys.stderr)
            return 1

        auth = XetAuth(hf_token=hf_token, session=session)
        token_info = auth.get_token(repo_id=repo_id, repo_type="model", auth_url=auth_url)

        logger.info(f"获取到 CAS token, endpoint={token_info.endpoint}")

        # 6. 初始化 CAS 客户端（使用获取的 CAS token）
        cas_client = CASClient(
            endpoint=token_info.endpoint,
            access_token=token_info.access_token,
            session=session,
            auth=auth,
            repo_id=repo_id,
        )

        # 7. 获取文件信息
        logger.info(f"获取 reconstruction: {file_hash}")
        reconstruction = cas_client.get_reconstruction(file_hash)

        # 显示信息
        print(f"File Hash: {file_hash}")
        print(f"CAS Endpoint: {token_info.endpoint}")
        print()
        print("Reconstruction Info:")
        print(f"  Terms: {len(reconstruction.terms)}")
        print(f"  Offset into first range: {reconstruction.offset_into_first_range}")

        # 统计 xorb 数量
        xorb_count = len(reconstruction.fetch_info)
        print(f"  Xorbs: {xorb_count}")

        # 估算文件大小（从 terms 推断）
        total_size = sum(term.unpacked_length for term in reconstruction.terms)
        print(f"  Estimated Size: {format_bytes(total_size)}")

        return 0

    except Exception as e:
        print(f"✗ 获取信息失败: {e}", file=sys.stderr)
        if logger.level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        return 1


def format_bytes(bytes_val: int) -> str:
    """格式化字节数。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.2f} PB"
