"""下载故障检测器 - 实时检测网络故障。

负责：
1. 检测连接异常（ConnectionReset, Timeout）
2. 检测低速（平均带宽 < 10KB/s 持续 30 秒）
3. 判断是否应该触发故障转移
"""
import socket
import time
import logging
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)


class DownloadFailureDetector:
    """下载故障检测器。

    检测下载过程中的网络故障：
    1. 连接异常：ConnectionResetError, BrokenPipeError, socket.timeout
    2. 低速：平均带宽 < min_speed_bps 持续 window_size 秒
    """

    def __init__(self, min_speed_bps: int = 10_000, window_size: int = 30):
        """初始化故障检测器。

        Args:
            min_speed_bps: 最低速度（字节/秒），默认 10KB/s
            window_size: 检测窗口大小（秒），默认 30 秒
        """
        self.min_speed_bps = min_speed_bps
        self.window_size = window_size

        # 速度采样（用于计算滑动窗口平均速度）
        self.samples: deque = deque(maxlen=window_size)  # [(timestamp, bytes), ...]
        self.total_bytes = 0
        self.start_time: Optional[float] = None

    def reset(self):
        """重置检测器状态（切换 IP 后调用）。"""
        self.samples.clear()
        self.total_bytes = 0
        self.start_time = None

    def update(self, bytes_downloaded: int):
        """更新下载进度。

        Args:
            bytes_downloaded: 本次下载的字节数
        """
        now = time.time()

        if self.start_time is None:
            self.start_time = now

        self.total_bytes += bytes_downloaded
        self.samples.append((now, bytes_downloaded))

    def should_failover(
        self,
        exception: Optional[Exception] = None,
    ) -> tuple[bool, str]:
        """判断是否应该触发故障转移。

        Args:
            exception: 发生的异常（如果有）

        Returns:
            (should_failover, reason): 是否应该转移 + 原因
        """
        # 1. 检查异常类型
        if exception:
            if isinstance(exception, (ConnectionResetError, BrokenPipeError)):
                reason = "连接被重置"
                logger.warning(f"[FailureDetector] 检测到网络故障: {reason}")
                return (True, reason)

            if isinstance(exception, socket.timeout):
                reason = "连接超时"
                logger.warning(f"[FailureDetector] 检测到网络故障: {reason}")
                return (True, reason)

            if isinstance(exception, TimeoutError):
                reason = "请求超时"
                logger.warning(f"[FailureDetector] 检测到网络故障: {reason}")
                return (True, reason)

        # 2. 检查带宽（需要足够的采样）
        if self.start_time and len(self.samples) >= 3:
            elapsed = time.time() - self.start_time

            # 只在达到窗口大小后检查带宽
            if elapsed >= self.window_size:
                avg_speed = self.total_bytes / elapsed

                if avg_speed < self.min_speed_bps:
                    reason = f"低速 ({avg_speed / 1024:.1f} KB/s < {self.min_speed_bps / 1024:.1f} KB/s)"
                    logger.warning(f"[FailureDetector] 检测到网络故障: {reason}")
                    return (True, reason)

        return (False, "")

    def get_current_speed(self) -> float:
        """获取当前平均速度（字节/秒）。

        Returns:
            平均速度（字节/秒）
        """
        if not self.start_time:
            return 0.0

        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0

        return self.total_bytes / elapsed

    def get_stats(self) -> dict:
        """获取统计信息。

        Returns:
            统计信息字典
        """
        elapsed = time.time() - self.start_time if self.start_time else 0
        avg_speed = self.total_bytes / elapsed if elapsed > 0 else 0

        return {
            "total_bytes": self.total_bytes,
            "elapsed_seconds": elapsed,
            "avg_speed_bps": avg_speed,
            "avg_speed_kbps": avg_speed / 1024,
            "samples": len(self.samples),
        }
