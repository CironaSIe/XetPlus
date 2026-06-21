"""Pipeline 层核心数据结构。

定义 Pipeline Layer 使用的数据类型，包括下载任务、checkpoint 等。
"""
from dataclasses import dataclass, field
from typing import Set

from xet.protocol.types import HttpRange


@dataclass
class XorbDownloadTask:
    """Xorb 下载任务。

    表示一个待下载的 xorb，包含其 hash、URL 和字节范围。

    Attributes:
        xorb_hash: Xorb 的 MerkleHash（64 字符 hex）
        url: Presigned 下载 URL
        url_range: 需要下载的字节范围
    """
    xorb_hash: str
    url: str
    url_range: HttpRange

    def __post_init__(self):
        """验证数据。"""
        if len(self.xorb_hash) != 64:
            raise ValueError(f"xorb_hash 必须是 64 字符: {self.xorb_hash}")

        if not self.url:
            raise ValueError("url 不能为空")

    def size(self) -> int:
        """返回下载大小（字节）。"""
        return self.url_range.length()


@dataclass
class ReconstructionCheckpoint:
    """文件重建 checkpoint。

    记录文件重建进度，支持中断后恢复。

    Attributes:
        file_hash: 文件的 MerkleHash（64 字符 hex）
        completed_xorbs: 已成功下载的 xorb hash 集合
        completed_terms: 已完成的 term 索引集合 (term_idx, xorb_hash)
        last_term_index: 最后完成的 term 索引（用于快速恢复）
        timestamp: checkpoint 更新时间戳（秒）
        version: checkpoint 格式版本
    """
    file_hash: str
    completed_xorbs: Set[str] = field(default_factory=set)
    completed_terms: Set[tuple] = field(default_factory=set)  # {(term_idx, xorb_hash)}
    last_term_index: int = -1
    timestamp: int = 0
    version: int = 2  # 升级到 v2（支持 term 级）

    def __post_init__(self):
        """验证数据。"""
        if len(self.file_hash) != 64:
            raise ValueError(f"file_hash 必须是 64 字符: {self.file_hash}")

    def mark_completed(self, xorb_hash: str) -> None:
        """标记一个 xorb 为已完成。

        Args:
            xorb_hash: 已下载的 xorb hash
        """
        self.completed_xorbs.add(xorb_hash)

    def mark_term_completed(self, term_idx: int, xorb_hash: str) -> None:
        """标记一个 term 为已完成。

        Args:
            term_idx: term 索引
            xorb_hash: term 所属的 xorb hash
        """
        self.completed_terms.add((term_idx, xorb_hash))
        self.last_term_index = max(self.last_term_index, term_idx)

    def is_term_completed(self, term_idx: int) -> bool:
        """检查一个 term 是否已完成。

        Args:
            term_idx: 要检查的 term 索引

        Returns:
            True 如果已完成
        """
        return any(idx == term_idx for idx, _ in self.completed_terms)

    def is_completed(self, xorb_hash: str) -> bool:
        """检查一个 xorb 是否已完成。

        Args:
            xorb_hash: 要检查的 xorb hash

        Returns:
            True 如果已完成
        """
        return xorb_hash in self.completed_xorbs

    def completion_count(self) -> int:
        """返回已完成的 xorb 数量。"""
        return len(self.completed_xorbs)

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "file_hash": self.file_hash,
            "completed_xorbs": list(self.completed_xorbs),
            "completed_terms": [list(t) for t in self.completed_terms],  # [(idx, hash), ...]
            "last_term_index": self.last_term_index,
            "timestamp": self.timestamp,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: dict) -> "ReconstructionCheckpoint":
        """从字典反序列化。"""
        # 兼容 v1 格式（无 term 信息）
        completed_terms = set()
        if "completed_terms" in data:
            completed_terms = {tuple(t) for t in data["completed_terms"]}

        return ReconstructionCheckpoint(
            file_hash=data["file_hash"],
            completed_xorbs=set(data.get("completed_xorbs", [])),
            completed_terms=completed_terms,
            last_term_index=data.get("last_term_index", -1),
            timestamp=data.get("timestamp", 0),
            version=data.get("version", 1),
        )
