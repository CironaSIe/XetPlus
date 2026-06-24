"""进度跟踪器 - 实时监控下载和组装进度。

提供线程安全的进度统计，包括速度、ETA 等指标。
"""
import time
import threading
import logging
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


class ProgressTracker:
    """下载和组装进度跟踪器。

    线程安全的进度监控组件，支持：
    - 实时统计下载和组装字节数
    - 计算下载速度和 ETA
    - Xorb 级别进度（已下载/总数）
    - Segment 级别进度（当前段/总段数）
    - 回调通知机制

    Attributes:
        total_bytes: 预期总字节数（用于计算百分比）
        callback: 进度更新回调函数（接收 dict 参数）
    """

    def __init__(
        self,
        total_bytes: int = 0,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        initial_assembled: int = 0,
    ):
        """初始化进度跟踪器。

        Args:
            total_bytes: 预期总字节数（0 表示未知）
            callback: 进度更新回调函数，每次更新时调用
            initial_assembled: 初始已组装字节数（断点续传时用于恢复基线）
        """
        self.total_bytes = total_bytes
        self.callback = callback

        self._downloaded_bytes = 0
        self._assembled_bytes = initial_assembled  # 断点续传：从已有数据开始而非 0
        self._start_time = time.time()
        self._lock = threading.Lock()

        # Xorb 级别进度
        self._total_xorbs = 0
        self._completed_xorbs = 0
        self._active_xorbs = set()  # 正在下载的 xorb 哈希

        # Segment 级别进度
        self._total_segments = 0
        self._completed_segments = 0
        self._current_segment = 0

        # Term 级别进度
        self._total_terms = 0
        self._processed_terms = 0

    def set_total_bytes(self, total_bytes: int) -> None:
        """设置总字节数（延迟初始化）。

        Args:
            total_bytes: 预期总字节数
        """
        with self._lock:
            self.total_bytes = total_bytes

    def set_total_xorbs(self, total_xorbs: int) -> None:
        """设置总 xorb 数量。

        Args:
            total_xorbs: 总 xorb 数量
        """
        with self._lock:
            self._total_xorbs = total_xorbs

    def set_total_segments(self, total_segments: int) -> None:
        """设置总 segment 数量。

        Args:
            total_segments: 总 segment 数量
        """
        with self._lock:
            self._total_segments = total_segments

    def set_total_terms(self, total_terms: int) -> None:
        """设置总 term 数量。

        Args:
            total_terms: 总 term 数量
        """
        with self._lock:
            self._total_terms = total_terms

    def start_xorb_download(self, xorb_hash: str) -> None:
        """开始下载一个 xorb。

        Args:
            xorb_hash: xorb 哈希值
        """
        with self._lock:
            self._active_xorbs.add(xorb_hash)
            self._notify()

    def complete_xorb_download(self, xorb_hash: str) -> None:
        """完成一个 xorb 下载。

        Args:
            xorb_hash: xorb 哈希值
        """
        with self._lock:
            self._active_xorbs.discard(xorb_hash)
            self._completed_xorbs += 1
            self._notify()

    def increment_segments(self, n: int = 1) -> None:
        """增加已完成的 segment 数量。

        Args:
            n: 新增 segment 数量（默认 1）
        """
        with self._lock:
            self._completed_segments += n
            self._notify()

    def set_current_segment(self, segment_index: int) -> None:
        """设置当前处理的 segment 索引。

        Args:
            segment_index: segment 索引（从 0 开始）
        """
        with self._lock:
            self._current_segment = segment_index
            self._notify()

    def increment_terms(self, n: int = 1) -> None:
        """增加已处理的 term 数量。

        Args:
            n: 新增 term 数量（默认 1）
        """
        with self._lock:
            self._processed_terms += n
            self._notify()

    def increment_downloaded(self, n: int) -> None:
        """增加已下载字节数。

        Args:
            n: 新增下载字节数
        """
        with self._lock:
            self._downloaded_bytes += n
            self._notify()

    def increment_assembled(self, n: int) -> None:
        """增加已组装字节数。

        Args:
            n: 新增组装字节数
        """
        with self._lock:
            self._assembled_bytes += n
            self._notify()

    def adjust_assembled(self, delta: int) -> None:
        """调整已组装字节数（truncate 后修正基线用）。

        Args:
            delta: 修正量（可为负值）
        """
        with self._lock:
            self._assembled_bytes += delta
            self._notify()

    def get_downloaded_bytes(self) -> int:
        """获取已下载字节数。"""
        with self._lock:
            return self._downloaded_bytes

    def get_assembled_bytes(self) -> int:
        """获取已组装字节数。"""
        with self._lock:
            return self._assembled_bytes

    def get_stats(self) -> Dict[str, Any]:
        """获取当前进度统计。

        Returns:
            包含以下字段的字典：
            - downloaded_bytes: 已下载字节数
            - assembled_bytes: 已组装字节数
            - total_bytes: 总字节数
            - progress_pct: 进度百分比（0-100）
            - speed_bps: 下载速度（字节/秒）
            - eta_seconds: 预计剩余时间（秒）
            - elapsed_seconds: 已用时间（秒）
            - total_xorbs: 总 xorb 数量
            - completed_xorbs: 已完成 xorb 数量
            - active_xorbs: 正在下载的 xorb 数量
            - total_segments: 总 segment 数量
            - completed_segments: 已完成 segment 数量
            - current_segment: 当前 segment 索引
            - total_terms: 总 term 数量
            - processed_terms: 已处理 term 数量
        """
        with self._lock:
            elapsed = time.time() - self._start_time

            # 计算速度（基于已下载字节）
            speed = self._downloaded_bytes / elapsed if elapsed > 0 else 0

            # 计算进度百分比（基于已组装字节）
            if self.total_bytes > 0:
                progress_pct = (self._assembled_bytes / self.total_bytes) * 100
                remaining_bytes = self.total_bytes - self._assembled_bytes
                eta = remaining_bytes / speed if speed > 0 else 0
            else:
                progress_pct = 0
                eta = 0

            return {
                'downloaded_bytes': self._downloaded_bytes,
                'assembled_bytes': self._assembled_bytes,
                'total_bytes': self.total_bytes,
                'progress_pct': min(progress_pct, 100.0),  # 限制在 100%
                'speed_bps': speed,
                'eta_seconds': eta,
                'elapsed_seconds': elapsed,
                'total_xorbs': self._total_xorbs,
                'completed_xorbs': self._completed_xorbs,
                'active_xorbs': len(self._active_xorbs),
                'total_segments': self._total_segments,
                'completed_segments': self._completed_segments,
                'current_segment': self._current_segment,
                'total_terms': self._total_terms,
                'processed_terms': self._processed_terms,
            }

    def reset(self) -> None:
        """重置进度跟踪器。"""
        with self._lock:
            self._downloaded_bytes = 0
            self._assembled_bytes = 0
            self._start_time = time.time()
            self._total_xorbs = 0
            self._completed_xorbs = 0
            self._active_xorbs.clear()
            self._total_segments = 0
            self._completed_segments = 0
            self._current_segment = 0
            self._total_terms = 0
            self._processed_terms = 0

    def _notify(self) -> None:
        """触发回调通知（内部方法，必须在锁内调用）。"""
        if self.callback:
            try:
                stats = self._get_stats_unsafe()
                self.callback(stats)
            except Exception as e:
                logger.warning(f"[ProgressTracker] 回调失败: {e}")

    def _get_stats_unsafe(self) -> Dict[str, Any]:
        """获取统计信息（不加锁，仅供内部使用）。"""
        elapsed = time.time() - self._start_time
        speed = self._downloaded_bytes / elapsed if elapsed > 0 else 0

        if self.total_bytes > 0:
            progress_pct = (self._assembled_bytes / self.total_bytes) * 100
            remaining_bytes = self.total_bytes - self._assembled_bytes
            eta = remaining_bytes / speed if speed > 0 else 0
        else:
            progress_pct = 0
            eta = 0

        return {
            'downloaded_bytes': self._downloaded_bytes,
            'assembled_bytes': self._assembled_bytes,
            'total_bytes': self.total_bytes,
            'progress_pct': min(progress_pct, 100.0),
            'speed_bps': speed,
            'eta_seconds': eta,
            'elapsed_seconds': elapsed,
            'total_xorbs': self._total_xorbs,
            'completed_xorbs': self._completed_xorbs,
            'active_xorbs': len(self._active_xorbs),
            'total_segments': self._total_segments,
            'completed_segments': self._completed_segments,
            'current_segment': self._current_segment,
            'total_terms': self._total_terms,
            'processed_terms': self._processed_terms,
        }

    def format_stats(self) -> str:
        """格式化进度统计为人类可读字符串。

        Returns:
            格式化的进度字符串
        """
        stats = self.get_stats()

        def format_bytes(b: float) -> str:
            """格式化字节数。"""
            for unit in ['B', 'KB', 'MB', 'GB']:
                if b < 1024:
                    return f"{b:.1f} {unit}"
                b /= 1024
            return f"{b:.1f} TB"

        def format_time(s: float) -> str:
            """格式化时间。"""
            if s < 60:
                return f"{s:.0f}s"
            elif s < 3600:
                return f"{s/60:.1f}m"
            else:
                return f"{s/3600:.1f}h"

        parts = [
            f"{stats['progress_pct']:.1f}%",
            f"{format_bytes(stats['assembled_bytes'])}/{format_bytes(stats['total_bytes'])}",
        ]

        if stats['speed_bps'] > 0:
            parts.append(f"{format_bytes(stats['speed_bps'])}/s")

        if stats['eta_seconds'] > 0:
            parts.append(f"ETA: {format_time(stats['eta_seconds'])}")

        # 添加 xorb 进度
        if stats['total_xorbs'] > 0:
            xorb_info = f"Xorb: {stats['completed_xorbs']}/{stats['total_xorbs']}"
            if stats['active_xorbs'] > 0:
                xorb_info += f" (active: {stats['active_xorbs']})"
            parts.append(xorb_info)

        # 添加 segment 进度
        if stats['total_segments'] > 0:
            parts.append(f"Seg: {stats['completed_segments']}/{stats['total_segments']}")

        # 添加 term 进度
        if stats['total_terms'] > 0:
            parts.append(f"Term: {stats['processed_terms']}/{stats['total_terms']}")

        return " | ".join(parts)
