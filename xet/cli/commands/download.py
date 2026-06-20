"""Download 命令实现。"""
import sys
import logging
from pathlib import Path
from typing import Optional

from xet.network.cas_client import CASClient
from xet.pipeline.file_reconstructor import FileReconstructor
from xet.cli.progress import create_progress
from xet.cli.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def register_download_command(subparsers):
    """注册 download 子命令。"""
    parser = subparsers.add_parser(
        "download",
        help="下载文件",
        description="从 XetHub 下载文件，支持断点续传和并行下载。",
    )

    parser.add_argument(
        "path",
        help="文件路径（格式: repo/file 或 file_hash）",
    )

    parser.add_argument(
        "-o", "--output",
        help="输出文件路径（默认: 当前目录）",
        type=Path,
    )

    parser.add_argument(
        "-c", "--concurrency",
        help="并发下载数（默认: 从配置读取或 4）",
        type=int,
    )

    parser.add_argument(
        "--resume",
        help="启用断点续传（默认）",
        action="store_true",
        default=True,
    )

    parser.add_argument(
        "--no-resume",
        help="禁用断点续传",
        action="store_false",
        dest="resume",
    )

    parser.add_argument(
        "--checkpoint",
        help="Checkpoint 文件路径（默认: 自动生成）",
        type=Path,
    )

    parser.add_argument(
        "--progress-style",
        help="进度条样式",
        choices=["rich", "simple", "quiet"],
        default="rich",
    )

    parser.add_argument(
        "--endpoint",
        help="CAS 服务器地址（覆盖配置）",
    )

    parser.add_argument(
        "--token",
        help="认证 Token（覆盖配置）",
    )

    parser.set_defaults(func=download_command)


def parse_file_spec(path: str) -> tuple[Optional[str], str]:
    """解析文件路径。

    支持两种格式：
    1. repo/file - 从仓库下载
    2. file_hash - 直接通过 hash 下载

    Returns:
        (repo, file_path) 或 (None, file_hash)
    """
    # 检查是否是 64 字符的 hash
    if len(path) == 64 and all(c in "0123456789abcdef" for c in path.lower()):
        return None, path

    # 否则解析为 repo/file
    if "/" not in path:
        raise ValueError(f"无效的文件路径格式: {path}。期望 'repo/file' 或 64 字符 hash")

    parts = path.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的文件路径格式: {path}")

    return parts[0], parts[1]


def get_checkpoint_path(args, file_hash: str) -> Optional[Path]:
    """获取 checkpoint 文件路径。"""
    if not args.resume:
        return None

    if args.checkpoint:
        return args.checkpoint

    # 默认: ~/.xet/checkpoints/<file_hash>.json
    checkpoint_dir = Path.home() / ".xet" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir / f"{file_hash}.json"


def download_command(args):
    """执行 download 命令。"""
    try:
        # 1. 加载配置
        config = ConfigManager()
        endpoint = args.endpoint or config.get_endpoint()
        token = args.token or config.get_token()
        concurrency = args.concurrency or config.get_concurrency()

        logger.info(f"使用配置: endpoint={endpoint}, concurrency={concurrency}")

        # 2. 初始化 CAS 客户端
        cas_client = CASClient(endpoint=endpoint, access_token=token)

        # 3. 解析文件路径
        repo, file_path = parse_file_spec(args.path)

        # 4. 获取文件信息
        if repo:
            logger.info(f"从仓库获取文件信息: {repo}/{file_path}")
            # TODO: 实现通过 repo/file 获取 file_hash 的 API
            # file_info = cas_client.get_file_info(repo, file_path)
            # file_hash = file_info.hash
            # expected_size = file_info.size
            # file_name = file_info.name
            print(f"✗ 暂不支持通过 repo/file 下载，请使用 file_hash", file=sys.stderr)
            sys.exit(1)
        else:
            # 直接使用 hash 下载
            file_hash = file_path
            expected_size = None  # 从 reconstruction 推断
            file_name = f"{file_hash[:8]}.bin"

        # 5. 确定输出路径
        if args.output:
            output_path = args.output
        else:
            output_path = Path.cwd() / file_name

        logger.info(f"输出路径: {output_path}")

        # 6. 获取 checkpoint 路径
        checkpoint_path = get_checkpoint_path(args, file_hash)
        if checkpoint_path:
            logger.info(f"Checkpoint 路径: {checkpoint_path}")

        # 7. 初始化进度条
        progress = create_progress(
            style=args.progress_style,
            description=f"Downloading {file_name}",
        )

        def progress_callback(stats):
            progress.update(stats)

        # 8. 初始化 FileReconstructor
        reconstructor = FileReconstructor(
            cas_client=cas_client,
            output_path=output_path,
            checkpoint_path=checkpoint_path,
            max_workers=concurrency,
            progress_callback=progress_callback,
        )

        # 9. 执行下载
        print(f"正在下载: {file_name}")
        print(f"Hash: {file_hash}")
        print(f"输出: {output_path}")
        print()

        with progress:
            result_path = reconstructor.reconstruct_file(
                file_hash=file_hash,
                expected_size=expected_size,
                resume=args.resume,
            )

        print(f"\n✓ 下载完成: {result_path}")
        print(f"文件大小: {result_path.stat().st_size:,} 字节")

        return 0

    except KeyboardInterrupt:
        print("\n⚠ 用户中断，进度已保存")
        return 130

    except ValueError as e:
        print(f"✗ 参数错误: {e}", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"✗ 下载失败: {e}", file=sys.stderr)
        if logger.level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        return 1
