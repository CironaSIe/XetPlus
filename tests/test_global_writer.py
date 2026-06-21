"""GlobalWriter 单元测试。"""
import os
import tempfile
import threading
from pathlib import Path

import pytest

from xet.pipeline.global_writer import GlobalWriter


def test_global_writer_basic():
    """测试基本的顺序写入。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_output.bin"

        writer = GlobalWriter(
            output_path=output_path,
            batch_size=4,
        )
        writer.start()

        # 写入一些数据
        writer.put(0, b"Hello ")
        writer.put(6, b"World")
        writer.put(11, b"!")

        # 完成写入
        total_bytes = writer.finish()

        assert total_bytes == 12
        assert output_path.exists()

        # 验证内容
        with open(output_path, 'rb') as f:
            content = f.read()

        assert content == b"Hello World!"


def test_global_writer_unordered():
    """测试乱序写入（会自动排序）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_unordered.bin"

        writer = GlobalWriter(
            output_path=output_path,
            batch_size=8,
        )
        writer.start()

        # 乱序写入
        writer.put(10, b"Third")
        writer.put(0, b"First")
        writer.put(5, b"Second")

        total_bytes = writer.finish()

        assert total_bytes == 16

        # 验证内容（GlobalWriter 会按 offset 排序）
        with open(output_path, 'rb') as f:
            content = f.read()

        # 期望：offset 0: "First", offset 5: "Second", offset 10: "Third"
        # 但中间可能有空隙（取决于实现）
        assert content[:5] == b"First"
        assert content[5:11] == b"Second"
        assert content[10:15] == b"Third"


def test_global_writer_progress_callback():
    """测试进度回调。"""
    progress_updates = []

    def progress_callback(bytes_written):
        progress_updates.append(bytes_written)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_progress.bin"

        writer = GlobalWriter(
            output_path=output_path,
            batch_size=2,  # 小批量，确保多次 flush
            progress_callback=progress_callback,
        )
        writer.start()

        # 写入多个数据块
        writer.put(0, b"A" * 100)
        writer.put(100, b"B" * 100)
        writer.put(200, b"C" * 100)
        writer.put(300, b"D" * 100)

        total_bytes = writer.finish()

        assert total_bytes == 400
        assert len(progress_updates) > 0  # 至少有一次进度更新
        assert sum(progress_updates) == 400  # 总和应该等于总字节数


def test_global_writer_stop_event():
    """测试停止信号。"""
    stop_event = threading.Event()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_stop.bin"

        writer = GlobalWriter(
            output_path=output_path,
            batch_size=4,
            stop_event=stop_event,
        )
        writer.start()

        # 写入一些数据
        writer.put(0, b"Start")

        # 触发停止信号
        stop_event.set()

        # 完成写入（应该能正常完成已提交的数据）
        total_bytes = writer.finish(timeout=5)

        assert total_bytes == 5
        assert output_path.exists()


def test_global_writer_large_batch():
    """测试大批量写入。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_large.bin"

        writer = GlobalWriter(
            output_path=output_path,
            batch_size=16,
        )
        writer.start()

        # 写入 100 个数据块
        for i in range(100):
            offset = i * 1024
            data = bytes([i % 256]) * 1024
            writer.put(offset, data)

        total_bytes = writer.finish()

        assert total_bytes == 100 * 1024
        assert output_path.stat().st_size == 100 * 1024


def test_global_writer_not_started_error():
    """测试未启动就调用 finish 会报错。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_error.bin"

        writer = GlobalWriter(output_path=output_path)

        # 未启动就 finish，应该报错
        with pytest.raises(RuntimeError, match="未启动"):
            writer.finish()


def test_global_writer_double_start_error():
    """测试重复启动会报错。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test_double.bin"

        writer = GlobalWriter(output_path=output_path)
        writer.start()

        # 重复启动，应该报错
        with pytest.raises(RuntimeError, match="已启动"):
            writer.start()

        # 清理
        writer.finish()


if __name__ == '__main__':
    # 运行测试
    pytest.main([__file__, '-v'])
