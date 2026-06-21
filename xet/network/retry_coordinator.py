"""全局重试协调器 - 防止永久重试死循环。

设计目标：
- 单个 xorb 重试无上限（临时故障应持续重试）
- 全局协调：如果所有并行下载都在重试状态，说明可能是全局网络问题，应触发停止

工作原理：
- 每个 xorb 重试时调用 register_retry(hash) 注册
- 重试成功后调用 unregister_retry(hash) 注销
- 重试前调用 should_stop_retrying() 检查：
  * 如果所有活跃下载都在重试状态（retrying == active），
    且持续超过 all_retry_grace 秒，返回 True（应停止）
  * 否则返回 False（继续重试）

参考: ~/xet.py/xet/http_utils.py:875-980 (RetryCoordinator)
"""
import time
import threading
import logging
from typing import Optional, Dict, Set

logger = logging.getLogger(__name__)


class RetryCoordinator:
    """Xorb 重试全局协调器。

    防止所有并行下载同时卡在重试循环中（可能是全局网络问题）。

    Attributes:
        all_retry_grace: 所有并行下载都在重试状态时，持续多少秒后才触发停止
        retrying_hashes: 正在重试的 xorb hash 集合
        active_hashes: 所有活跃的 xorb hash 集合（正在下载或重试）
        all_retry_since: 开始"全部重试"的时间戳
        global_stop: 全局停止标志
    """

    def __init__(self, all_retry_grace: float = 120.0):
        """初始化重试协调器。

        Args:
            all_retry_grace: 所有并行下载都在重试状态时，
                持续多少秒后才触发停止（给临时波动留余地）
        """
        self._lock = threading.Lock()
        self._retrying_hashes: Set[str] = set()  # 正在重试的 xorb hash
        self._active_hashes: Set[str] = set()    # 所有活跃的 xorb hash
        self._all_retry_since: Optional[float] = None  # 开始"全部重试"的时间戳
        self._all_retry_grace = all_retry_grace
        self._global_stop = False  # 全局停止标志

    def register_active(self, xorb_hash: str):
        """注册一个活跃的 xorb 下载（开始下载时调用）。"""
        with self._lock:
            self._active_hashes.add(xorb_hash)
            logger.debug(f"[RetryCoord] 注册活跃: {xorb_hash[:16]}...")

    def unregister_active(self, xorb_hash: str):
        """注销一个活跃的 xorb 下载（下载完成或彻底失败时调用）。"""
        with self._lock:
            self._active_hashes.discard(xorb_hash)
            self._retrying_hashes.discard(xorb_hash)
            self._update_all_retry_state_locked()
            logger.debug(f"[RetryCoord] 注销活跃: {xorb_hash[:16]}...")

    def register_retry(self, xorb_hash: str):
        """注册一个 xorb 进入重试状态。"""
        with self._lock:
            self._retrying_hashes.add(xorb_hash)
            self._update_all_retry_state_locked()
            logger.debug(
                f"[RetryCoord] 进入重试: {xorb_hash[:16]}... "
                f"({len(self._retrying_hashes)}/{len(self._active_hashes)} 在重试)"
            )

    def unregister_retry(self, xorb_hash: str):
        """注销一个 xorb 的重试状态（重试成功时调用）。"""
        with self._lock:
            self._retrying_hashes.discard(xorb_hash)
            self._update_all_retry_state_locked()
            logger.debug(f"[RetryCoord] 重试成功: {xorb_hash[:16]}...")

    def _update_all_retry_state_locked(self):
        """更新"全部重试"状态（调用者需持锁）。"""
        # 只有当有活跃下载，且全部都在重试时，才算"全部重试"
        if self._active_hashes and len(self._retrying_hashes) == len(self._active_hashes):
            if self._all_retry_since is None:
                self._all_retry_since = time.time()
                logger.warning(
                    f"[RetryCoord] ⚠️ 所有 {len(self._active_hashes)} 个并行下载"
                    f"都在重试状态，开始计时 (宽限 {self._all_retry_grace:.0f}s)"
                )
        else:
            if self._all_retry_since is not None:
                logger.info(
                    f"[RetryCoord] 部分下载恢复正常，取消停止计时"
                )
            self._all_retry_since = None

    def should_stop_retrying(self) -> bool:
        """检查是否应该停止重试。

        Returns:
            True 如果所有并行下载都在重试状态且超过宽限期，或全局停止已触发
        """
        with self._lock:
            if self._global_stop:
                return True

            if self._all_retry_since is None:
                return False

            elapsed = time.time() - self._all_retry_since
            if elapsed >= self._all_retry_grace:
                logger.error(
                    f"[RetryCoord] ❌ 所有并行下载持续重试 {elapsed:.0f}s "
                    f"(超过宽限 {self._all_retry_grace:.0f}s)，触发全局停止"
                )
                self._global_stop = True
                return True

            return False

    def trigger_global_stop(self):
        """手动触发全局停止（如检测到网络完全断开）。"""
        with self._lock:
            self._global_stop = True
            logger.error("[RetryCoord] ❌ 手动触发全局停止")

    def get_status(self) -> Dict:
        """获取当前状态（用于日志）。

        Returns:
            {
                "active": 活跃下载数,
                "retrying": 重试中的下载数,
                "all_retry_elapsed": 全部重试持续时间（秒），None 表示未触发,
                "global_stop": 是否已全局停止,
            }
        """
        with self._lock:
            all_retry_elapsed = None
            if self._all_retry_since is not None:
                all_retry_elapsed = time.time() - self._all_retry_since

            return {
                "active": len(self._active_hashes),
                "retrying": len(self._retrying_hashes),
                "all_retry_elapsed": all_retry_elapsed,
                "global_stop": self._global_stop,
            }
