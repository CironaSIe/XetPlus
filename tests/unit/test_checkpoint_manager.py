"""pipeline.checkpoint_manager 模块单元测试。"""
import pytest
import json
import tempfile
import shutil
import threading
from pathlib import Path

from xet.pipeline.checkpoint_manager import CheckpointManager
from xet.pipeline.types import ReconstructionCheckpoint

# 有效的 64 字符 hex hash（用于测试）
VALID_HASH = "a" * 64
VALID_HASH_2 = "b" * 64


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
    assert manager._cache is None


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
        file_hash=VALID_HASH,
        completed_xorbs={"xorb1", "xorb2"},
        timestamp=1234567890,
    )

    # 保存
    manager.save(checkpoint)

    # 加载
    loaded = manager.load(VALID_HASH)

    assert loaded is not None
    assert loaded.file_hash == VALID_HASH
    assert loaded.completed_xorbs == {"xorb1", "xorb2"}
    assert loaded.timestamp == 1234567890


def test_load_nonexistent_checkpoint(temp_checkpoint_file):
    """测试加载不存在的 checkpoint（hash 不匹配）。"""
    manager = CheckpointManager(temp_checkpoint_file)

    # 先存一个不同 hash 的 checkpoint
    cp = ReconstructionCheckpoint(file_hash=VALID_HASH)
    manager.save(cp)

    # 用另一个 hash 加载应返回 None
    loaded = manager.load(VALID_HASH_2)

    assert loaded is None


def test_load_empty_file(temp_checkpoint_file):
    """测试加载空的 checkpoint 文件。"""
    temp_checkpoint_file.touch()

    manager = CheckpointManager(temp_checkpoint_file)

    loaded = manager.load(VALID_HASH)
    assert loaded is None


def test_save_creates_directory(temp_checkpoint_file):
    """测试保存时自动创建目录。"""
    shutil.rmtree(temp_checkpoint_file.parent, ignore_errors=True)

    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash=VALID_HASH)
    manager.save(checkpoint)

    assert temp_checkpoint_file.parent.exists()
    assert temp_checkpoint_file.exists()


def test_save_overwrites_existing(temp_checkpoint_file):
    """测试保存覆盖已有 checkpoint。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint1 = ReconstructionCheckpoint(
        file_hash=VALID_HASH,
        completed_xorbs={"xorb1"},
    )
    checkpoint2 = ReconstructionCheckpoint(
        file_hash=VALID_HASH,
        completed_xorbs={"xorb1", "xorb2", "xorb3"},
    )

    manager.save(checkpoint1)
    manager.save(checkpoint2)

    loaded = manager.load(VALID_HASH)
    assert len(loaded.completed_xorbs) == 3


def test_hash_mismatch_returns_none(temp_checkpoint_file):
    """测试文件中 hash 与请求不匹配时返回 None。"""
    manager = CheckpointManager(temp_checkpoint_file)

    # 存 VALID_HASH
    manager.save(ReconstructionCheckpoint(file_hash=VALID_HASH))

    # 用不同的 hash 查询
    result = manager.load(VALID_HASH_2)
    assert result is None


# ============================================================================
# 增量更新测试
# ============================================================================

def test_mark_completed_new_checkpoint(temp_checkpoint_file):
    """测试标记完成（新 checkpoint）。"""
    manager = CheckpointManager(temp_checkpoint_file)

    manager.mark_completed(VALID_HASH, "xorb1")

    loaded = manager.load(VALID_HASH)
    assert loaded is not None
    assert loaded.is_completed("xorb1")


def test_mark_completed_existing_checkpoint(temp_checkpoint_file):
    """测试标记完成（已有 checkpoint）。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash=VALID_HASH,
        completed_xorbs={"xorb1"},
    )
    manager.save(checkpoint)

    manager.mark_completed(VALID_HASH, "xorb2")

    loaded = manager.load(VALID_HASH)
    assert loaded.is_completed("xorb1")
    assert loaded.is_completed("xorb2")


def test_mark_completed_idempotent(temp_checkpoint_file):
    """测试重复标记完成是幂等的。"""
    manager = CheckpointManager(temp_checkpoint_file)

    manager.mark_completed(VALID_HASH, "xorb1")
    manager.mark_completed(VALID_HASH, "xorb1")  # 重复

    loaded = manager.load(VALID_HASH)
    assert loaded.completion_count() == 1


# ============================================================================
# 清理测试
# ============================================================================

