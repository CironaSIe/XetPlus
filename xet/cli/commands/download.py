"""Download 命令实现 - 改进版。

支持:
1. user/repo/file 格式（自动获取 xet_hash）
2. file_hash 直接下载
3. 批量下载（--include glob 匹配）
4. IP 优选参数（预留）
"""
import sys
import os
import re
import fnmatch
import logging
import requests
from pathlib import Path
from typing import Optional, List, Tuple

from xet.network.cas_client import CASClient
from xet.pipeline.file_reconstructor import FileReconstructor
from xet.pipeline.xorb_disk_cache import XorbDiskCache
from xet.pipeline.chunk_disk_cache import ChunkDiskCache
from xet.cli.progress import create_progress
from xet.cli.config_manager import ConfigManager


logger = logging.getLogger(__name__)


def register_download_command(subparsers):
    """注册 download 子命令。"""
    parser = subparsers.add_parser(
        "download",
        help="下载文件",
        description="从 HuggingFace 下载 XET 文件，支持断点续传和并行下载。",
    )

    parser.add_argument(
        "path",
        help="文件路径（格式: user/repo/file.gguf, user/repo 或 file_hash）",
    )

    parser.add_argument(
        "-o", "--output",
        help="输出目录或文件路径（默认: ./downloads）",
        type=Path,
    )

    parser.add_argument(
        "-i", "--include",
        help="批量匹配 glob pattern（如 *.gguf）",
    )

    parser.add_argument(
        "-r", "--revision",
        help="Git revision (分支名或 commit hash，默认: main)",
        default="main",
    )

    parser.add_argument(
        "-c", "--concurrency", "--concurrent",
        help="并发下载数（默认: 从配置读取或 4）",
        type=int,
        dest="concurrency",
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

    # IP 优选参数
    optimize_group = parser.add_mutually_exclusive_group()
    optimize_group.add_argument(
        "--optimize-hosts",
        help="启用 HOST 优选（DoH 查询 + 测速，国内网络优化）。"
             "建议配合 --proxy 使用以访问海外 DoH 服务器。"
             "可通过配置文件设置默认值: xet config network.optimize_hosts true",
        action="store_true",
        dest="optimize_hosts_flag",
    )

    optimize_group.add_argument(
        "--no-optimize-hosts",
        help="禁用 HOST 优选（即使配置文件中启用）",
        action="store_true",
        dest="no_optimize_hosts_flag",
    )

    parser.add_argument(
        "--refresh-hosts",
        help="强制刷新 HOST 优选缓存（重新测速）",
        action="store_true",
    )

    parser.add_argument(
        "--proxy",
        help="HTTP/HTTPS 代理地址（如 http://127.0.0.1:7890）。"
             "也可通过环境变量 HTTPS_PROXY 设置",
    )

    parser.add_argument(
        "--hf-endpoint",
        help="HuggingFace 镜像站端点（默认: https://huggingface.co）。"
             "示例: https://hf-mirror.com (国内镜像，可直连)。"
             "用于替换所有 huggingface.co 请求，包括认证、元数据和文件下载。"
             "也可通过环境变量 HF_ENDPOINT 设置",
    )

    parser.add_argument(
        "--dns-servers",
        help="自定义 DoH 服务器列表（逗号分隔）。"
             "示例: https://cloudflare-dns.com/dns-query,https://dns.google/dns-query"
             "默认使用内置服务器列表（国内优先 + 海外备选）",
    )

    # 分段下载参数
    parser.add_argument(
        "--segment-size",
        help="分段大小（如 256MB, 1GB），自动根据文件大小选择",
        type=str,
    )

    parser.add_argument(
        "--parallel-segments",
        help="并行段数（默认: 1，顺序下载）",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--no-adaptive-concurrency",
        help="禁用自适应并发控制（默认启用）",
        action="store_true",
    )

    # 下载模式参数
    parser.add_argument(
        "--mode",
        help="下载模式: auto（自动选择）、xet（XET 重建）、direct（直接下载）。"
             "auto 模式: <256MB 用 direct，>=256MB 用 xet",
        choices=["auto", "xet", "direct"],
        default="auto",
    )

    # Xorb 缓存参数
    parser.add_argument(
        "--cache-dir",
        help="Xorb 缓存目录（默认: ~/.xet/cache/xorbs）",
        type=Path,
    )

    parser.add_argument(
        "--keep-cache",
        help="下载完成后保留 Xorb 缓存（默认: 删除缓存）",
        action="store_true",
    )

    parser.add_argument(
        "--no-cache",
        help="禁用 Xorb 磁盘缓存",
        action="store_true",
    )

    # 内存控制参数（低内存环境优化）
    parser.add_argument(
        "--max-memory-mb",
        help="解压缓冲区内存限制（单位：MB，默认: 200）。"
             "限制同时在内存中的解压 xorb 数据总量。"
             "推荐值: 100-150（低内存，如 Termux）、200-300（正常）、400+（高内存）",
        type=int,
        default=200,
    )

    # 预取控制参数（高级用户）
    parser.add_argument(
        "--prefetch-low",
        help="预取低水位线（单位：MB，默认: 48）。"
             "当缓存低于此值时触发预取。",
        type=int,
        default=48,
    )
    parser.add_argument(
        "--prefetch-high",
        help="预取高水位线（单位：MB，默认: 192）。"
             "预取时最多缓存到此值。",
        type=int,
        default=192,
    )
    parser.add_argument(
        "--prefetch-max",
        help="单次最多预取 xorb 数量（默认: 8）。"
             "限制并发预取的 xorb 数量，配合水位线精确控制内存。",
        type=int,
        default=8,
    )

    # 断点续传和重试参数
    parser.add_argument(
        "--checkpoint-interval",
        help="每 N terms 保存 checkpoint（默认: 10）。"
             "更小的值提供更精确的断点续传，但增加 I/O 开销。",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--retry-max",
        help="最大重试次数（默认: 5）。"
             "单个 xorb 下载失败后的最大重试次数。",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--parallel-write",
        action="store_true",
        default=False,
        help="启用并行批量写入（实验性功能）。"
             "通过批量 seek + write + 统一 fsync 减少系统调用，大文件性能提升 2-3 倍。"
             "注意：Windows 需要 CreateFileW 支持，Linux/macOS 默认兼容。",
    )
    parser.add_argument(
        "--buffer-mb",
        help="写入缓冲区大小（单位：MB，默认: 32）。"
             "控制 GlobalWriter 的批量写入缓冲大小。"
             "推荐值: 8-16（内存受限）、32（默认）、64+（高性能 SSD）",
        type=int,
        default=32,
    )

    parser.set_defaults(func=download_command)


def parse_file_spec(path: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """解析文件路径。

    支持格式:
    1. user/repo/file.gguf → (repo_id, filename, None, "model")
    2. datasets/user/repo/file.bin → (repo_id, filename, None, "dataset")
    3. user/repo → (repo_id, None, None, "model")
    4. datasets/user/repo → (repo_id, None, None, "dataset")
    5. 64-char-hash → (None, None, file_hash, "model")

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

    # user/repo/file 或更多层级
    if len(parts) >= 3:
        # 最后一部分是文件名
        filename = parts[-1]
        repo_id = "/".join(parts[:-1])
        return repo_id, filename, None, repo_type

    # user/repo（无文件名）
    elif len(parts) == 2:
        repo_id = "/".join(parts)
        return repo_id, None, None, repo_type

    else:
        raise ValueError(f"无效的文件路径格式: {path}")


def list_hf_files(
    repo_id: str,
    repo_type: str,
    token: str,
    session: requests.Session,
    hf_endpoint: str = "https://huggingface.co",
) -> List[str]:
    """列出 HuggingFace 仓库中的所有文件。

    Args:
        repo_id: 仓库 ID
        repo_type: 仓库类型 ("model" 或 "dataset")
        token: HF Token
        session: requests.Session
        hf_endpoint: HF 端点 URL（默认: https://huggingface.co）

    Returns:
        文件路径列表
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


def detect_xet_file(
    repo_id: str,
    repo_type: str,
    filename: str,
    token: str,
    session: requests.Session,
    revision: str = "main",
    hf_endpoint: str = "https://huggingface.co",
) -> Optional[dict]:
    """检测文件是否为 XET 文件并获取元数据。

    Args:
        repo_id: 仓库 ID
        repo_type: 仓库类型 ("model" 或 "dataset")
        filename: 文件名
        token: HF Token
        session: requests.Session
        revision: 分支名或 commit hash，默认 "main"
        hf_endpoint: HF 端点 URL（默认: https://huggingface.co）

    Returns:
        {
            "xet_hash": str,
            "auth_url": str,
            "size": int,
            "sha256": str,
        } 或 None
    """
    # 根据 repo_type 构造文件 URL
    if repo_type == "dataset":
        file_url = f"{hf_endpoint}/datasets/{repo_id}/resolve/{revision}/{filename}"
    else:
        file_url = f"{hf_endpoint}/{repo_id}/resolve/{revision}/{filename}"

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # HEAD 请求获取 X-Xet-Hash header
        resp = session.head(file_url, headers=headers, allow_redirects=False, timeout=30)

        # 如果 main 分支不存在（404），尝试自动探测最新 commit
        if resp.status_code == 404 and revision == "main":
            logger.info(f"main 分支不存在，尝试获取最新 commit...")

            # 方法 1: 通过 API 获取仓库信息
            api_url = f"{hf_endpoint}/api/models/{repo_id}" if repo_type != "dataset" else f"{hf_endpoint}/api/datasets/{repo_id}"
            try:
                api_resp = session.get(api_url, headers=headers, timeout=10)
                if api_resp.status_code == 200:
                    data = api_resp.json()
                    latest_sha = data.get("sha")
                    if latest_sha:
                        logger.info(f"检测到最新 commit: {latest_sha[:12]}...")
                        # 递归调用，使用最新 commit
                        return detect_xet_file(repo_id, repo_type, filename, token, session, revision=latest_sha, hf_endpoint=hf_endpoint)
            except Exception as e:
                logger.debug(f"API 获取失败: {e}")

            logger.warning(f"无法自动探测最新 commit，文件不存在: {filename}")
            return None

        if resp.status_code not in (301, 302, 307, 308):
            logger.warning(f"文件不是 XET 格式: {filename}")
            return None

        # 解析 Link header（需要先解析以便提取 xet_hash）
        link_header = resp.headers.get("Link", "")
        auth_url = None
        recon_url = None

        if link_header:
            # 提取 xet-auth URL
            auth_match = re.search(r'<([^>]+)>;\s*rel="xet-auth"', link_header)
            if auth_match:
                auth_url = auth_match.group(1)
                if not auth_url.startswith("http"):
                    auth_url = f"{hf_endpoint}{auth_url}"

            # 提取 xet-reconstruction-info URL
            recon_match = re.search(r'<([^>]+)>;\s*rel="xet-reconstruction-info"', link_header)
            if recon_match:
                recon_url = recon_match.group(1)

        # 提取 xet-hash（多级 fallback，支持未来协议变化）
        xet_hash = None

        # 方法1: X-Xet-Hash 头（直接提供 hash）
        xet_hash = resp.headers.get("X-Xet-Hash")

        # 方法2: 标准 xet:// 协议格式 (rel="xet-hash")
        if not xet_hash and link_header:
            match = re.search(
                r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
                link_header,
                re.IGNORECASE
            )
            if match:
                xet_hash = match.group(1)
                logger.debug(f"从 xet:// URI 提取 xet_hash: {xet_hash[:16]}...")

        # 方法3: reconstruction-info URL 中的 hash（通用版本）
        if not xet_hash and recon_url:
            match = re.search(
                r'/reconstructions?/([0-9a-f]{64})',
                recon_url,
                re.IGNORECASE
            )
            if match:
                xet_hash = match.group(1)
                logger.debug(f"从 reconstruction URL 提取 xet_hash: {xet_hash[:16]}...")

        # 方法4: 任何 URL 中的 64 字符 hex 串（最后的 fallback）
        if not xet_hash and link_header:
            match = re.search(
                r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
                link_header,
                re.IGNORECASE
            )
            if match:
                xet_hash = match.group(1)
                logger.debug(f"从通用 xet Link 提取 xet_hash: {xet_hash[:16]}...")

        if not xet_hash:
            logger.debug(f"文件缺少 X-Xet-Hash header 且无法从 Link 提取: {filename}")
            return None

        if not auth_url:
            logger.debug(f"文件缺少 xet-auth URL: {filename}")
            return None

        # 获取文件大小和 SHA256
        size = 0
        sha256 = ""

        # X-Linked-Size: 实际文件大小（未压缩）
        linked_size = resp.headers.get("X-Linked-Size")
        if linked_size:
            size = int(linked_size)

        # X-Linked-ETag: SHA256 (去掉引号)
        linked_etag = resp.headers.get("X-Linked-ETag", "")
        if linked_etag:
            sha256 = linked_etag.strip('"')

        return {
            "xet_hash": xet_hash,
            "auth_url": auth_url,
            "size": size,
            "sha256": sha256,
        }

    except requests.RequestException as e:
        logger.error(f"检测 XET 文件失败: {e}")
        return None


def parse_size(size_str: str) -> int:
    """解析大小字符串（如 '256MB', '1GB'）。

    Args:
        size_str: 大小字符串

    Returns:
        字节数

    Raises:
        ValueError: 格式无效
    """
    size_str = size_str.strip().upper()

    # 提取数字和单位
    import re
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMGT]?B?)$', size_str)
    if not match:
        raise ValueError(f"无效的大小格式: {size_str}")

    number = float(match.group(1))
    unit = match.group(2) or 'B'

    # 单位转换
    multipliers = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
        'K': 1024,
        'M': 1024 ** 2,
        'G': 1024 ** 3,
        'T': 1024 ** 4,
    }

    multiplier = multipliers.get(unit)
    if multiplier is None:
        raise ValueError(f"未知的单位: {unit}")

    return int(number * multiplier)


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


