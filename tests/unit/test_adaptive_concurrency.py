"""network.adaptive_concurrency 模块单元测试。"""
import pytest
import time
import threading
from unittest.mock import Mock

from xet.network.adaptive_concurrency import AdaptiveConcurrencyController


# ============================================================================
# AdaptiveConcurrencyController 基本功能测试
# ============================================================================

def test_acc_initialization():
    """测试自适应并发控制器初始化。"""
    acc = AdaptiveConcurrencyController(
        initial=4,
        min_concurrency=1,
        max_concurrency=64,
        success_threshold=0.8
    )

    assert acc._initial == 4
    assert acc._current == 4
    assert acc._min == 1
    assert acc._max == 64
    assert acc._success_threshold == 0.8
    assert acc._ewma_success_rate == 1.0


def test_acc_initialization_invalid_params():
    """测试无效参数抛出异常。"""
    with pytest.raises(ValueError, match="必须在"):
        AdaptiveConcurrencyController(initial=0)

    with pytest.raises(ValueError, match="必须 <="):
        AdaptiveConcurrencyController(min_concurrency=10, max_concurrency=5)

    with pytest.raises(ValueError, match="必须在"):
        AdaptiveConcurrencyController(success_threshold=1.5)


def test_acquire_and_release():
    """测试许可的获取和释放。"""
    acc = AdaptiveConcurrencyController(initial=2)

    # 获取 2 个许可
    assert acc.acquire(timeout=1.0) is True
    assert acc.acquire(timeout=1.0) is True

    # 第 3 个应该超时
    assert acc.acquire(timeout=0.1) is False

    # 释放 1 个
    acc.release()

    # 应该可以再次获取
    assert acc.acquire(timeout=1.0) is True


def test_report_success():
    """测试成功报告。"""
    acc = AdaptiveConcurrencyController(initial=4)

    # 报告成功
    acc.report_success(bytes_transferred=1024)

    assert acc._success_count == 1
    assert acc._total_count == 1
    # EWMA 更新：0.3 * 1.0 + 0.7 * 1.0 = 1.0
    assert acc._ewma_success_rate == 1.0


def test_report_failure():
    """测试失败报告。"""
    acc = AdaptiveConcurrencyController(initial=4)

    # 报告失败
    acc.report_failure(status_code=403)

    assert acc._success_count == 0
    assert acc._total_count == 1
    # EWMA 更新：0.3 * 0.0 + 0.7 * 1.0 = 0.7
    assert acc._ewma_success_rate == 0.7


def test_ewma_calculation():
    """测试 EWMA 成功率计算。"""
    acc = AdaptiveConcurrencyController(initial=4, ewma_alpha=0.3)

    # 初始成功率 1.0
    assert acc.success_rate == 1.0

    # 第 1 次失败：0.3 * 0 + 0.7 * 1.0 = 0.7
    acc.report_failure()
    assert abs(acc.success_rate - 0.7) < 0.01

    # 第 2 次失败：0.3 * 0 + 0.7 * 0.7 = 0.49
    acc.report_failure()
    assert abs(acc.success_rate - 0.49) < 0.01

    # 第 3 次成功：0.3 * 1 + 0.7 * 0.49 = 0.643
    acc.report_success()
    assert abs(acc.success_rate - 0.643) < 0.01


def test_increase_concurrency():
    """测试成功时增加并发数。"""
    acc = AdaptiveConcurrencyController(
        initial=2,
        max_concurrency=5,
        success_threshold=0.8,
        adjustment_interval=0.1
    )

    initial_concurrency = acc.current_concurrency

    # 报告多次成功
    for _ in range(5):
        acc.report_success()
        time.sleep(0.15)  # 等待调整间隔

    # 并发数应该增加
    assert acc.current_concurrency > initial_concurrency


def test_decrease_concurrency():
    """测试失败时降低并发数。"""
    acc = AdaptiveConcurrencyController(
        initial=4,
        min_concurrency=1,
        adjustment_interval=0.1
    )

    initial_concurrency = acc.current_concurrency

    # 报告多次失败
    for _ in range(5):
        acc.report_failure()
        time.sleep(0.15)  # 等待调整间隔

    # 并发数应该降低
    assert acc.current_concurrency < initial_concurrency


def test_concurrency_bounds():
    """测试并发数不超出边界。"""
    acc = AdaptiveConcurrencyController(
        initial=2,
        min_concurrency=1,
        max_concurrency=3,
        adjustment_interval=0.1
    )

    # 尝试增加到上限
    for _ in range(10):
        acc.report_success()
        time.sleep(0.15)

    assert acc.current_concurrency <= 3

    # 尝试降低到下限
    for _ in range(10):
        acc.report_failure()
        time.sleep(0.15)

    assert acc.current_concurrency >= 1


def test_adjustment_interval():
    """测试调整间隔防止抖动。"""
    acc = AdaptiveConcurrencyController(
        initial=4,
        adjustment_interval=1.0
    )

    initial = acc.current_concurrency

    # 快速连续报告成功
    for _ in range(10):
        acc.report_success()

    # 由于调整间隔，并发数不应该变化太多
    assert abs(acc.current_concurrency - initial) <= 1


def test_reset():
    """测试重置控制器。"""
    acc = AdaptiveConcurrencyController(initial=4)

    # 修改状态
    acc.report_failure()
    acc.report_failure()
    time.sleep(0.6)
    acc.report_failure()  # 触发降级

    # 重置
    acc.reset()

    assert acc.current_concurrency == 4
    assert acc.success_rate == 1.0
    assert acc._success_count == 0
    assert acc._total_count == 0


# ============================================================================
# 并发测试
# ============================================================================

def test_concurrent_acquire_release():
    """测试并发获取和释放。"""
    acc = AdaptiveConcurrencyController(initial=4)
    success_count = [0]
    lock = threading.Lock()

    def worker():
        if acc.acquire(timeout=2.0):
            with lock:
                success_count[0] += 1
            time.sleep(0.1)
            acc.release()

    # 10 个线程同时工作
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 所有线程都应该最终获得许可
    assert success_count[0] == 10