def test_clear_checkpoint(temp_checkpoint_file):
    """测试 clear 操作（删除文件）。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash=VALID_HASH,
        completed_xorbs={"xorb1", "xorb2"},
    )
    manager.save(checkpoint)

    manager.clear(VALID_HASH)

    # 文件应被删除
    assert not temp_checkpoint_file.exists()


def test_clear_nonexistent_checkpoint(temp_checkpoint_file):
    """测试清理不存在的 checkpoint 不抛异常。"""
    manager = CheckpointManager(temp_checkpoint_file)
    manager.clear("nonexistent")  # 不应抛异常


# ============================================================================
# 缓存机制测试
# ============================================================================

def test_cache_after_load(temp_checkpoint_file):
    """测试加载后缓存。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash=VALID_HASH)
    manager.save(checkpoint)

    # 第一次加载（从文件）
    loaded1 = manager.load(VALID_HASH)

    # 缓存应该被设置
    assert manager._cache is not None
    assert manager._cache.file_hash == VALID_HASH

    # 第二次加载（从文件，值相同）
    loaded2 = manager.load(VALID_HASH)

    # 值应相同（不保证同一对象，因为 load 每次从文件重建）
    assert loaded1.file_hash == loaded2.file_hash
    assert loaded1.completed_xorbs == loaded2.completed_xorbs


def test_cache_after_save(temp_checkpoint_file):
    """测试保存后缓存。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash=VALID_HASH)
    manager.save(checkpoint)

    # 缓存应该被更新
    assert manager._cache is not None
    assert manager._cache.file_hash == VALID_HASH


def test_cache_cleared_after_clear(temp_checkpoint_file):
    """测试清理后缓存被移除。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash=VALID_HASH)
    manager.save(checkpoint)

    # 确保缓存存在
    assert manager._cache is not None

    manager.clear(VALID_HASH)

    # 缓存应该被清空
    assert manager._cache is None


# ============================================================================
# 文件格式测试
# ============================================================================

def test_checkpoint_file_format(temp_checkpoint_file):
    """测试 checkpoint 文件格式。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(
        file_hash=VALID_HASH,
        completed_xorbs={"xorb1", "xorb2"},
        timestamp=1234567890,
    )
    manager.save(checkpoint)

    with open(temp_checkpoint_file, 'r') as f:
        data = json.load(f)

    # 文件格式是扁平的 JSON 对象（非嵌套 dict）
    assert data["file_hash"] == VALID_HASH
    assert "completed_xorbs" in data
    assert "timestamp" in data
    assert data["version"] >= 1


def test_load_corrupted_checkpoint(temp_checkpoint_file):
    """测试加载损坏的 checkpoint 文件返回 None。"""
    with open(temp_checkpoint_file, 'w') as f:
        f.write("invalid json {")

    manager = CheckpointManager(temp_checkpoint_file)
    loaded = manager.load(VALID_HASH)
    assert loaded is None


# ============================================================================
# 线程安全测试
# ============================================================================

def test_thread_safety_mark_completed(temp_checkpoint_file):
    """测试多线程标记完成的线程安全性。"""
    manager = CheckpointManager(temp_checkpoint_file)

    def worker(idx):
        manager.mark_completed(VALID_HASH, f"xorb{idx}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = manager.load(VALID_HASH)
    assert loaded.completion_count() == 100


def test_thread_safety_mixed_operations(temp_checkpoint_file):
    """测试混合操作的线程安全性。"""
    manager = CheckpointManager(temp_checkpoint_file)

    checkpoint = ReconstructionCheckpoint(file_hash=VALID_HASH)
    manager.save(checkpoint)

    def mark_worker(idx):
        manager.mark_completed(VALID_HASH, f"xorb{idx}")

    def load_worker():
        for _ in range(10):
            manager.load(VALID_HASH)

    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=mark_worker, args=(i,)))
    for _ in range(5):
        threads.append(threading.Thread(target=load_worker))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = manager.load(VALID_HASH)
    assert loaded.completion_count() == 10


# ============================================================================
# None path 处理测试
# ============================================================================

def test_operations_with_none_path():
    """测试 checkpoint_path 为 None 时的操作。"""
    manager = CheckpointManager(None)

    checkpoint = ReconstructionCheckpoint(file_hash=VALID_HASH)

    # 所有操作都不应抛出异常
    manager.save(checkpoint)
    loaded = manager.load(VALID_HASH)
    manager.mark_completed(VALID_HASH, "xorb1")
    manager.clear(VALID_HASH)

    # 但不应实际保存或加载任何内容
    assert loaded is None