def download_file_direct(
    repo_id: str,
    filename: str,
    xet_info: dict,
    output_path: Path,
    args,
    session: requests.Session,
    repo_type: str = "model",
    hf_endpoint: str = "https://huggingface.co",
) -> bool:
    """使用 presigned URL 直接下载文件（不经过 XET 重建）。

    适用于小文件（<256MB），速度更快。

    Args:
        repo_id: 仓库 ID
        filename: 文件名
        xet_info: XET 文件元数据
        output_path: 输出路径
        args: 命令行参数
        session: 复用的 Session（支持 HOST 优选）
        repo_type: 仓库类型（model 或 dataset）

    Returns:
        成功返回 True，失败返回 False
    """
    import time
    from tqdm import tqdm

    expected_size = xet_info.get("size", 0)

    # 1. 获取 presigned URL
    # 直接构造下载 URL（HuggingFace 会重定向到 presigned URL）
    if repo_type == "dataset":
        file_url = f"{hf_endpoint}/datasets/{repo_id}/resolve/main/{filename}"
    else:
        file_url = f"{hf_endpoint}/{repo_id}/resolve/main/{filename}"

    try:
        # 2. 下载文件（使用传入的 session，支持 HOST 优选）
        print(f"   正在获取下载链接...")
        headers = {}
        if hasattr(args, 'token') and args.token:
            headers["Authorization"] = f"Bearer {args.token}"

        response = session.get(
            file_url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=30,
        )
        response.raise_for_status()

        # 3. 流式写入文件
        total_size = int(response.headers.get('content-length', expected_size))

        with open(output_path, 'wb') as f:
            with tqdm(
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=filename[:40],
            ) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

        # 4. 验证文件大小
        actual_size = output_path.stat().st_size
        if expected_size > 0 and actual_size != expected_size:
            print(f"⚠ 警告: 文件大小不匹配 ({actual_size} != {expected_size})")

        from rich.console import Console
        console = Console()
        console.print(f"[green]✓[/green] 下载完成: [cyan]{output_path}[/cyan]")
        return True

    except Exception as e:
        logger.error(f"Direct 模式下载失败: {e}")
        # 清理部分下载的文件
        if output_path.exists():
            output_path.unlink()
        raise

    finally:
        session.close()


