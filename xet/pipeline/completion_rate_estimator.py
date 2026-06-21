"""完成速率估算器 - 自适应预取优化。

使用指数加权移动平均（EWMA）估算文件重建的完成速率，
用于动态调整预取大小。
"""
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CompletionRateEstimator:
    """完成速率估算器（EWMA）。

    使用指数加权移动平均算法估算实时完成速率（bytes/s），
    用于自适应调整预取缓冲区大小。

    算法：
        rate(t) = α * rate(t-1) + (1 - α) * instant_rate
        其中 α = 0.5^(1 / half_life)

    Attributes:
        half_life: 半衰期（单位：样本数，默认 3）
        alpha: 平滑系数（根据半衰期计算）
    """

    def __init__(self, half_life: int = 3):
        """初始化估算器。

        Args:
            half_life: 半衰期（单位：样本数）
                - 表示多少个样本后权重衰减到 50%
                - 默认 3：最近 3 个样本的权重占主导
                - 越大越平滑，越小越灵敏
        """
        if half_life <= 0:
            raise ValueError(f"half_life 必须 > 0: {half_life}")

        self.half_life = half_life
        self.alpha = 0.5 ** (1.0 / half_life)
        self._value = 0.0  # 当前 EWMA 值（bytes/s）
        self._last_update = time.time()
        self._bytes_completed = 0
        self._sample_count = 0

        logger.debug(
            f"[CompletionRateEstimator] 初始化: half_life={half_life}, alpha={self.alpha:.4f}"
        )

    def update(self, bytes_delta: int) -> None:
        """更新已完成字节数。

        Args:
            bytes_delta: 本次增量字节数
        """
        if bytes_delta <= 0:
            return

        now = time.time()
        elapsed = now - self._last_update

        if elapsed > 0:
            # 计算瞬时速率
            instant_rate = bytes_delta / elapsed

            # EWMA 更新
            if self._sample_count == 0:
                # 第一个样本：直接设置
                self._value = instant_rate
            else:
                # 后续样本：指数加权平均
                self._value = self.alpha * self._value + (1 - self.alpha) * instant_rate

            self._sample_count += 1

            logger.debug(
                f"[CompletionRateEstimator] 更新: "
                f"瞬时={instant_rate / 1024 / 1024:.2f} MB/s, "
                f"EWMA={self._value / 1024 / 1024:.2f} MB/s, "
                f"样本数={self._sample_count}"
            )

        self._last_update = now
        self._bytes_completed += bytes_delta

    def get_rate(self) -> float:
        """获取当前完成速率（bytes/s）。

        Returns:
            当前估算的完成速率（bytes/s）
        """
        return self._value

    def get_rate_mbps(self) -> float:
        """获取当前完成速率（MB/s）。

        Returns:
            当前估算的完成速率（MB/s）
        """
        return self._value / 1024 / 1024

    def get_total_bytes(self) -> int:
        """获取总完成字节数。

        Returns:
            累计完成的字节数
        """
        return self._bytes_completed

    def reset(self) -> None:
        """重置估算器。"""
        self._value = 0.0
        self._last_update = time.time()
        self._bytes_completed = 0
        self._sample_count = 0
        logger.debug("[CompletionRateEstimator] 重置")

    def estimate_remaining_time(self, remaining_bytes: int) -> Optional[float]:
        """估算剩余时间（秒）。

        Args:
            remaining_bytes: 剩余字节数

        Returns:
            估算的剩余时间（秒），如果速率为 0 返回 None
        """
        if self._value <= 0:
            return None

        return remaining_bytes / self._value

    def __repr__(self) -> str:
        """字符串表示。"""
        return (
            f"CompletionRateEstimator("
            f"rate={self.get_rate_mbps():.2f} MB/s, "
            f"samples={self._sample_count}, "
            f"total={self._bytes_completed / 1024 / 1024:.2f} MB)"
        )
