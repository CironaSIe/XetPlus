"""Xorb 磁盘缓存管理器。

缓存下载的 xorb 数据到磁盘，加速重复下载。

设计:
- 缓存粒度: 完整 xorb（压缩后的字节数据）
- 缓存路径: ~/.xet/cache/xorbs/{xorb_hash}.xorb
- 大小验证: 防止部分下载污染缓存
- 自动清理: 下载完成后可选清理

参考: ~/xet.py/xet/reconstructor.py (_load_from_disk_cache)
"""
import logging
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)


class XorbDiskCache:
    """Xorb 磁盘缓存管理器。

    Attributes:
        cache_dir: 缓存目录路径
        keep_cache: 下载完成后是否保留缓存
        written_xorbs: 本次写入的 xorb 集合（用于清理）
    """

    DEFAULT_CACHE_DIR = Path.home() / ".xet" / "cache" / "xorbs"

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        keep_cache: bool = False,
        enabled: bool = True,
    ):
        """初始化 Xorb 磁盘缓存。

        Args:
            cache_dir: 缓存目录（默认 ~/.xet/cache/xorbs）
            keep_cache: 下载完成后是否保留缓存
            enabled: 是否启用缓存（分段模式需要禁用）
        """
        self.enabled = enabled
        self.keep_cache = keep_cache
        self.written_xorbs: Set[str] = set()

        if enabled:
            self.cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                logger.debug(f"[XorbCache] 缓存目录: {self.cache_dir}")
            except OSError as e:
                logger.warning(f"[XorbCache] 无法创建缓存目录，禁用缓存: {e}")
                self.enabled = False
        else:
            self.cache_dir = None
            logger.debug("[XorbCache] 缓存已禁用")

    def get(
        self,
        xorb_hash: str,
        expected_size: int = 0,
    ) -> Optional[bytes]:
        """从缓存加载 xorb 数据。

        Args:
            xorb_hash: Xorb 的 MerkleHash
            expected_size: 期望的最小数据大小（字节）
                如果缓存文件小于此值，视为不完整并删除

        Returns:
            缓存的 xorb 数据（字节），缓存未命中返回 None
        """
        if not self.enabled or self.cache_dir is None:
            return None

        cache_path = self.cache_dir / f"{xorb_hash}.xorb"

        if not cache_path.exists():
            logger.debug(f"[XorbCache] 缓存未命中: {xorb_hash[:16]}...")
            return None

        try:
            # 检查文件大小
            file_size = cache_path.stat().st_size

            if expected_size > 0 and file_size < expected_size:
                logger.warning(
                    f"[XorbCache] 缓存文件不完整（{file_size} < {expected_size} bytes），删除: "
                    f"{xorb_hash[:16]}..."
                )
                cache_path.unlink()
                return None

            # 读取缓存数据
            data = cache_path.read_bytes()
            logger.info(
                f"[XorbCache] ✅ 缓存命中: {xorb_hash[:16]}... ({len(data)} bytes)"
            )
            return data

        except Exception as e:
            logger.warning(
                f"[XorbCache] 读取缓存失败（将重新下载）: {xorb_hash[:16]}... - {e}"
            )
            # 删除损坏的缓存文件
            try:
                if cache_path.exists():
                    cache_path.unlink()
            except OSError:
                pass
            return None

    def put(
        self,
        xorb_hash: str,
        data: bytes,
    ) -> None:
        """保存 xorb 数据到缓存。

        Args:
            xorb_hash: Xorb 的 MerkleHash
            data: Xorb 数据（压缩后的字节）
        """
        if not self.enabled or self.cache_dir is None:
            return

        cache_path = self.cache_dir / f"{xorb_hash}.xorb"

        try:
            cache_path.write_bytes(data)
            self.written_xorbs.add(xorb_hash)
            logger.debug(
                f"[XorbCache] 缓存保存: {xorb_hash[:16]}... ({len(data)} bytes)"
            )

        except Exception as e:
            logger.warning(f"[XorbCache] 缓存保存失败: {xorb_hash[:16]}... - {e}")

    def cleanup(self) -> None:
        """清理本次下载写入的缓存文件（下载完成后调用）。

        只清理本次下载新写入的缓存，不影响已有缓存。
        """
        if not self.enabled or self.keep_cache or self.cache_dir is None:
            return

        if not self.written_xorbs:
            return

        count = 0
        for xorb_hash in self.written_xorbs:
            cache_path = self.cache_dir / f"{xorb_hash}.xorb"
            try:
                if cache_path.exists():
                    cache_path.unlink()
                    count += 1
            except OSError as e:
                logger.debug(f"[XorbCache] 删除缓存失败: {xorb_hash[:16]}... - {e}")

        if count > 0:
            logger.info(f"[XorbCache] 清理缓存: 删除 {count} 个文件")

        self.written_xorbs.clear()

    def get_cache_stats(self) -> dict:
        """获取缓存统计信息。

        Returns:
            {
                "total_files": 缓存文件总数,
                "total_size_bytes": 缓存总大小（字节）,
                "cache_dir": 缓存目录路径,
            }
        """
        if not self.enabled or self.cache_dir is None:
            return {
                "total_files": 0,
                "total_size_bytes": 0,
                "cache_dir": None,
            }

        try:
            cache_files = list(self.cache_dir.glob("*.xorb"))
            total_size = sum(f.stat().st_size for f in cache_files)

            return {
                "total_files": len(cache_files),
                "total_size_bytes": total_size,
                "cache_dir": str(self.cache_dir),
            }

        except Exception as e:
            logger.warning(f"[XorbCache] 获取缓存统计失败: {e}")
            return {
                "total_files": 0,
                "total_size_bytes": 0,
                "cache_dir": str(self.cache_dir),
            }
