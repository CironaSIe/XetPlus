"""pipeline.progress_tracker 模块单元测试。"""
import pytest
import time
import threading
from unittest.mock import Mock

from xet.pipeline.progress_tracker import ProgressTracker


# ============================================================================
# ProgressTracker 初始化测试
# ============================================================================

def test_progress_tracker_creation():
    """测试创建 ProgressTracker。"""
    tracker = ProgressTracker(total_bytes=1000)

    assert tracker.get_stats()["total_bytes"] == 1000
    assert tracker.get_stats()["downloaded_bytes"] == 0
    assert tracker.get_stats()["assembled_bytes"] == 0


def test_progress_tracker_with_callback():
    """测试带回调的 ProgressTracker。"""
    callback = Mock()
    tracker = ProgressTracker(total_bytes=1000, callback=callback)

    # 增加下载字节应触发回调
    tracker.increment_downloaded(100)

    callback.assert_called_once()
    stats = callback.call_args[0][0]
    assert stats["downloaded_bytes"] == 100


# ============================================================================
# 基本计数测试
# ============================================================================

def test_increment_downloaded():
    """测试增加下载字节数。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker.increment_downloaded(100)
    assert tracker.get_stats()["downloaded_bytes"] == 100

    tracker.increment_downloaded(200)
    assert tracker.get_stats()["downloaded_bytes"] == 300


def test_increment_assembled():
    """测试增加组装字节数。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker.increment_assembled(50)
    assert tracker.get_stats()["assembled_bytes"] == 50

    tracker.increment_assembled(150)
    assert tracker.get_stats()["assembled_bytes"] == 200


def test_set_total_bytes():
    """测试设置总字节数。"""
    tracker = ProgressTracker()

    assert tracker.get_stats()["total_bytes"] == 0

    tracker.set_total_bytes(5000)
    assert tracker.get_stats()["total_bytes"] == 5000


def test_reset():
    """测试重置进度。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker.increment_downloaded(300)
    tracker.increment_assembled(200)

    tracker.reset()

    stats = tracker.get_stats()
    assert stats["downloaded_bytes"] == 0
    assert stats["assembled_bytes"] == 0
    assert stats["total_bytes"] == 1000  # total 不被重置


# ============================================================================
# 进度百分比测试
# ============================================================================

def test_progress_percentage():
    """测试进度百分比计算。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker.increment_assembled(250)
    stats = tracker.get_stats()
    assert stats["progress_pct"] == 25.0

    tracker.increment_assembled(250)
    stats = tracker.get_stats()
    assert stats["progress_pct"] == 50.0


def test_progress_percentage_zero_total():
    """测试总字节数为 0 时的进度百分比。"""
    tracker = ProgressTracker(total_bytes=0)

    tracker.increment_assembled(100)
    stats = tracker.get_stats()
    assert stats["progress_pct"] == 0.0


def test_progress_percentage_over_100():
    """测试进度超过 100% 的情况。"""
    tracker = ProgressTracker(total_bytes=100)

    tracker.increment_assembled(150)
    stats = tracker.get_stats()
    # 不应超过 100%
    assert stats["progress_pct"] == 100.0


# ============================================================================
# 速度和 ETA 测试
# ============================================================================

def test_speed_calculation():
    """测试速度计算。"""
    tracker = ProgressTracker(total_bytes=1000)

    # 手动设置开始时间（通过私有属性，仅测试用）
    tracker._start_time = time.time() - 1.0  # 1 秒前开始

    tracker.increment_assembled(500)

    stats = tracker.get_stats()
    # 500 字节 / 1 秒 = 500 B/s
    assert 400 < stats["speed_bps"] < 600  # 允许误差


def test_eta_calculation():
    """测试 ETA 计算。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker._start_time = time.time() - 1.0  # 1 秒前开始
    tracker.increment_assembled(250)  # 完成 25%

    stats = tracker.get_stats()
    # 剩余 750 字节，速度 250 B/s，ETA = 3 秒
    assert 2.5 < stats["eta_seconds"] < 3.5


def test_eta_when_no_progress():
    """测试无进度时的 ETA。"""
    tracker = ProgressTracker(total_bytes=1000)

    stats = tracker.get_stats()
    assert stats["eta_seconds"] == 0.0


def test_eta_when_completed():
    """测试完成时的 ETA。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker.increment_assembled(1000)

    stats = tracker.get_stats()
    assert stats["eta_seconds"] == 0.0


