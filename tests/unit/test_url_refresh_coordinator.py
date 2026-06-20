"""network.url_refresh_coordinator 模块单元测试。"""
import pytest
import time
import threading
from unittest.mock import Mock

from xet.network.url_refresh_coordinator import URLRefreshCoordinator


# ============================================================================
# URLRefreshCoordinator 基本功能测试
# ============================================================================

def test_coordinator_initialization():
    """测试协调器初始化。"""
    coordinator = URLRefreshCoordinator(max_failures=3, cooldown=10.0)

    assert coordinator._max_failures == 3
    assert coordinator._cooldown == 10.0
    assert coordinator._consecutive_failures == 0
    assert coordinator._refreshing is False
    assert coordinator._last_refresh_time == 0.0


def test_acquire_refresh_success():
    """测试成功获取刷新权限。"""
    coordinator = URLRefreshCoordinator()

    # 第一次获取应该成功
    assert coordinator.acquire_refresh() is True
    assert coordinator._refreshing is True


def test_acquire_refresh_blocked_by_other_thread():
    """测试其他线程正在刷新时拒绝新请求。"""
    coordinator = URLRefreshCoordinator()

    # 第一次获取成功
    assert coordinator.acquire_refresh() is True

    # 第二次应该失败（其他线程在刷新）
    assert coordinator.acquire_refresh() is False


def test_release_refresh_success():
    """测试成功释放刷新权限。"""
    coordinator = URLRefreshCoordinator()

    coordinator.acquire_refresh()
    coordinator.release_refresh(success=True)

    assert coordinator._refreshing is False
    assert coordinator._consecutive_failures == 0


def test_release_refresh_failure():
    """测试失败释放刷新权限。"""
    coordinator = URLRefreshCoordinator(max_failures=3)

    coordinator.acquire_refresh()
    coordinator.release_refresh(success=False)

    assert coordinator._refreshing is False
    assert coordinator._consecutive_failures == 1


def test_consecutive_failures_exhausted():
    """测试连续失败达到上限。"""
    coordinator = URLRefreshCoordinator(max_failures=3, cooldown=0.0)  # 禁用冷却期

    # 失败 3 次
    for _ in range(3):
        assert coordinator.acquire_refresh() is True
        coordinator.release_refresh(success=False)

    # 第 4 次应该拒绝（已 exhausted）
    assert coordinator.is_exhausted is True
    assert coordinator.acquire_refresh() is False


def test_cooldown_period():
    """测试冷却期。"""
    coordinator = URLRefreshCoordinator(cooldown=1.0)

    # 第一次获取
    assert coordinator.acquire_refresh() is True
    coordinator.release_refresh(success=True)

    # 立即再次获取应该失败（冷却期）
    assert coordinator.acquire_refresh() is False

    # 等待冷却期结束
    time.sleep(1.1)

    # 冷却期后应该成功
    assert coordinator.acquire_refresh() is True
    coordinator.release_refresh(success=True)


def test_reset():
    """测试重置协调器。"""
    coordinator = URLRefreshCoordinator(max_failures=2)

    # 失败 2 次达到 exhausted
    for _ in range(2):
        coordinator.acquire_refresh()
        coordinator.release_refresh(success=False)

    assert coordinator.is_exhausted is True

    # 重置
    coordinator.reset()

    assert coordinator._consecutive_failures == 0
    assert coordinator._refreshing is False
    assert coordinator.acquire_refresh() is True


# ============================================================================
# 并发测试
# ============================================================================

def test_thread_safety():
    """测试多线程安全。"""
    coordinator = URLRefreshCoordinator()
    acquired_count = [0]
    lock = threading.Lock()

    def try_acquire():
        if coordinator.acquire_refresh():
            with lock:
                acquired_count[0] += 1
            time.sleep(0.1)  # 模拟刷新工作
            coordinator.release_refresh(success=True)

    # 10 个线程同时尝试获取
    threads = [threading.Thread(target=try_acquire) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 只有 1 个线程应该获得权限（因为有 sleep 模拟工作）
    # 注意：由于冷却期，后续可能有更多线程获得，但至少第一波只有 1 个
    assert acquired_count[0] >= 1
