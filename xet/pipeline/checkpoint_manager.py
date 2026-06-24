"""Checkpoint 管理器 - 支持断点续传。

管理文件重建的 checkpoint，记录已完成的 xorb，支持中断后恢复。
"""
import json
import time
import threading
import logging
from pathlib import Path
from typing import Optional

from xet.pipeline.types import ReconstructionCheckpoint

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Reconstruction checkpoint 管理器。

    负责：
    - 保存/加载 checkpoint 到 JSON 文件
    - 增量更新已完成的 xorb
    - 线程安全的文件 I/O

    Checkpoint 文件格式：
    {
        "file_hash": "...",
        "completed_xorbs": ["xorb1", "xorb2", ...],
        "timestamp": 1234567890,
        "version": 1
    }
    """

    def __init__(self, checkpoint_path: Optional[Path] = None):
        """初始化 checkpoint 管理器。

        Args:
            checkpoint_path: checkpoint 文件路径（None 表示禁用 checkpoint）
        """
        self.checkpoint_path = checkpoint_path
        self._lock = threading.Lock()
        self._cache: Optional[ReconstructionCheckpoint] = None
        self._last_save_time: float = 0.0  # 时间兜底：上次保存的 unix 时间戳

    def load(self, file_hash: str) -> Optional[ReconstructionCheckpoint]:
        """加载指定文件的 checkpoint。

        Args:
            file_hash: 文件的 MerkleHash

        Returns:
            ReconstructionCheckpoint 对象，如果不存在或损坏则返回 None
        """
        if not self.checkpoint_path or not self.checkpoint_path.exists():
            return None

        with self._lock:
            try:
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 检查文件 hash 是否匹配
                if data.get('file_hash') != file_hash:
                    logger.debug(
                        f"[Checkpoint] 文件 hash 不匹配: "
                        f"期望 {file_hash[:16]}..., 实际 {data.get('file_hash', '')[:16]}..."
                    )
                    return None

                checkpoint = ReconstructionCheckpoint(
                    file_hash=data['file_hash'],
                    completed_xorbs=set(data.get('completed_xorbs', [])),
                    completed_terms=set(tuple(t) for t in data.get('completed_terms', [])),
                    last_term_index=data.get('last_term_index', -1),
                    timestamp=data.get('timestamp', 0),
                    version=data.get('version', 1),
                )

                logger.info(
                    f"[Checkpoint] 加载成功: {checkpoint.completion_count()} 个 xorb, "
                    f"{len(checkpoint.completed_terms)} 个 term 已完成 "
                    f"(last_term={checkpoint.last_term_index})"
                )

                # 缓存
                self._cache = checkpoint
                return checkpoint

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"[Checkpoint] 加载失败: {e}")
                return None

    def save(self, checkpoint: ReconstructionCheckpoint) -> None:
        """保存 checkpoint 到文件。

        Args:
            checkpoint: 要保存的 checkpoint 对象
        """
        if not self.checkpoint_path:
            return

        with self._lock:
            try:
                # 确保目录存在
                self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

                # 写入 JSON
                with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                    json.dump(
                        {
                            'file_hash': checkpoint.file_hash,
                            'completed_xorbs': list(checkpoint.completed_xorbs),
                            'completed_terms': [list(t) for t in checkpoint.completed_terms],
                            'last_term_index': checkpoint.last_term_index,
                            'timestamp': checkpoint.timestamp,
                            'version': checkpoint.version,
                        },
                        f,
                        indent=2,
                    )

                # 更新缓存
                self._cache = checkpoint

                logger.debug(
                    f"[Checkpoint] 保存成功: {checkpoint.completion_count()} 个 xorb"
                )

            except (IOError, OSError) as e:
                logger.error(f"[Checkpoint] 保存失败: {e}")

    def mark_completed(self, file_hash: str, xorb_hash: str) -> None:
        """标记一个 xorb 为已完成并保存。

        Args:
            file_hash: 文件的 MerkleHash
            xorb_hash: 已完成的 xorb hash
        """
        with self._lock:
            # 尝试从缓存加载
            checkpoint = self._cache if self._cache and self._cache.file_hash == file_hash else None

            # 如果缓存无效，尝试从文件加载（无锁）
            if not checkpoint:
                checkpoint = self._load_unsafe(file_hash)

            # 如果仍然没有，创建新的
            if not checkpoint:
                checkpoint = ReconstructionCheckpoint(
                    file_hash=file_hash,
                    completed_xorbs=set(),
                    timestamp=int(time.time()),
                )

            # 标记完成
            checkpoint.mark_completed(xorb_hash)
            checkpoint.timestamp = int(time.time())

            # 保存（无锁）
            self._save_unsafe(checkpoint)

    def mark_term_completed(self, file_hash: str, term_idx: int, xorb_hash: str,
                            save_interval: int = 1) -> None:
        """标记一个 term 为已完成并定期保存。

        Args:
            file_hash: 文件的 MerkleHash
            term_idx: term 索引
            xorb_hash: term 所属的 xorb hash
            save_interval: 保存间隔（每 N 个 term 保存一次，默认 1）
        """
        with self._lock:
            # 尝试从缓存加载
            checkpoint = self._cache if self._cache and self._cache.file_hash == file_hash else None

            # 如果缓存无效，尝试从文件加载（无锁）
            if not checkpoint:
                checkpoint = self._load_unsafe(file_hash)

            # 如果仍然没有，创建新的
            if not checkpoint:
                checkpoint = ReconstructionCheckpoint(
                    file_hash=file_hash,
                    completed_xorbs=set(),
                    timestamp=int(time.time()),
                )

            # 标记 term 完成
            checkpoint.mark_term_completed(term_idx, xorb_hash)
            checkpoint.timestamp = int(time.time())

            # 双重保存策略：
            # 1. 计数触发：每 N 个 term 保存一次（默认每个 term 都保存）
            # 2. 时间兜底：超过 5 秒未保存则强制保存（防止长 xorb 下载期间丢失进度）
            now = time.time()
            should_save = (
                term_idx % save_interval == 0 or term_idx == 0
                or (now - self._last_save_time) > 5.0
            )
            if should_save:
                self._save_unsafe(checkpoint)
                self._last_save_time = now
                logger.debug(
                    f"[Checkpoint] Term {term_idx} 已保存 "
                    f"({len(checkpoint.completed_terms)} terms total)"
                )
            else:
                # 只更新缓存
                self._cache = checkpoint

    def clear(self, file_hash: str) -> None:
        """清除指定文件的 checkpoint。

        Args:
            file_hash: 文件的 MerkleHash
        """
        if not self.checkpoint_path or not self.checkpoint_path.exists():
            return

        with self._lock:
            try:
                # 检查文件 hash 是否匹配
                checkpoint = self._load_unsafe(file_hash)
                if checkpoint and checkpoint.file_hash == file_hash:
                    self.checkpoint_path.unlink()
                    self._cache = None
                    logger.info(f"[Checkpoint] 清除成功: {file_hash[:16]}...")

            except Exception as e:
                logger.warning(f"[Checkpoint] 清除失败: {e}")

    def _load_unsafe(self, file_hash: str) -> Optional[ReconstructionCheckpoint]:
        """加载 checkpoint（不加锁，仅供内部使用）。

        Args:
            file_hash: 文件的 MerkleHash

        Returns:
            ReconstructionCheckpoint 对象或 None
        """
        if not self.checkpoint_path or not self.checkpoint_path.exists():
            return None

        try:
            with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if data.get('file_hash') != file_hash:
                return None

            return ReconstructionCheckpoint(
                file_hash=data['file_hash'],
                completed_xorbs=set(data.get('completed_xorbs', [])),
                completed_terms=set(tuple(t) for t in data.get('completed_terms', [])),
                last_term_index=data.get('last_term_index', -1),
                timestamp=data.get('timestamp', 0),
                version=data.get('version', 1),
            )

        except Exception:
            return None

    def _save_unsafe(self, checkpoint: ReconstructionCheckpoint) -> None:
        """保存 checkpoint（不加锁，仅供内部使用）。

        Args:
            checkpoint: 要保存的 checkpoint 对象
        """
        if not self.checkpoint_path:
            return

        try:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        'file_hash': checkpoint.file_hash,
                        'completed_xorbs': list(checkpoint.completed_xorbs),
                        'completed_terms': [list(t) for t in checkpoint.completed_terms],
                        'last_term_index': checkpoint.last_term_index,
                        'timestamp': checkpoint.timestamp,
                        'version': checkpoint.version,
                    },
                    f,
                    indent=2,
                )

            self._cache = checkpoint

        except Exception as e:
            logger.error(f"[Checkpoint] 保存失败: {e}")
