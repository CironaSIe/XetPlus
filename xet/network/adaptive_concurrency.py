"""自适应并发控制器 - 对齐 Rust xet-core 实现。

基于 EWMA (Exponential Weighted Moving Average) 跟踪成功率，
并结合 RTT/带宽预测，动态调整并发数。

增强版：集成 RTTPredictor 预测 RTT（基于指数加权在线线性回归）。
"""
import threading
import time
import logging
from typing import Optional

from xet.network.online_regression import RTTPredictor


logger = logging.getLogger(__name__)


class AdaptiveConcurrencyController:
    """自适应并发控制器。

    根据请求成功率动态调整并发数，避免网络不稳定时的雪崩效应。

    算法：
    - 使用 EWMA 跟踪成功率（alpha=0.3 衰减因子）
    - 成功率 >= threshold 时缓慢增加并发（+1）
    - 失败时快速降低并发（-1）
    - 最小调整间隔 500ms，避免抖动

    Attributes:
        initial: 初始并发数
        min: 最小并发数
        max: 最大并发数
        success_threshold: 触发增加并发的成功率阈值
    """

    def __init__(
        self,
        initial: int = 4,
        min_concurrency: int = 1,
        max_concurrency: int = 64,
        success_threshold: float = 0.8,
        ewma_alpha: float = 0.3,
        adjustment_interval: float = 0.5,
        enable_rtt_prediction: bool = True,
        target_max_rtt: float = 5.0,
    ):
        """初始化自适应并发控制器。

        Args:
            initial: 初始并发数
            min_concurrency: 最小并发数
            max_concurrency: 最大并发数
            success_threshold: 触发增加的成功率阈值（0.0-1.0）
            ewma_alpha: EWMA 衰减因子（0.0-1.0，越大越敏感）
            adjustment_interval: 最小调整间隔（秒）
            enable_rtt_prediction: 是否启用 RTT 预测（默认 True）
            target_max_rtt: 目标最大 RTT（秒，默认 5.0）
        """
        if not (1 <= initial <= max_concurrency):
            raise ValueError(f"initial={initial} 必须在 [1, {max_concurrency}] 范围内")
        if not (1 <= min_concurrency <= max_concurrency):
            raise ValueError(f"min={min_concurrency} 必须 <= max={max_concurrency}")
        if not (0.0 < success_threshold <= 1.0):
            raise ValueError(f"success_threshold={success_threshold} 必须在 (0, 1] 范围内")

        self._initial = initial
        self._min = min_concurrency
        self._max = max_concurrency
        self._success_threshold = success_threshold
        self._alpha = ewma_alpha
        self._adjustment_interval = adjustment_interval
        self._enable_rtt_prediction = enable_rtt_prediction
        self._target_max_rtt = target_max_rtt

        # 当前并发数和信号量
        self._current = initial
        self._semaphore = threading.Semaphore(initial)
        self._lock = threading.Lock()
        self._pending_acquire: int = 0  # _maybe_decrease 欠债计数

        # EWMA 成功率跟踪
        self._ewma_success_rate: float = 1.0  # 初始假设成功率 100%
        self._success_count: int = 0
        self._total_count: int = 0

        # 调整时间戳
        self._last_adjustment_time: float = 0.0

        # RTT 预测器（可选）
        self._rtt_predictor: Optional[RTTPredictor] = None
        if enable_rtt_prediction:
            self._rtt_predictor = RTTPredictor(
                decay_half_life_count=100.0
            )
            logger.debug(f"[ACC] RTT 预测已启用: half_life=100.0")

    def acquire(self, timeout: float = 300.0) -> bool:
        """获取下载许可（阻塞直到获得或超时）。

        Args:
            timeout: 超时时间（秒）

        Returns:
            True: 获得许可
            False: 超时未获得
        """
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            logger.warning(f"[ACC] acquire 超时 ({timeout}s)，当前并发={self._current}")
        return acquired

    def release(self):
        """释放下载许可（消费 _pending_acquire 欠债）。"""
        with self._lock:
            if self._pending_acquire > 0:
                self._pending_acquire -= 1
            else:
                self._semaphore.release()

    def report_success(self, bytes_transferred: int = 0, rtt: Optional[float] = None):
        """报告成功，可能触发并发数增加。

        Args:
            bytes_transferred: 传输字节数（可选，用于 RTT 预测）
            rtt: 往返时间（秒，可选，用于 RTT 预测）
        """
        self._update_ewma(success=True)

        # 更新 RTT 预测器
        if self._rtt_predictor and rtt is not None and bytes_transferred > 0:
            self._rtt_predictor.update(
                size_bytes=bytes_transferred,
                duration_secs=rtt,
                avg_concurrent=float(self._current),
                weight=1.0
            )

        self._maybe_increase(bytes_transferred)

    def report_failure(self, status_code: int = 0):
        """报告失败，快速降级并发数。

        Args:
            status_code: HTTP 状态码（可选，用于日志）
        """
        self._update_ewma(success=False)
        self._maybe_decrease(reason=f"HTTP {status_code}" if status_code else "failure")

    def _update_ewma(self, success: bool):
        """更新 EWMA 成功率。

        Args:
            success: 本次请求是否成功
        """
        with self._lock:
            self._total_count += 1
            if success:
                self._success_count += 1

            # EWMA 更新公式: new_ewma = alpha * current + (1 - alpha) * old_ewma
            current_value = 1.0 if success else 0.0
            self._ewma_success_rate = (
                self._alpha * current_value + (1 - self._alpha) * self._ewma_success_rate
            )

    def _maybe_increase(self, bytes_transferred: int = 0):
        """尝试增加并发数（成功率高且冷却期已过）。

        Args:
            bytes_transferred: 传输字节数（用于 RTT 预测）
        """
        now = time.time()
        with self._lock:
            # 检查冷却期
            if now - self._last_adjustment_time < self._adjustment_interval:
                return

            # 检查成功率
            if self._ewma_success_rate < self._success_threshold:
                return

            # 检查是否已达上限
            if self._current >= self._max:
                return

            # 如果启用 RTT 预测，检查预测的 RTT
            if self._rtt_predictor and bytes_transferred > 0:
                # 预测增加 1 个并发后的 RTT
                predicted_rtt = self._rtt_predictor.predicted_rtt(
                    size_bytes=bytes_transferred,
                    avg_concurrent=float(self._current + 1)
                )

                if predicted_rtt is not None and predicted_rtt > self._target_max_rtt:
                    logger.debug(
                        f"[ACC] RTT 预测阻止增加: predicted_rtt={predicted_rtt:.3f}s "
                        f"> target={self._target_max_rtt}s"
                    )
                    return

            # 增加并发
            old_value = self._current
            self._current += 1
            self._semaphore.release()  # 增加一个许可
            self._last_adjustment_time = now

            logger.info(
                f"[ACC] 并发数增加: {old_value} → {self._current} "
                f"(EWMA={self._ewma_success_rate:.3f})"
            )

    def _maybe_decrease(self, reason: str = ""):
        """快速降低并发数（失败时立即触发）。

        Args:
            reason: 降低原因（用于日志）
        """
        now = time.time()
        with self._lock:
            # 检查冷却期
            if now - self._last_adjustment_time < self._adjustment_interval:
                return

            # 检查是否已达下限
            if self._current <= self._min:
                return

            # 降低并发
            old_value = self._current
            self._current -= 1
            # 不能调用 acquire（可能阻塞），用 _pending_acquire 标记告知 release 消费
            self._pending_acquire += 1
            self._last_adjustment_time = now

            logger.info(
                f"[ACC] 并发数降低: {old_value} → {self._current} "
                f"(EWMA={self._ewma_success_rate:.3f}, reason={reason})"
            )

    @property
    def current_concurrency(self) -> int:
        """获取当前并发数。"""
        with self._lock:
            return self._current

    @property
    def success_rate(self) -> float:
        """获取当前 EWMA 成功率。"""
        with self._lock:
            return self._ewma_success_rate

    def reset(self):
        """重置控制器到初始状态（用于测试）。"""
        with self._lock:
            # 调整信号量到初始值
            diff = self._initial - self._current
            if diff > 0:
                for _ in range(diff):
                    self._semaphore.release()
            elif diff < 0:
                for _ in range(-diff):
                    self._semaphore.acquire(blocking=False)

            self._current = self._initial
            self._ewma_success_rate = 1.0
            self._success_count = 0
            self._total_count = 0
            self._last_adjustment_time = 0.0
            self._pending_acquire = 0