def test_elapsed_time():
    """测试经过时间。"""
    tracker = ProgressTracker(total_bytes=1000)

    tracker._start_time = time.time() - 2.0  # 2 秒前开始

    stats = tracker.get_stats()
    assert 1.8 < stats["elapsed_seconds"] < 2.2


# ============================================================================
# 格式化输出测试
# ============================================================================

def test_format_stats():
    """测试格式化统计信息。"""
    tracker = ProgressTracker(total_bytes=100_000_000)  # 100 MB

    tracker._start_time = time.time() - 10.0
    tracker.increment_assembled(50_000_000)  # 50 MB

    formatted = tracker.format_stats()

    # 应包含百分比、大小、速度、ETA
    assert "50.0%" in formatted
    assert "MB" in formatted
    assert "MB/s" in formatted
    assert "ETA:" in formatted


def test_format_bytes():
    """测试字节格式化。"""
    tracker = ProgressTracker()

    # 通过 format_stats 间接测试（因为 _format_bytes 是私有方法）
    tracker.set_total_bytes(1024)
    tracker.increment_assembled(512)

    formatted = tracker.format_stats()
    assert "512.0 B" in formatted or "0.5 KB" in formatted


# ============================================================================
# 线程安全测试
# ============================================================================

def test_thread_safety_downloaded():
    """测试多线程下载计数的线程安全性。"""
    tracker = ProgressTracker(total_bytes=10000)

    def worker():
        for _ in range(100):
            tracker.increment_downloaded(10)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 10 个线程，每个增加 1000，总计 10000
    assert tracker.get_stats()["downloaded_bytes"] == 10000


def test_thread_safety_assembled():
    """测试多线程组装计数的线程安全性。"""
    tracker = ProgressTracker(total_bytes=10000)

    def worker():
        for _ in range(100):
            tracker.increment_assembled(10)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert tracker.get_stats()["assembled_bytes"] == 10000


def test_thread_safety_mixed_operations():
    """测试混合操作的线程安全性。"""
    tracker = ProgressTracker(total_bytes=20000)

    def download_worker():
        for _ in range(50):
            tracker.increment_downloaded(10)

    def assemble_worker():
        for _ in range(50):
            tracker.increment_assembled(10)

    threads = []
    for _ in range(5):
        threads.append(threading.Thread(target=download_worker))
        threads.append(threading.Thread(target=assemble_worker))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stats = tracker.get_stats()
    assert stats["downloaded_bytes"] == 2500  # 5 * 50 * 10
    assert stats["assembled_bytes"] == 2500


# ============================================================================
# 回调机制测试
# ============================================================================

def test_callback_triggered_on_downloaded():
    """测试下载时触发回调。"""
    callback = Mock()
    tracker = ProgressTracker(total_bytes=1000, callback=callback)

    tracker.increment_downloaded(100)

    assert callback.call_count == 1


def test_callback_triggered_on_assembled():
    """测试组装时触发回调。"""
    callback = Mock()
    tracker = ProgressTracker(total_bytes=1000, callback=callback)

    tracker.increment_assembled(100)

    assert callback.call_count == 1


def test_callback_receives_stats():
    """测试回调接收正确的统计信息。"""
    callback = Mock()
    tracker = ProgressTracker(total_bytes=1000, callback=callback)

    tracker.increment_assembled(250)

    stats = callback.call_args[0][0]
    assert stats["assembled_bytes"] == 250
    assert stats["progress_pct"] == 25.0


def test_no_callback_when_not_set():
    """测试未设置回调时不报错。"""
    tracker = ProgressTracker(total_bytes=1000)

    # 不应抛出异常
    tracker.increment_downloaded(100)
    tracker.increment_assembled(100)

    assert tracker.get_stats()["downloaded_bytes"] == 100
