"""pipeline.checkpoint_manager 模块单元测试。"""
import pytest
import json
import tempfile
import shutil
import threading
from pathlib import Path

from xet.pipeline.checkpoint_manager import CheckpointManager
from xet.pipeline.types import ReconstructionCheckpoint


@pytest.fixture
def temp_checkpoint_file():
    """创建临时 checkpoint 文件。"""
    tmpdir = Path(tempfile.mkdtemp())
    checkpoint_file = tmpdir / "test_checkpoint.json"
    yield checkpoint_file
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# CheckpointManager 初始化测试
# ============================================================================

def test_checkpoint_manager_creation(temp_checkpoint_file):
    """测试创建 CheckpointManager。"""
    manager = CheckpointManager(temp_checkpoint_file)

    assert manager.checkpoint_path == temp_checkpoint_file
    assert manager._cache == {}


def test_checkpoint_manager_none_path():
    """测试 checkpoint_path 为 None。"""
    manager = CheckpointManager(None)

    # 不应抛出异常
    assert manager.checkpoint_path is None


# ============================================================================
# 保存和加载测试
# ============================================================================

def test_save_and_load_checkpoint(temp_checkpoint_file):
    """测试保存和加载 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash="file123",
        completed_xorbs={"xorb1", "xorb2"},
        timestamp=1234567890,
    )

    # 保存
    manager.save(checkpoint)

    # 加载
    loaded = manager.load("file123")

    assert loaded is not None
    assert loaded.file_hash == "file123"
    assert loaded.completed_xorbs == {"xorb1", "xorb2"}
    assert loaded.timestamp == 1234567890


def test_load_nonexistent_checkpoint(temp_checkpoint_file):
    """测试加载不存在的 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    loaded = manager.load("nonexistent")

    assert loaded is None


def test_save_creates_directory(temp_checkpoint_file):
    """测试保存时自动创建目录。"""
    # 删除父目录
    shutil.rmtree(temp_checkpoint_file.parent, ignore_errors=True)

    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash="file123")
    manager.save(checkpoint)

    # 目录应该被创建
    assert temp_checkpoint_file.parent.exists()
    assert temp_checkpoint_file.exists()


def test_save_multiple_checkpoints(temp_checkpoint_file):
    """测试保存多个 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint1 = ReconstructionCheckpoint(
        file_hash="file1",
        completed_xorbs={"xorb1"},
    )
    checkpoint2 = ReconstructionCheckpoint(
        file_hash="file2",
        completed_xorbs={"xorb2", "xorb3"},
    )

    manager.save(checkpoint1)
    manager.save(checkpoint2)

    # 两个 checkpoint 都应该存在
    loaded1 = manager.load("file1")
    loaded2 = manager.load("file2")

    assert loaded1.file_hash == "file1"
    assert loaded2.file_hash == "file2"
    assert len(loaded2.completed_xorbs) == 2


def test_save_overwrites_existing(temp_checkpoint_file):
    """测试保存覆盖已有 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint1 = ReconstructionCheckpoint(
        file_hash="file123",
        completed_xorbs={"xorb1"},
    )
    checkpoint2 = ReconstructionCheckpoint(
        file_hash="file123",
        completed_xorbs={"xorb1", "xorb2", "xorb3"},
    )

    manager.save(checkpoint1)
    manager.save(checkpoint2)

    loaded = manager.load("file123")
    assert len(loaded.completed_xorbs) == 3


# ============================================================================
# 增量更新测试
# ============================================================================

def test_mark_completed_new_checkpoint(temp_checkpoint_file):
    """测试标记完成（新 checkpoint）。"""
    manager = CheckpointManager(temp_checkpoint_file)

    manager.mark_completed("file123", "xorb1")

    loaded = manager.load("file123")
    assert loaded is not None
    assert loaded.is_completed("xorb1")


def test_mark_completed_existing_checkpoint(temp_checkpoint_file):
    """测试标记完成（已有 checkpoint）。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash="file123",
        completed_xorbs={"xorb1"},
    )
    manager.save(checkpoint)

    manager.mark_completed("file123", "xorb2")

    loaded = manager.load("file123")
    assert loaded.is_completed("xorb1")
    assert loaded.is_completed("xorb2")


def test_mark_completed_idempotent(temp_checkpoint_file):
    """测试重复标记完成是幂等的。"""
    manager = CheckpointManager(temp_checkpoint_file)

    manager.mark_completed("file123", "xorb1")
    manager.mark_completed("file123", "xorb1")  # 重复

    loaded = manager.load("file123")
    assert loaded.completion_count() == 1


# ============================================================================
# 清理测试
# ============================================================================

def test_clear_checkpoint(temp_checkpoint_file):
    """测试清理 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash="file123",
        completed_xorbs={"xorb1", "xorb2"},
    )
    manager.save(checkpoint)

    manager.clear("file123")

    loaded = manager.load("file123")
    assert loaded is None


