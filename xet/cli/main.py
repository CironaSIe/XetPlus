"""XET 命令行工具主入口 - 改进日志控制。"""
import sys
import os
import logging
import argparse
from pathlib import Path
from datetime import datetime

from xet.cli.commands import (
    register_download_command,
    register_info_command,
    register_config_command,
    register_optimize_command,
)


def setup_logging(verbose: int = 0, log_file: str = None):
    """配置日志系统。

    Args:
        verbose: 控制台详细级别
            0 = WARNING
            1 = INFO
            2 = DEBUG
        log_file: 日志文件路径（可选）
                 如果指定，文件始终记录 DEBUG 级别
    """
    # 根 logger 设置为 DEBUG（让所有日志都能通过）
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 清除已有的 handlers
    root_logger.handlers.clear()

    # 1. 控制台 handler - 根据 verbose 设置级别
    console_handler = logging.StreamHandler(sys.stderr)

    if verbose == 0:
        console_level = logging.WARNING
    elif verbose == 1:
        console_level = logging.INFO
    else:
        console_level = logging.DEBUG

    console_handler.setLevel(console_level)
    console_handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s")
    )
    root_logger.addHandler(console_handler)

    # 2. 文件 handler - 始终记录 DEBUG 级别（完整日志）
    if log_file:
        log_path = Path(log_file)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)  # 文件始终记录完整日志
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
            root_logger.addHandler(file_handler)

            # 记录日志位置（输出到控制台和文件）
            logging.info(f"日志文件: {log_path}")
        except Exception as e:
            # 日志文件创建失败时，输出警告到 stderr
            print(f"⚠️  日志文件创建失败: {log_path} ({e})", file=sys.stderr)
            print(f"   日志将仅输出到控制台", file=sys.stderr)

    # 3. 抑制第三方库的 DEBUG 日志（即使控制台设置为 DEBUG）
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("urllib3.util.retry").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def get_default_log_file() -> str:
    """获取默认日志文件路径。

    Returns:
        ~/.xet/logs/xet_YYYYMMDD_HHMMSS.log
    """
    log_dir = Path.home() / ".xet" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧日志（保留最近 10 个）
    log_files = sorted(log_dir.glob("xet_*.log"))
    if len(log_files) > 10:
        for old_log in log_files[:-10]:
            try:
                old_log.unlink()
            except OSError:
                pass

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(log_dir / f"xet_{timestamp}.log")


def main():
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        prog="xet",
        description="XET+ 文件下载工具 - 支持 HuggingFace XET 协议高速下载",
        epilog="使用 'xet <command> --help' 查看命令帮助",
    )

    parser.add_argument(
        "-v", "--verbose",
        help="详细输出（可多次使用：-v=INFO, -vv=DEBUG）",
        action="count",
        default=0,
    )

    parser.add_argument(
        "--log-level",
        help="控制台日志级别（覆盖 -v）",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    parser.add_argument(
        "--log-file",
        help="日志文件路径（默认: ~/.xet/logs/xet_YYYYMMDD_HHMMSS.log）",
    )

    parser.add_argument(
        "--no-log-file",
        help="禁用日志文件",
        action="store_true",
    )

    parser.add_argument(
        "--version",
        help="显示版本信息",
        action="version",
        version="xet 0.2.0 (Phase 5 + CLI Improvements)",
    )

    # 子命令
    subparsers = parser.add_subparsers(
        dest="command",
        help="可用命令",
        required=True,
    )

    # 注册子命令
    register_download_command(subparsers)
    register_info_command(subparsers)
    register_config_command(subparsers)
    register_optimize_command(subparsers)

    # 解析参数
    args = parser.parse_args()

    # 确定控制台日志级别
    if args.log_level:
        # --log-level 优先
        verbose = {"DEBUG": 2, "INFO": 1, "WARNING": 0, "ERROR": 0}.get(args.log_level, 0)
    else:
        # 使用 -v 计数
        verbose = args.verbose

    # 确定日志文件路径
    if args.no_log_file:
        log_file = None
    else:
        log_file = args.log_file or get_default_log_file()

    # 设置日志
    setup_logging(verbose=verbose, log_file=log_file)

    # 记录启动信息
    logging.debug(f"XET CLI 启动: {' '.join(sys.argv)}")
    logging.debug(f"控制台日志级别: {['WARNING', 'INFO', 'DEBUG'][min(verbose, 2)]}")
    if log_file:
        logging.debug(f"文件日志级别: DEBUG (完整)")

    # 执行命令
    try:
        exit_code = args.func(args)
        sys.exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\n⚠ 用户中断", file=sys.stderr)
        logging.info("用户中断 (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        print(f"✗ 未知错误: {e}", file=sys.stderr)
        logging.exception("未知错误")
        if verbose >= 2:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