def download_single_file(
    repo_id: str,
    filename: str,
    xet_info: dict,
    output_path: Path,
    cas_client: CASClient,
    args,
    repo_type: str = "model",
    xorb_cache: Optional[XorbDiskCache] = None,
    chunk_cache = None,
    hf_endpoint: str = "https://huggingface.co",
) -> bool:
    """下载单个文件。

    Args:
        repo_id: 仓库 ID
        filename: 文件名
        xet_info: XET 文件元数据
        output_path: 输出路径
        cas_client: CAS 客户端
        args: 命令行参数
        repo_type: 仓库类型（model 或 dataset）
        xorb_cache: Xorb 缓存实例
        chunk_cache: Chunk 缓存实例
        hf_endpoint: HF 端点 URL

    Returns:
        成功返回 True，失败返回 False
    """
    file_hash = xet_info["xet_hash"]
    expected_size = xet_info.get("size", 0)

    print(f"\n{'='*60}")
    print(f"📥 下载: {filename}")
    print(f"   Hash: {file_hash}")
    print(f"   大小: {format_bytes(expected_size)}")
    print(f"   输出: {output_path}")

    # 1. 决定下载模式
    mode = getattr(args, 'mode', 'auto')
    use_direct = False

    if mode == 'direct':
        # 强制使用 direct 模式
        use_direct = True
        print(f"   模式: direct（直接下载）")
    elif mode == 'xet':
        # 强制使用 xet 重建模式
        use_direct = False
        print(f"   模式: xet（XET 重建）")
    else:
        # auto 模式：根据文件大小自动选择
        DIRECT_THRESHOLD = 256 * 1024 * 1024  # 256 MB
        if expected_size > 0 and expected_size < DIRECT_THRESHOLD:
            use_direct = True
            print(f"   模式: direct（文件 < 256MB，自动选择）")
        else:
            use_direct = False
            print(f"   模式: xet（文件 >= 256MB 或大小未知，自动选择）")

    # 2. 如果使用 direct 模式，执行直接下载
    if use_direct:
        try:
            return download_file_direct(
                repo_id=repo_id,
                filename=filename,
                xet_info=xet_info,
                output_path=output_path,
                args=args,
                session=session,
                repo_type=repo_type,
                hf_endpoint=hf_endpoint,
            )
        except Exception as e:
            print(f"⚠ Direct 模式失败 ({e})，回退到 XET 重建模式")
            # 回退到 XET 模式
            use_direct = False

    # 3. 使用 XET 重建模式
    # 决定是否使用分段下载
    use_segmented = False
    segment_size = None
    parallel_segments = getattr(args, 'parallel_segments', 1)

    # 解析segment_size参数
    if hasattr(args, 'segment_size') and args.segment_size:
        try:
            segment_size = parse_size(args.segment_size)
            use_segmented = True
            print(f"   分段大小: {format_bytes(segment_size)}")
        except ValueError as e:
            print(f"⚠ 警告: {e}，将自动选择分段大小")
            use_segmented = True

    # 如果文件很大（>1GB），自动启用分段下载
    if not use_segmented and expected_size > 1 * 1024 ** 3:
        use_segmented = True
        print(f"   自动启用分段下载（文件 > 1GB）")

    if use_segmented:
        print(f"   并行段数: {parallel_segments}")

    # 创建进度条
    progress = create_progress(
        style=args.progress_style,
        description=f"{filename[:40]}",
    )

    def progress_callback(stats):
        progress.update(stats)

    # 执行下载
    try:
        with progress:
            if use_segmented:
                # 使用分段下载
                from xet.pipeline.segmented_reconstructor import SegmentedReconstructor

                reconstructor = SegmentedReconstructor(
                    cas_client=cas_client,
                    output_path=output_path,
                    file_hash=file_hash,
                    file_size=expected_size,
                    segment_size=segment_size,
                    max_workers=args.concurrency or 4,
                    parallel_segments=parallel_segments,
                    progress_callback=progress_callback,
                )

                result_path = reconstructor.reconstruct_file(resume=args.resume)
            else:
                # 使用标准下载
                checkpoint_path = get_checkpoint_path(args, file_hash)
                if checkpoint_path:
                    logger.info(f"Checkpoint: {checkpoint_path}")

                reconstructor = FileReconstructor(
                    cas_client=cas_client,
                    output_path=output_path,
                    checkpoint_path=checkpoint_path,
                    max_workers=args.concurrency or 4,
                    progress_callback=progress_callback,
                    xorb_cache=xorb_cache,
                    chunk_cache=chunk_cache,
                    max_memory_mb=getattr(args, 'max_memory_mb', 200),
                    prefetch_low_mb=getattr(args, 'prefetch_low', 48),
                    prefetch_high_mb=getattr(args, 'prefetch_high', 192),
                    prefetch_max=getattr(args, 'prefetch_max', 8),
                    checkpoint_interval=getattr(args, 'checkpoint_interval', 10),
                    retry_max=getattr(args, 'retry_max', 5),
                    parallel_write=getattr(args, 'parallel_write', False),
                    buffer_mb=getattr(args, 'buffer_mb', 32),
                    ip_pool_manager=ip_pool_manager,  # ← 传递
                    host_optimizer=host_optimizer if optimize_hosts else None,  # ← 传递
                )

                result_path = reconstructor.reconstruct_file(
                    file_hash=file_hash,
                    expected_size=expected_size,
                    resume=args.resume,
                )

        # 下载完成，显示美化的成功消息
        file_size = result_path.stat().st_size
        from rich.console import Console
        from rich.panel import Panel
        console = Console()

        success_msg = (
            f"[green]✓[/green] 文件已保存: [cyan]{result_path}[/cyan]\n"
            f"[green]✓[/green] 文件大小: [yellow]{format_bytes(file_size)}[/yellow] ({file_size:,} bytes)"
        )

        console.print(Panel(success_msg, title="[bold green]下载完成[/bold green]", border_style="green"))
        return True

    except KeyboardInterrupt:
        print(f"\n⚠ 用户中断，进度已保存")
        raise

    except Exception as e:
        print(f"✗ 下载失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def format_bytes(n: int) -> str:
    """格式化字节数。"""
    if n == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def download_command(args):
    """执行 download 命令。"""
    try:
        # 1. 加载配置
        config = ConfigManager()
        endpoint = args.endpoint or config.get_endpoint()
        hf_token = args.token or config.get_token()
        concurrency = args.concurrency or config.get_concurrency()

        if not hf_token:
            print("✗ 缺少 HF Token，请设置：xet config xet.token YOUR_TOKEN", file=sys.stderr)
            return 1

        logger.info(f"使用配置: concurrency={concurrency}")

        # 2. 从命令行或环境变量读取代理
        proxy = args.proxy if hasattr(args, 'proxy') and args.proxy else None
        if not proxy:
            proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')

        # 2.5. 从命令行或环境变量读取 HF_ENDPOINT
        hf_endpoint = args.hf_endpoint if hasattr(args, 'hf_endpoint') and args.hf_endpoint else None
        if not hf_endpoint:
            hf_endpoint = os.environ.get('HF_ENDPOINT') or "https://huggingface.co"

        # 标准化：移除尾部斜杠
        hf_endpoint = hf_endpoint.rstrip('/')

        if hf_endpoint != "https://huggingface.co":
            logger.info(f"[Download] 使用自定义 HF 端点: {hf_endpoint}")

        # 3. 创建 Session（集成 IP 优选）
        from xet.network.host_optimizer import create_optimized_session

        # 优先级：命令行参数 > 配置文件 > 默认值 False
        if getattr(args, 'optimize_hosts_flag', False):
            # 用户明确指定 --optimize-hosts
            optimize_hosts = True
        elif getattr(args, 'no_optimize_hosts_flag', False):
            # 用户明确指定 --no-optimize-hosts
            optimize_hosts = False
        else:
            # 命令行未指定，使用配置文件
            optimize_hosts = config.get_optimize_hosts()

        refresh_hosts = getattr(args, 'refresh_hosts', False)

        # 解析 DNS 服务器列表
        dns_servers = None
        if hasattr(args, 'dns_servers') and args.dns_servers:
            dns_servers = [s.strip() for s in args.dns_servers.split(',') if s.strip()]
            if dns_servers:
                logger.info(f"[Download] 使用自定义 DNS 服务器: {len(dns_servers)} 个")

        if optimize_hosts:
            print("🚀 正在执行 HOST 优选（DoH 查询 + 测速）...")

            # 如果使用自定义 HF_ENDPOINT，先检测其 XET 支持
            if hf_endpoint != "https://huggingface.co":
                from xet.network.host_optimizer import check_hf_endpoint_xet_support

                print(f"   检测 {hf_endpoint} 的 XET 支持...")
                check_result = check_hf_endpoint_xet_support(
                    endpoint=hf_endpoint,
                    proxy=proxy or "",
                    timeout=10,
                )

                if check_result["reachable"]:
                    if check_result["supports_xet"]:
                        print(f"   ✅ {hf_endpoint} 支持 XET 协议（响应时间: {check_result['response_time']:.2f}s）")
                        if check_result["xet_headers"].get("x-linked-etag"):
                            etag = check_result["xet_headers"]["x-linked-etag"][:16]
                            print(f"      x-linked-etag: {etag}...")
                    else:
                        if check_result["has_xet_headers"]:
                            print(f"   ⚠️  {hf_endpoint} 有 XET 头但缺少 Link 头")
                        else:
                            print(f"   ⚠️  {hf_endpoint} 不支持 XET 协议，可能无法下载")
                else:
                    print(f"   ❌ {hf_endpoint} 不可达: {check_result.get('error', 'Unknown')}")
                    print(f"      建议检查网络连接或尝试添加 --proxy 参数")

        session, host_optimizer = create_optimized_session(
            proxy=proxy or "",
            optimize_hosts=optimize_hosts,
            refresh_hosts=refresh_hosts,
            dns_servers=dns_servers,
        )

        if optimize_hosts and host_optimizer:
            mappings = host_optimizer.mappings
            if mappings:
                print(f"✅ HOST 优选完成: {len(mappings)} 个域名")

                # 检查是否有详细结果可以显示
                detailed_results = getattr(host_optimizer, 'detailed_results', {})

                for domain, info in mappings.items():
                    from xet.network.host_optimizer import get_domain_category
                    category = get_domain_category(domain)
                    category_label = {
                        "api": "API域名",
                        "data": "DATA域名",
                        "cas": "CAS域名",
                    }.get(category, "")

                    mode = "代理" if info["use_proxy"] else "直连"
                    rtt_ms = info["rtt"] * 1000

                    # 显示选中的 IP
                    if info.get("speed", 0) > 0:
                        from xet.network.host_optimizer import _format_speed
                        speed_str = _format_speed(info["speed"])
                        domain_title = f"{domain} ({category_label})" if category_label else domain
                        print(f"   {domain_title}")
                        print(f"     ✅ {info['ip']}  {mode}  RTT={rtt_ms:.0f}ms  带宽={speed_str}")
                    else:
                        domain_title = f"{domain} ({category_label})" if category_label else domain
                        print(f"   {domain_title}")
                        print(f"     ✅ {info['ip']}  {mode}  RTT={rtt_ms:.0f}ms")

                    # 如果有详细结果，显示其他候选 IP（最多3个）
                    if domain in detailed_results:
                        other_ips = [
                            ip for ip in detailed_results[domain]
                            if ip["ip"] != info["ip"]
                        ][:3]  # 最多显示3个其他候选

                        for ip_info in other_ips:
                            ip = ip_info["ip"]
                            use_proxy = ip_info.get("use_proxy", False)
                            mode = "代理" if use_proxy else "直连"
                            rtt = ip_info.get("rtt", 0)
                            speed = ip_info.get("speed", 0)
                            status = ip_info.get("status", "unknown")
                            cert_valid = ip_info.get("cert_valid", False)
                            cert_issuer = ip_info.get("cert_issuer", "")

                            if status == "ok" and cert_valid:
                                # 证书有效但未选中
                                from xet.network.host_optimizer import _format_speed
                                speed_str = _format_speed(speed) if speed > 0 else "0"
                                cert_info = f"  证书={cert_issuer}" if cert_issuer else ""
                                print(f"       {ip}  {mode}  RTT={rtt*1000:.0f}ms  带宽={speed_str}{cert_info}")
                            elif status == "cert_invalid":
                                # 证书无效
                                cert_error = ip_info.get("cert_error", "未知")
                                print(f"     ❌ {ip}  {mode}  证书验证失败: {cert_error}")
                            elif status == "transfer_failed":
                                # Transfer 失败
                                print(f"     ❌ {ip}  {mode}  RTT={rtt*1000:.0f}ms  Transfer失败")
            else:
                print("⚠ HOST 优选未生效，将使用系统 DNS")

        # 3.5. 初始化 IP 池管理器（如果启用了优选）
        ip_pool_manager = None
        if optimize_hosts and host_optimizer:
            from pathlib import Path
            from xet.network.ip_pool_manager import IPPoolManager

            cache_file = Path.home() / ".xet" / "cache" / "host_optimize.json"
            if cache_file.exists():
                try:
                    ip_pool_manager = IPPoolManager(cache_file)
                    logger.info(
                        f"[IPPoolManager] 已初始化，"
                        f"加载 {len(ip_pool_manager.pools)} 个域名的 IP 池"
                    )
                except Exception as e:
                    logger.warning(f"[IPPoolManager] 初始化失败: {e}")
            else:
                logger.debug("[IPPoolManager] 缓存文件不存在，跳过初始化")

        # 4. 解析文件路径
        repo_id, filename, file_hash, repo_type = parse_file_spec(args.path)

        # 5. 确定要下载的文件列表
        files_to_download = []  # [(repo_id, filename, xet_info, repo_type), ...]

        if file_hash:
            # 直接使用 hash 下载 - 使用 dummy repo 获取 CAS token
            print(f"💡 直接使用 hash 下载: {file_hash[:16]}...")
            print(f"   将使用默认仓库获取 CAS token")

            # 使用一个已知的 XET 仓库来获取 token
            dummy_repo = "mykor/granite-embedding-97m-multilingual-r2-GGUF"
            dummy_file = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"

            # 获取 auth URL
            dummy_xet = detect_xet_file(dummy_repo, "model", dummy_file, hf_token, session, revision="main", hf_endpoint=hf_endpoint)
            if not dummy_xet:
                print("✗ 无法获取 CAS token，请改用 user/repo/file 格式", file=sys.stderr)
                return 1

            # 构造虚拟的 xet_info（用于获取 token）
            xet_info = {
                "xet_hash": file_hash,
                "auth_url": dummy_xet["auth_url"],
                "size": 0,  # 未知大小，从 reconstruction 推断
            }

            # 生成文件名
            filename = f"{file_hash[:8]}.bin"
            files_to_download.append((dummy_repo, filename, xet_info, "model"))

        elif filename:
            # 单个文件: user/repo/file
            logger.info(f"检测文件: {repo_id}/{filename} (repo_type={repo_type}, revision={args.revision})")
            xet_info = detect_xet_file(repo_id, repo_type, filename, hf_token, session, revision=args.revision, hf_endpoint=hf_endpoint)

            if not xet_info:
                print(f"✗ 文件不是 XET 格式: {filename}", file=sys.stderr)
                return 1

            files_to_download.append((repo_id, filename, xet_info, repo_type))

        else:
            # 批量下载: user/repo + --include pattern
            if not args.include:
                print(f"✗ 批量下载需要 --include 参数指定文件匹配模式", file=sys.stderr)
                print(f"  示例: xet download {repo_id} --include '*.gguf'")
                return 1

            repo_label = f"datasets/{repo_id}" if repo_type == "dataset" else repo_id
            print(f"📦 仓库: {repo_label}")
            print(f"   匹配: {args.include}")

            # 列出所有文件
            all_files = list_hf_files(repo_id, repo_type, hf_token, session, hf_endpoint=hf_endpoint)
            if not all_files:
                print(f"✗ 无法列出仓库文件", file=sys.stderr)
                return 1

            # 匹配文件
            matched_files = match_files(all_files, args.include)
            if not matched_files:
                print(f"✗ 没有匹配的文件", file=sys.stderr)
                return 1

            print(f"   找到 {len(matched_files)} 个匹配文件")

            # 检测每个文件是否为 XET
            for fname in matched_files:
                xet_info = detect_xet_file(repo_id, repo_type, fname, hf_token, session, revision=args.revision, hf_endpoint=hf_endpoint)
                if xet_info:
                    files_to_download.append((repo_id, fname, xet_info, repo_type))
                else:
                    print(f"  ⊘ 跳过非 XET 文件: {fname}")

        if not files_to_download:
            print("✗ 没有可下载的 XET 文件", file=sys.stderr)
            return 1

        print(f"\n准备下载 {len(files_to_download)} 个文件")

        # 6. 获取第一个文件的 auth_url 来获取 CAS token
        first_repo, first_file, first_info, first_repo_type = files_to_download[0]
        auth_url = first_info["auth_url"]

        from xet.network.auth import XetAuth
        auth = XetAuth(hf_token=hf_token, session=session)
        token_info = auth.get_token(repo_id=first_repo, repo_type=first_repo_type, auth_url=auth_url)

        logger.info(f"获取到 CAS token, endpoint={token_info.endpoint}")

        # 7. 初始化自适应并发控制器（如果启用）
        acc = None
        if not getattr(args, 'no_adaptive_concurrency', False):
            from xet.network.adaptive_concurrency import AdaptiveConcurrencyController

            parallel_segments = getattr(args, 'parallel_segments', 1)

            # 根据并行段数调整ACC参数
            if parallel_segments > 1:
                # 多段并行：降低初始并发，避免CloudFront 403
                acc_initial = min(2, max(1, 8 // parallel_segments))
                acc_max = min(12, max(4, parallel_segments * 3))
            else:
                # 单段：使用标准并发
                acc_initial = 4
                acc_max = 12

            acc = AdaptiveConcurrencyController(
                initial=acc_initial,
                min_concurrency=1,
                max_concurrency=acc_max,
                success_threshold=0.80,
            )
            logger.info(
                f"自适应并发控制器已启用: initial={acc_initial}, max={acc_max}"
            )

        # 7.5. 初始化全局重试协调器
        from xet.network.retry_coordinator import RetryCoordinator

        retry_coordinator = RetryCoordinator(all_retry_grace=120.0)
        logger.info("[RetryCoordinator] 全局重试协调器已启用，宽限期 120 秒")

        # 8. 初始化 CAS 客户端
        cas_client = CASClient(
            endpoint=token_info.endpoint,
            access_token=token_info.access_token,
            session=session,
            auth=auth,
            repo_id=first_repo,
            acc=acc,
            retry_coordinator=retry_coordinator,
        )

        # 8.5. 初始化 Xorb 磁盘缓存
        cache_enabled = not getattr(args, 'no_cache', False)
        parallel_segments = getattr(args, 'parallel_segments', 1)

        # 分段模式禁用缓存（避免冲突）
        if parallel_segments > 1:
            cache_enabled = False
            logger.info("[Cache] 分段模式已禁用缓存")

        xorb_cache = None
        chunk_cache = None
        if cache_enabled:
            cache_dir = getattr(args, 'cache_dir', None)
            keep_cache = getattr(args, 'keep_cache', False)

            # 使用 chunk-level 缓存（新实现）
            if cache_dir:
                chunk_cache_dir = cache_dir / "chunks"
            else:
                chunk_cache_dir = Path.home() / ".xet" / "cache" / "chunks"

            chunk_cache = ChunkDiskCache(
                cache_root=chunk_cache_dir,
                capacity_bytes=10 * 1024 * 1024 * 1024  # 10GB 默认容量
            )

            if chunk_cache.enabled:
                logger.info(
                    f"[ChunkCache] Chunk-level 缓存已启用: {chunk_cache_dir} "
                    f"(容量: {chunk_cache.capacity / 1024 / 1024 / 1024:.1f}GB)"
                )

            # 保持 xorb 缓存作为回退（可选，用于渐进迁移）
            # xorb_cache = XorbDiskCache(
            #     cache_dir=cache_dir,
            #     keep_cache=keep_cache,
            #     enabled=True,
            # )

        # 9. 确定输出目录
        if args.output:
            output_base = args.output
        else:
            output_base = Path.cwd() / "downloads"

        # 只在明确是目录时创建（批量下载或未指定文件名）
        if not args.output or not args.output.suffix:
            output_base.mkdir(parents=True, exist_ok=True)

        # 9. 逐个下载文件
        success_count = 0
        interrupted = False

        for repo_id, filename, xet_info, repo_type in files_to_download:
            if interrupted:
                break

            # 确定输出路径
            if len(files_to_download) == 1 and args.output and args.output.suffix:
                # 单文件 + 指定了文件名
                output_path = args.output
            else:
                # 批量下载或指定了目录
                output_path = output_base / filename

            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 下载
            try:
                if download_single_file(repo_id, filename, xet_info, output_path, cas_client, args, repo_type, xorb_cache, chunk_cache, hf_endpoint):
                    success_count += 1
            except KeyboardInterrupt:
                interrupted = True
                print(f"\n⚠ 用户中断")
                break

        # 10. 汇总 - 使用美化输出
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()

        # 创建汇总表格
        table = Table(show_header=False, box=None)
        table.add_column("状态", style="bold")
        table.add_column("数量", justify="right")

        table.add_row("✓ 成功", f"[green]{success_count}[/green]")

        if success_count < len(files_to_download):
            failed_count = len(files_to_download) - success_count
            table.add_row("✗ 失败", f"[red]{failed_count}[/red]")
            table.add_row("", "")
            table.add_row("💡 提示", "[yellow]已保存断点，重新运行相同命令即可续传[/yellow]")

        table.add_row("", "")
        table.add_row("📦 总计", f"[cyan]{len(files_to_download)}[/cyan]")

        console.print(Panel(table, title="[bold cyan]批量下载汇总[/bold cyan]", border_style="cyan"))

        # 11. 清理缓存（如果不保留）
        if xorb_cache:
            xorb_cache.cleanup()

        return 0 if success_count == len(files_to_download) else 1

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