def test_clear_nonexistent_checkpoint(temp_checkpoint_file):
    """测试清理不存在的 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    # 不应抛出异常
    manager.clear("nonexistent")


def test_clear_one_of_many(temp_checkpoint_file):
    """测试清理多个 checkpoint 中的一个。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint1 = ReconstructionCheckpoint(file_hash="file1")
    checkpoint2 = ReconstructionCheckpoint(file_hash="file2")

    manager.save(checkpoint1)
    manager.save(checkpoint2)

    manager.clear("file1")

    # file1 应该被清理，file2 仍然存在
    assert manager.load("file1") is None
    assert manager.load("file2") is not None


# ============================================================================
# 缓存机制测试
# ============================================================================

def test_cache_after_load(temp_checkpoint_file):
    """测试加载后缓存。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash="file123")
    manager.save(checkpoint)

    # 第一次加载（从文件）
    loaded1 = manager.load("file123")

    # 检查缓存
    assert "file123" in manager._cache

    # 第二次加载（从缓存）
    loaded2 = manager.load("file123")

    # 应该是同一个对象
    assert loaded1 is loaded2


def test_cache_after_save(temp_checkpoint_file):
    """测试保存后缓存。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash="file123")
    manager.save(checkpoint)

    # 缓存应该被更新
    assert "file123" in manager._cache
    assert manager._cache["file123"].file_hash == "file123"


def test_cache_cleared_after_clear(temp_checkpoint_file):
    """测试清理后缓存被移除。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash="file123")
    manager.save(checkpoint)

    # 确保缓存存在
    assert "file123" in manager._cache

    manager.clear("file123")

    # 缓存应该被清理
    assert "file123" not in manager._cache


# ============================================================================
# 文件格式测试
# ============================================================================

def test_checkpoint_file_format(temp_checkpoint_file):
    """测试 checkpoint 文件格式。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash="file123",
        completed_xorbs={"xorb1", "xorb2"},
        timestamp=1234567890,
    )
    manager.save(checkpoint)

    # 读取文件内容
    with open(temp_checkpoint_file, 'r') as f:
        data = json.load(f)

    assert "file123" in data
    assert "file_hash" in data["file123"]
    assert "completed_xorbs" in data["file123"]
    assert "timestamp" in data["file123"]


def test_load_corrupted_checkpoint(temp_checkpoint_file):
    """测试加载损坏的 checkpoint 文件。"""
    # 写入无效 JSON
    with open(temp_checkpoint_file, 'w') as f:
        f.write("invalid json {")

    manager = CheckpointManager(temp_checkpoint_file)

    # 应该返回 None 而不是抛出异常
    loaded = manager.load("file123")
    assert loaded is None


def test_load_empty_checkpoint_file(temp_checkpoint_file):
    """测试加载空的 checkpoint 文件。"""
    # 创建空文件
    temp_checkpoint_file.touch()

    manager = CheckpointManager(temp_checkpoint_file)

    loaded = manager.load("file123")
    assert loaded is None


# ============================================================================
# 线程安全测试
# ============================================================================

def test_thread_safety_save(temp_checkpoint_file):
    """测试多线程保存的线程安全性。"""
    manager = CheckpointManager(temp_checkpoint_file)

    def worker(idx):
        checkpoint = ReconstructionCheckpoint(
            file_hash=f"file{idx}",
            completed_xorbs={f"xorb{idx}"},
        )
        manager.save(checkpoint)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 所有 checkpoint 都应该被保存
    for i in range(10):
        loaded = manager.load(f"file{i}")
        assert loaded is not None
        assert loaded.file_hash == f"file{i}"


def test_thread_safety_mark_completed(temp_checkpoint_file):
    """测试多线程标记完成的线程安全性。"""
    manager = CheckpointManager(temp_checkpoint_file)

    def worker(idx):
        manager.mark_completed("file123", f"xorb{idx}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = manager.load("file123")
    assert loaded.completion_count() == 100


def test_thread_safety_mixed_operations(temp_checkpoint_file):
    """测试混合操作的线程安全性。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash="file123")
    manager.save(checkpoint)

    def mark_worker(idx):
        manager.mark_completed("file123", f"xorb{idx}")

    def load_worker():
        for _ in range(10):
            manager.load("file123")

    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=mark_worker, args=(i,)))
    for _ in range(5):
        threads.append(threading.Thread(target=load_worker))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = manager.load("file123")
    assert loaded.completion_count() == 10


# ============================================================================
# None path 处理测试
# ============================================================================

def test_operations_with_none_path():
    """测试 checkpoint_path 为 None 时的操作。"""
    manager = CheckpointManager(None)

    checkpoint = ReconstructionCheckpoint(file_hash="file123")

    # 所有操作都不应抛出异常
    manager.save(checkpoint)
    loaded = manager.load("file123")
    manager.mark_completed("file123", "xorb1")
    manager.clear("file123")

    # 但不应实际保存或加载任何内容
    assert loaded is None
