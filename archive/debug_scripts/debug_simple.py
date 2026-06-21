#!/usr/bin/env python3
"""简化版：调试 chunk 缓存问题的工具。

直接调用现有的下载逻辑，增加详细日志。
"""
import json
import logging
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,  # 使用 DEBUG 级别
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# 强制启用 CacheAdapter 的日志
logging.getLogger('xet.pipeline.chunk_cache_adapter').setLevel(logging.INFO)


def main():
    """主函数：下载文件并分析 chunk 缓存日志。"""
    import argparse

    parser = argparse.ArgumentParser(description="调试 chunk 缓存问题")
    parser.add_argument("--repo", default="xet-team/Granite", help="仓库名")
    parser.add_argument(
        "--path",
        default="granite-embedding/granite-embedding-97M-multilingual-r2-Q4_K_M.gguf",
        help="文件路径"
    )
    parser.add_argument("--output", default="debug_download.gguf", help="输出文件")

    args = parser.parse_args()

    logger.info("="*60)
    logger.info("🔍 Chunk 缓存调试工具")
    logger.info("="*60)
    logger.info(f"仓库: {args.repo}")
    logger.info(f"路径: {args.path}")
    logger.info(f"输出: {args.output}")
    logger.info("")

    # 清除已有的 chunk 缓存
    import shutil
    chunk_cache_dir = Path.home() / ".xet" / "cache" / "chunks"
    if chunk_cache_dir.exists():
        logger.info(f"🗑️  清除现有 chunk 缓存: {chunk_cache_dir}")
        shutil.rmtree(chunk_cache_dir)
        logger.info("")

    # 直接使用 xet_dl.py 的下载逻辑
    logger.info("📥 开始下载...")
    logger.info("  (观察 [CacheAdapter] 日志以分析 chunk 缓存问题)")
    logger.info("")

    # 导入并调用 download 命令
    from xet.cli.commands.download import handle_download
    from xet.cli.config_manager import ConfigManager

    config = ConfigManager()

    # 准备参数
    class Args:
        def __init__(self):
            self.repo = args.repo
            self.path = args.path
            self.output = args.output
            self.resume = False
            self.checkpoint = True
            self.parallel = 5
            self.buffer_mb = 64
            self.parallel_write = False
            self.optimize_hosts = False
            self.max_mirrors = 3
            self.proxy = None

    download_args = Args()

    try:
        handle_download(download_args, config)
        logger.info("\n✅ 下载完成")
    except Exception as e:
        logger.error(f"\n❌ 下载失败: {e}", exc_info=True)
        return 1

    # 分析日志文件
    logger.info("\n" + "="*60)
    logger.info("📊 分析 chunk 缓存日志")
    logger.info("="*60)

    log_dir = Path.home() / ".xet" / "logs"
    if not log_dir.exists():
        logger.warning("未找到日志目录")
        return 0

    # 找到最新的日志文件
    log_files = sorted(log_dir.glob("xet_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        logger.warning("未找到日志文件")
        return 0

    latest_log = log_files[0]
    logger.info(f"最新日志: {latest_log}")

    # 提取 CacheAdapter 相关日志
    cache_logs = []
    with open(latest_log, 'r') as f:
        for line in f:
            if 'CacheAdapter' in line or 'chunk_cache' in line:
                cache_logs.append(line.strip())

    if cache_logs:
        logger.info(f"\n找到 {len(cache_logs)} 条 CacheAdapter 日志:\n")
        for log in cache_logs:
            print(log)
    else:
        logger.info("\n未找到 CacheAdapter 相关日志")

    return 0


if __name__ == "__main__":
    sys.exit(main())
