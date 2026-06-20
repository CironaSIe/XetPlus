"""下载断点管理。

支持下载中断后恢复，保存/加载断点信息。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional, Set
from pathlib import Path
import json
import time


@dataclass
class DownloadCheckpoint:
    """下载断点信息。

    记录下载进度，支持中断恢复。

    Attributes:
        file_path: 目标文件路径
        file_size: 文件总大小（字节）
        xet_hash: XET hash (64 字符 hex)
        sha256: 预期 SHA256 hash
        completed_terms: 已完成的 term 索引列表
        bytes_written: 已写入字节数
        last_update: 最后更新时间戳（Unix time）
    """
    file_path: str
    file_size: int
    xet_hash: str
    sha256: str
    completed_terms: List[int]
    bytes_written: int
    last_update: float

    def to_dict(self) -> dict:
        """转换为字典（用于 JSON 序列化）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DownloadCheckpoint:
        """从字典创建实例（JSON 反序列化）。"""
        return cls(**d)

    def save(self, checkpoint_path: Path) -> None:
        """保存断点到文件。

        Args:
            checkpoint_path: 断点文件路径

        Raises:
            IOError: 写入失败
        """
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        with open(checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, checkpoint_path: Path) -> Optional[DownloadCheckpoint]:
        """从文件加载断点。

        Args:
            checkpoint_path: 断点文件路径

        Returns:
            DownloadCheckpoint 实例，如果文件不存在或损坏则返回 None
        """
        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, encoding='utf-8') as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            # JSON 损坏或格式不匹配
            return None

    def is_complete(self, total_terms: int) -> bool:
        """检查是否所有 terms 都已完成。

        Args:
            total_terms: 总 term 数量

        Returns:
            True 表示全部完成
        """
        return len(self.completed_terms) == total_terms

    def mark_term_completed(self, term_index: int, term_size: int) -> None:
        """标记一个 term 为已完成。

        Args:
            term_index: term 索引
            term_size: term 数据大小（字节）
        """
        if term_index not in self.completed_terms:
            self.completed_terms.append(term_index)
            self.bytes_written += term_size
            self.last_update = time.time()

    def get_pending_terms(self, total_terms: int) -> List[int]:
        """获取待下载的 term 索引列表。

        Args:
            total_terms: 总 term 数量

        Returns:
            待下载的 term 索引列表
        """
        completed_set = set(self.completed_terms)
        return [i for i in range(total_terms) if i not in completed_set]


class CheckpointManager:
    """断点管理器。

    负责断点的保存、加载、验证和清理。

    Example:
        >>> manager = CheckpointManager(Path("output.bin"))
        >>>
        >>> # 保存断点
        >>> checkpoint = DownloadCheckpoint(...)
        >>> manager.save_checkpoint(checkpoint)
        >>>
        >>> # 恢复下载
        >>> checkpoint = manager.load_checkpoint()
        >>> if checkpoint and manager.verify_partial_file(checkpoint):
        ...     # 继续下载
        ...     pass
    """

    def __init__(self, file_path: Path):
        """初始化断点管理器。

        Args:
            file_path: 目标文件路径
        """
        self.file_path = file_path
        self.checkpoint_path = file_path.with_suffix(
            file_path.suffix + '.xet-checkpoint.json'
        )
        self.part_path = file_path.with_suffix(
            file_path.suffix + '.part'
        )

    def save_checkpoint(self, checkpoint: DownloadCheckpoint) -> None:
        """保存断点（原子操作）。

        使用临时文件 + 原子重命名避免损坏。

        Args:
            checkpoint: 断点信息

        Raises:
            IOError: 保存失败
        """
        # 先写入临时文件
        tmp_path = self.checkpoint_path.with_suffix('.tmp')
        checkpoint.save(tmp_path)

        # 原子重命名
        tmp_path.rename(self.checkpoint_path)

    def load_checkpoint(self) -> Optional[DownloadCheckpoint]:
        """加载断点。

        Returns:
            DownloadCheckpoint 实例，如果不存在或损坏则返回 None
        """
        return DownloadCheckpoint.load(self.checkpoint_path)

    def verify_partial_file(self, checkpoint: DownloadCheckpoint) -> bool:
        """验证部分下载的文件是否有效。

        检查 .part 文件是否存在且大小正确。

        Args:
            checkpoint: 断点信息

        Returns:
            True 表示文件有效
        """
        if not self.part_path.exists():
            return False

        # 检查文件大小
        actual_size = self.part_path.stat().st_size
        if actual_size != checkpoint.file_size:
            return False

        # TODO: 可选的增量哈希校验
        # 对于大文件，可以只校验已下载的 terms

        return True

    def clear(self) -> None:
        """清除断点文件。

        在下载完成或放弃恢复时调用。
        """
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()

    def clear_all(self) -> None:
        """清除所有临时文件（断点 + .part 文件）。

        在下载完成或重新开始时调用。
        """
        self.clear()

        if self.part_path.exists():
            self.part_path.unlink()

    def should_resume(
        self,
        xet_hash: str,
        file_size: int,
        min_completed_ratio: float = 0.1
    ) -> bool:
        """判断是否应该恢复下载。

        Args:
            xet_hash: 当前任务的 XET hash
            file_size: 当前任务的文件大小
            min_completed_ratio: 最小完成比例（低于此值则重新下载）

        Returns:
            True 表示应该恢复下载
        """
        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            return False

        # 验证是否是同一个文件
        if checkpoint.xet_hash != xet_hash:
            return False

        if checkpoint.file_size != file_size:
            return False

        # 验证 .part 文件
        if not self.verify_partial_file(checkpoint):
            return False

        # 检查完成比例
        completed_ratio = checkpoint.bytes_written / file_size
        if completed_ratio < min_completed_ratio:
            # 进度太少，重新下载更快
            return False

        return True


def create_checkpoint(
    file_path: Path,
    file_size: int,
    xet_hash: str,
    sha256: str
) -> DownloadCheckpoint:
    """工厂函数：创建新的断点。

    Args:
        file_path: 目标文件路径
        file_size: 文件总大小
        xet_hash: XET hash
        sha256: SHA256 hash

    Returns:
        DownloadCheckpoint 实例
    """
    return DownloadCheckpoint(
        file_path=str(file_path),
        file_size=file_size,
        xet_hash=xet_hash,
        sha256=sha256,
        completed_terms=[],
        bytes_written=0,
        last_update=time.time()
    )
