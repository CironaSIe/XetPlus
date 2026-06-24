"""Verify 命令实现 - 文件校验与修复。

双层验证:
  第一层: 文件级 SHA256（外部锚点，需要完整扫描文件）
  第二层: per-term 诊断（需要 checkpoint，零网络，快速定位损坏）

用法:
  xet verify <file>                文件级 SHA256 校验
  xet verify <file> --diagnose     文件级失败后做 per-term 诊断
  xet verify <file> --repair       诊断 + 修复损坏 term
"""
import logging
import sys
import json
from pathlib import Path

from xet.pipeline.file_verifier import FileVerifier, NoCheckpointError, VerifyError
from xet.pipeline.checkpoint_manager import CheckpointManager

logger = logging.getLogger(__name__)


def register_verify_command(subparsers):
    """注册 verify 子命令。"""
    parser = subparsers.add_parser(
        "verify",
        help="校验并修复文件",
        description="校验已下载文件的完整性，并可修复损坏的数据。\n\n"
                    "校验流程:\n"
                    "  1. 文件级 SHA256（对比服务器提供的期望值）\n"
                    "  2. Per-term 诊断（仅当文件级失败时，对比 checkpoint）\n\n"
                    "修复流程:\n"
                    "  只重新下载损坏 term 对应的 xorb（比全量重下快得多）",
    )

    parser.add_argument(
        "file",
        help="待校验的文件路径",
        type=Path,
    )

    parser.add_argument(
        "--diagnose",
        help="文件级校验失败后执行 per-term 诊断（需要 checkpoint）",
        action="store_true",
    )

    parser.add_argument(
        "--repair",
        help="诊断 + 修复损坏的 term（需要网络连接和 CAS token）",
        action="store_true",
    )

    parser.add_argument(
        "--checkpoint",
        help="Checkpoint 文件路径（默认自动检测）",
        type=Path,
    )

    parser.add_argument(
        "-c", "--concurrency",
        help="修复时并行下载数（默认: 4）",
        type=int,
        default=4,
    )

    parser.add_argument(
        "--token",
        help="HF Token（修复时需要，覆盖配置）",
    )

    parser.add_argument(
        "--endpoint",
        help="CAS 服务器地址（修复时覆盖配置）",
    )

    parser.set_defaults(func=verify_command)


