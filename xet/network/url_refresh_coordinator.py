"""URL 刷新协调器 - 防止并发下载时的 403 风暴。

在并行多段下载时，每个 xorb 的 403 都可能独立触发 get_reconstruction()，
导致短时间内几十次重复 API 调用。URLRefreshCoordinator 通过全局去重、
快速失败和冷却期来避免请求风暴。
"""
import threading
import time
from typing import Optional


class URLRefreshCoordinator:
    """全局协调 URL 刷新请求的线程安全控制器。

    特性：
    - 同一时间只允许 1 个线程执行刷新
    - 连续失败达到阈值后快速放弃
    - 冷却期防止频繁刷新

    Attributes:
        max_failures: 连续失败上限，达到后拒绝所有刷新请求
        cooldown: 刷新冷却期（秒），期间拒绝新请求
    """

    def __init__(self, max_failures: int = 3, cooldown: float = 10.0):
        """初始化协调器。

        Args:
            max_failures: 连续失败多少次后进入 exhausted 状态
            cooldown: 刷新间隔最小冷却时间（秒）
        """
        self._lock = threading.Lock()
        self._refreshing = False
        self._last_refresh_time: float = 0.0
        self._consecutive_failures: int = 0
        self._max_failures = max_failures
        self._cooldown = cooldown

    def acquire_refresh(self) -> bool:
        """尝试获取刷新权限（线程安全）。

        Returns:
            True: 获得刷新权限，调用者应执行刷新
            False: 未获得权限（其他线程在刷新/冷却期/已exhausted）
        """
        with self._lock:
            # 检查是否已达失败上限
            if self._consecutive_failures >= self._max_failures:
                return False

            # 检查是否在冷却期
            if time.time() - self._last_refresh_time < self._cooldown:
                return False

            # 检查是否有其他线程在刷新
            if self._refreshing:
                return False

            # 获得权限
            self._refreshing = True
            return True

    def release_refresh(self, success: bool):
        """释放刷新权限并报告结果。

        Args:
            success: 刷新是否成功
        """
        with self._lock:
            self._refreshing = False
            self._last_refresh_time = time.time()

            if success:
                # 成功：重置失败计数
                self._consecutive_failures = 0
            else:
                # 失败：累加计数
                self._consecutive_failures += 1

    @property
    def is_exhausted(self) -> bool:
        """检查是否已达失败上限（exhausted 状态）。

        Returns:
            True 表示连续失败次数已达上限，不应继续尝试
        """
        with self._lock:
            return self._consecutive_failures >= self._max_failures

    def reset(self):
        """重置协调器状态（用于测试或手动恢复）。"""
        with self._lock:
            self._refreshing = False
            self._last_refresh_time = 0.0
            self._consecutive_failures = 0
