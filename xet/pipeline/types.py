"""Pipeline 层核心数据结构。

定义 Pipeline Layer 使用的数据类型，包括下载任务、checkpoint 等。
"""
from dataclasses import dataclass, field
from typing import Set, Dict, Optional

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
class TermHashRecord:
    """单个 term 的 SHA256 校验记录。

    在组装时计算并持久化，用于后续的 verify 和 repair 操作。

    Attributes:
        term_index: term 索引
        sha256: SHA256(segment) 十六进制字符串
        file_offset: 该 term 在最终文件中的起始偏移
        unpacked_length: segment 长度（用于读取文件指定范围）
        xorb_hash: 来源 xorb hash（repair 时需要下载）
    """
    term_index: int
    sha256: str
    file_offset: int
    unpacked_length: int
    xorb_hash: str


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
        per_term_hashes: term 级 SHA256 校验记录（用于 verify/repair）
        expected_sha256: 服务器提供的文件级 SHA256（验证锚点）
        confirmed_bytes: 上次保存时确认已写入磁盘的字节数（续传校验用）
    """
    file_hash: str
    completed_xorbs: Set[str] = field(default_factory=set)
    completed_terms: Set[tuple] = field(default_factory=set)  # {(term_idx, xorb_hash)}
    last_term_index: int = -1
    timestamp: int = 0
    version: int = 5  # v5: 新增 confirmed_bytes
    per_term_hashes: Dict[int, TermHashRecord] = field(default_factory=dict)
    expected_sha256: str = ""  # 服务器提供的文件级 SHA256（验证锚点）
    confirmed_bytes: int = 0  # 续传时验证写入量的基准

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

    def mark_term_completed(self, term_idx: int, xorb_hash: str,
                            confirmed_bytes: int = 0) -> None:
        """标记一个 term 为已完成。

        Args:
            term_idx: term 索引
            xorb_hash: term 所属的 xorb hash
            confirmed_bytes: 当前已写入文件的总字节数（用于续传校验）
        """
        self.completed_terms.add((term_idx, xorb_hash))
        self.last_term_index = max(self.last_term_index, term_idx)
        if confirmed_bytes > self.confirmed_bytes:
            self.confirmed_bytes = confirmed_bytes

    def record_term_hash(self, term_index: int, sha256: str,
                         file_offset: int, unpacked_length: int,
                         xorb_hash: str) -> None:
        """记录一个 term 的 SHA256 校验值。

        Args:
            term_index: term 索引
            sha256: SHA256(segment) 十六进制字符串
            file_offset: 该 term 在文件中的起始偏移
            unpacked_length: segment 长度
            xorb_hash: 来源 xorb hash
        """
        self.per_term_hashes[term_index] = TermHashRecord(
            term_index=term_index,
            sha256=sha256,
            file_offset=file_offset,
            unpacked_length=unpacked_length,
            xorb_hash=xorb_hash,
        )

    def has_per_term_hashes(self) -> bool:
        """检查是否包含 per-term 校验存档。

        Returns:
            True 如果包含 term 级校验记录
        """
        return len(self.per_term_hashes) > 0

    def get_term_hash(self, term_index: int) -> Optional[TermHashRecord]:
        """获取指定 term 的校验记录。

        Args:
            term_index: term 索引

        Returns:
            TermHashRecord 或 None
        """
        return self.per_term_hashes.get(term_index)

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
        result = {
            "file_hash": self.file_hash,
            "completed_xorbs": list(self.completed_xorbs),
            "completed_terms": [list(t) for t in self.completed_terms],
            "last_term_index": self.last_term_index,
            "timestamp": self.timestamp,
            "version": self.version,
            "per_term_hashes": {
                str(k): {
                    "term_index": v.term_index,
                    "sha256": v.sha256,
                    "file_offset": v.file_offset,
                    "unpacked_length": v.unpacked_length,
                    "xorb_hash": v.xorb_hash,
                }
                for k, v in self.per_term_hashes.items()
            },
        }
        if self.expected_sha256:
            result["expected_sha256"] = self.expected_sha256
        if self.confirmed_bytes:
            result["confirmed_bytes"] = self.confirmed_bytes
        return result

    @staticmethod
    def from_dict(data: dict) -> "ReconstructionCheckpoint":
        """从字典反序列化。"""
        # 兼容 v1 格式（无 term 信息）
        completed_terms = set()
        if "completed_terms" in data:
            completed_terms = {tuple(t) for t in data["completed_terms"]}

        # 兼容 v1/v2 格式（无 per_term_hashes）
        per_term_hashes = {}
        if "per_term_hashes" in data:
            for k, v in data["per_term_hashes"].items():
                per_term_hashes[int(k)] = TermHashRecord(
                    term_index=v.get("term_index", int(k)),
                    sha256=v["sha256"],
                    file_offset=v["file_offset"],
                    unpacked_length=v["unpacked_length"],
                    xorb_hash=v["xorb_hash"],
                )

        return ReconstructionCheckpoint(
            file_hash=data["file_hash"],
            completed_xorbs=set(data.get("completed_xorbs", [])),
            completed_terms=completed_terms,
            last_term_index=data.get("last_term_index", -1),
            timestamp=data.get("timestamp", 0),
            version=data.get("version", 1),
            per_term_hashes=per_term_hashes,
            expected_sha256=data.get("expected_sha256", ""),
            confirmed_bytes=data.get("confirmed_bytes", 0),
        )