def find_checkpoint(file_path: Path) -> Path:
    """根据文件路径查找对应的 checkpoint。"""
    sidecar = file_path.with_suffix(file_path.suffix + ".xet_verify")
    if sidecar.exists():
        try:
            with open(sidecar, 'r', encoding='utf-8') as f:
                info = json.load(f)
            file_hash = info.get('file_hash', '')
            checkpoint_path = Path.home() / ".xet" / "checkpoints" / f"{file_hash}.json"
            if checkpoint_path.exists():
                return checkpoint_path
        except Exception:
            pass

    checkpoint_dir = Path.home() / ".xet" / "checkpoints"
    if not checkpoint_dir.exists():
        raise FileNotFoundError(
            f"Checkpoint 目录不存在: {checkpoint_dir}\n"
            f"请确保文件是通过 xet download 下载的"
        )

    candidates = sorted(checkpoint_dir.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(
            f"未找到 checkpoint 文件。\n"
            f"该文件可能不是通过 xet download 下载的，"
            f"或者 checkpoint 已被清理。\n"
            f"请使用 --checkpoint 参数指定 checkpoint 文件路径"
        )

    if len(candidates) == 1:
        return candidates[0]

    details = "\n".join(f"    {c.name}" for c in candidates)
    raise FileNotFoundError(
        f"找到多个 checkpoint 候选:\n{details}\n"
        f"请使用 --checkpoint 参数指定正确的 checkpoint 文件"
    )


def verify_command(args):
    """执行 verify 命令。"""
    file_path: Path = args.file

    if not file_path.exists():
        print(f"✗ 文件不存在: {file_path}", file=sys.stderr)
        return 1

    # 确定 checkpoint 路径
    checkpoint_path = args.checkpoint
    if checkpoint_path and not checkpoint_path.exists():
        print(f"✗ Checkpoint 文件不存在: {checkpoint_path}", file=sys.stderr)
        return 1

    if not checkpoint_path:
        try:
            checkpoint_path = find_checkpoint(file_path)
        except FileNotFoundError as e:
            print(f"✗ {e}", file=sys.stderr)
            return 1

    file_hash = checkpoint_path.stem
    if len(file_hash) != 64:
        print(f"✗ 无效的 checkpoint 文件名（不是 64 字符 hash）", file=sys.stderr)
        return 1

    checkpoint_manager = CheckpointManager(checkpoint_path)
    temp_dir = Path.cwd() / ".xet_temp"

    # 修复模式需要 CAS 客户端
    cas_client = None
    if args.repair:
        from xet.network.cas_client import CASClient
        from xet.cli.config_manager import ConfigManager
        from xet.network.auth import XetAuth
        from xet.network.host_optimizer import create_robust_session

        config = ConfigManager()
        hf_token = args.token or config.get_token()
        endpoint = args.endpoint or config.get_endpoint()

        if not hf_token:
            print("✗ 修复需要 HF Token。", file=sys.stderr)
            print("  设置: xet config xet.token YOUR_TOKEN", file=sys.stderr)
            return 1

        session = create_robust_session()
        auth = XetAuth(hf_token=hf_token, session=session)

        try:
            token_info = auth.get_token(
                repo_id="mykor/granite-embedding-97m-multilingual-r2-GGUF",
                repo_type="model",
            )
        except Exception as e:
            print(f"✗ 获取 CAS token 失败: {e}", file=sys.stderr)
            return 1

        cas_client = CASClient(
            endpoint=token_info.endpoint,
            access_token=token_info.access_token,
            session=session, auth=auth,
            repo_id="mykor/granite-embedding-97m-multilingual-r2-GGUF",
        )

    verifier = FileVerifier(
        output_path=file_path,
        file_hash=file_hash,
        temp_dir=temp_dir,
        checkpoint_manager=checkpoint_manager,
        cas_client=cas_client,
        max_workers=args.concurrency,
    )

    print(f"校验文件: {file_path}")
    print(f"  Checkpoint: {checkpoint_path}")

    try:
        report = verifier.verify(diagnose=args.diagnose or args.repair)
    except NoCheckpointError as e:
        print(f"\n  ✗ {e}", file=sys.stderr)
        return 1
    except VerifyError as e:
        print(f"\n  ✗ 校验错误: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"\n  ✗ {e}", file=sys.stderr)
        return 1

    print(f"\n校验结果:\n{report}")

    if report.is_healthy:
        if report.file_sha256_ok is True:
            print(f"\n  💡 文件完成且通过校验，可以安全使用")
        return 0

    # 文件级失败 + 有 checkpoint + 无诊断损坏项 → 需要全量重下
    if report.file_sha256_ok is False and report.has_checkpoint and not report.corrupt_terms:
        print(f"\n  ⚠ 文件级 SHA256 不匹配，但 per-term 诊断所有 term 一致。")
        print(f"    这可能意味着下载时服务器返回了错误数据。")
        print(f"    建议:\n"
              f"      xet download <原始路径> (重新下载整个文件)")

    # 有损坏 term → 可以修复
    if args.repair and report.corrupt_terms:
        print(f"\n  正在修复 {len(report.corrupt_terms)} 个损坏 term...")
        try:
            success = verifier.repair(report)
            if success:
                print(f"\n  ✅ 修复完成，文件已通过校验")
                return 0
            else:
                print(f"\n  ⚠ 部分修复失败，检查日志获取详情", file=sys.stderr)
                return 1
        except Exception as e:
            print(f"\n  ✗ 修复失败: {e}", file=sys.stderr)
            return 1

    if not args.repair and report.corrupt_terms:
        print(f"\n  提示: 运行 'xet verify --repair {file_path}' 修复损坏数据")
    return 1
