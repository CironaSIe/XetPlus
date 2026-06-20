"""Info 命令实现。"""
import sys
import logging
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
        token = args.token or config.get_token()

        # 2. 初始化 CAS 客户端
        cas_client = CASClient(endpoint=endpoint, access_token=token)

        # 3. 解析文件路径
        path = args.path

        # 检查是否是 hash
        if len(path) == 64 and all(c in "0123456789abcdef" for c in path.lower()):
            file_hash = path
            repo = None
            file_name = None
        elif "/" in path:
            parts = path.split("/", 1)
            repo = parts[0]
            file_name = parts[1]
            file_hash = None
        else:
            print(f"✗ 无效的文件路径: {path}", file=sys.stderr)
            return 1

        # 4. 获取文件信息
        if file_hash:
            # 通过 hash 获取 reconstruction
            logger.info(f"获取 reconstruction: {file_hash}")
            reconstruction = cas_client.get_reconstruction(file_hash)

            # 显示信息
            print(f"File Hash: {file_hash}")
            print(f"CAS Endpoint: {endpoint}")
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

        else:
            # 通过 repo/file 获取信息
            print(f"✗ 暂不支持通过 repo/file 查询，请使用 file_hash", file=sys.stderr)
            return 1

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
