"""storage.checkpoint 模块单元测试。"""
import pytest
from pathlib import Path
import tempfile
import shutil
import time
import json

from xet.storage.checkpoint import (
    DownloadCheckpoint,
    CheckpointManager,
    create_checkpoint,
)


@pytest.fixture
def temp_dir():
    """创建临时目录。"""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# DownloadCheckpoint 测试
# ============================================================================

def test_checkpoint_creation():
    """测试创建 checkpoint。"""
    checkpoint = DownloadCheckpoint(
        file_path="/path/to/file.bin",
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0, 1, 2],
        bytes_written=512,
        last_update=time.time()
    )

    assert checkpoint.file_path == "/path/to/file.bin"
    assert checkpoint.file_size == 1024
    assert len(checkpoint.completed_terms) == 3


def test_checkpoint_to_dict():
    """测试转换为字典。"""
    checkpoint = DownloadCheckpoint(
        file_path="/path/to/file.bin",
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0, 1],
        bytes_written=512,
        last_update=1234567890.0
    )

    data = checkpoint.to_dict()

    assert data['file_path'] == "/path/to/file.bin"
    assert data['file_size'] == 1024
    assert data['xet_hash'] == "abc123"
    assert data['completed_terms'] == [0, 1]


def test_checkpoint_from_dict():
    """测试从字典创建。"""
    data = {
        'file_path': "/path/to/file.bin",
        'file_size': 1024,
        'xet_hash': "abc123",
        'sha256': "def456",
        'completed_terms': [0, 1, 2],
        'bytes_written': 512,
        'last_update': 1234567890.0
    }

    checkpoint = DownloadCheckpoint.from_dict(data)

    assert checkpoint.file_path == "/path/to/file.bin"
    assert checkpoint.file_size == 1024
    assert checkpoint.completed_terms == [0, 1, 2]


def test_checkpoint_save_load(temp_dir):
    """测试保存和加载。"""
    checkpoint_path = temp_dir / "checkpoint.json"

    # 保存
    checkpoint = DownloadCheckpoint(
        file_path="/path/to/file.bin",
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0, 1, 2],
        bytes_written=512,
        last_update=1234567890.0
    )
    checkpoint.save(checkpoint_path)

    # 加载
    loaded = DownloadCheckpoint.load(checkpoint_path)

    assert loaded is not None
    assert loaded.file_path == checkpoint.file_path
    assert loaded.file_size == checkpoint.file_size
    assert loaded.completed_terms == checkpoint.completed_terms


def test_checkpoint_load_nonexistent(temp_dir):
    """测试加载不存在的文件。"""
    checkpoint_path = temp_dir / "nonexistent.json"

    loaded = DownloadCheckpoint.load(checkpoint_path)

    assert loaded is None


def test_checkpoint_load_corrupted(temp_dir):
    """测试加载损坏的 JSON。"""
    checkpoint_path = temp_dir / "corrupted.json"

    # 写入无效 JSON
    checkpoint_path.write_text("{ invalid json", encoding='utf-8')

    loaded = DownloadCheckpoint.load(checkpoint_path)

    assert loaded is None


def test_checkpoint_is_complete():
    """测试完成检查。"""
    checkpoint = DownloadCheckpoint(
        file_path="/path/to/file.bin",
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0, 1, 2],
        bytes_written=512,
        last_update=time.time()
    )

    assert checkpoint.is_complete(total_terms=3)
    assert not checkpoint.is_complete(total_terms=5)


def test_checkpoint_mark_term_completed():
    """测试标记 term 完成。"""
    checkpoint = DownloadCheckpoint(
        file_path="/path/to/file.bin",
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[],
        bytes_written=0,
        last_update=time.time()
    )

    initial_time = checkpoint.last_update

    # 等待一小段时间
    time.sleep(0.01)

    # 标记完成
    checkpoint.mark_term_completed(term_index=0, term_size=100)

    assert 0 in checkpoint.completed_terms
    assert checkpoint.bytes_written == 100
    assert checkpoint.last_update > initial_time

    # 重复标记（应该不重复计数）
    checkpoint.mark_term_completed(term_index=0, term_size=100)
    assert checkpoint.completed_terms.count(0) == 1
    assert checkpoint.bytes_written == 100  # 不增加


def test_checkpoint_get_pending_terms():
    """测试获取待下载的 terms。"""
    checkpoint = DownloadCheckpoint(
        file_path="/path/to/file.bin",
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0, 2, 4],
        bytes_written=512,
        last_update=time.time()
    )

    pending = checkpoint.get_pending_terms(total_terms=6)

    assert pending == [1, 3, 5]


# ============================================================================
# CheckpointManager 测试
# ============================================================================

def test_checkpoint_manager_init(temp_dir):
    """测试 CheckpointManager 初始化。"""
    file_path = temp_dir / "output.bin"

    manager = CheckpointManager(file_path)

    assert manager.file_path == file_path
    assert manager.checkpoint_path == file_path.with_suffix('.bin.xet-checkpoint.json')
    assert manager.part_path == file_path.with_suffix('.bin.part')


def test_checkpoint_manager_save_load(temp_dir):
    """测试保存和加载。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    # 保存
    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0, 1],
        bytes_written=512,
        last_update=time.time()
    )
    manager.save_checkpoint(checkpoint)

    # 加载
    loaded = manager.load_checkpoint()

    assert loaded is not None
    assert loaded.file_path == str(file_path)
    assert loaded.completed_terms == [0, 1]


def test_checkpoint_manager_atomic_save(temp_dir):
    """测试原子保存（使用临时文件）。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=256,
        last_update=time.time()
    )

    manager.save_checkpoint(checkpoint)

    # 临时文件应该不存在（已重命名）
    tmp_path = manager.checkpoint_path.with_suffix('.tmp')
    assert not tmp_path.exists()

    # checkpoint 文件存在
    assert manager.checkpoint_path.exists()


def test_checkpoint_manager_verify_partial_file(temp_dir):
    """测试验证 .part 文件。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=512,
        last_update=time.time()
    )

    # 创建正确大小的 .part 文件
    manager.part_path.write_bytes(b'\0' * 1024)

    # 验证应该通过
    assert manager.verify_partial_file(checkpoint)


def test_checkpoint_manager_verify_partial_file_missing(temp_dir):
    """测试验证不存在的 .part 文件。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=512,
        last_update=time.time()
    )

    # .part 文件不存在
    assert not manager.verify_partial_file(checkpoint)


def test_checkpoint_manager_verify_partial_file_wrong_size(temp_dir):
    """测试验证大小错误的 .part 文件。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=512,
        last_update=time.time()
    )

    # 创建错误大小的 .part 文件
    manager.part_path.write_bytes(b'\0' * 2048)

    # 验证应该失败
    assert not manager.verify_partial_file(checkpoint)


def test_checkpoint_manager_clear(temp_dir):
    """测试清除 checkpoint 文件。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    # 创建 checkpoint
    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=512,
        last_update=time.time()
    )
    manager.save_checkpoint(checkpoint)

    assert manager.checkpoint_path.exists()

    # 清除
    manager.clear()

    assert not manager.checkpoint_path.exists()


def test_checkpoint_manager_clear_all(temp_dir):
    """测试清除所有临时文件。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    # 创建 checkpoint 和 .part 文件
    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=512,
        last_update=time.time()
    )
    manager.save_checkpoint(checkpoint)
    manager.part_path.write_bytes(b'\0' * 1024)

    assert manager.checkpoint_path.exists()
    assert manager.part_path.exists()

    # 清除所有
    manager.clear_all()

    assert not manager.checkpoint_path.exists()
    assert not manager.part_path.exists()


def test_checkpoint_manager_should_resume_yes(temp_dir):
    """测试应该恢复下载的场景。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    xet_hash = "abc123"
    file_size = 1024

    # 创建有效的 checkpoint 和 .part 文件
    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=file_size,
        xet_hash=xet_hash,
        sha256="def456",
        completed_terms=[0, 1, 2],
        bytes_written=700,  # 68% 完成
        last_update=time.time()
    )
    manager.save_checkpoint(checkpoint)
    manager.part_path.write_bytes(b'\0' * file_size)

    # 应该恢复
    assert manager.should_resume(xet_hash, file_size)


def test_checkpoint_manager_should_resume_no_checkpoint(temp_dir):
    """测试没有 checkpoint 的场景。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    # 没有 checkpoint，不应该恢复
    assert not manager.should_resume("abc123", 1024)


def test_checkpoint_manager_should_resume_different_hash(temp_dir):
    """测试不同 hash 的场景。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    # 创建 checkpoint
    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=1024,
        xet_hash="old_hash",
        sha256="def456",
        completed_terms=[0],
        bytes_written=512,
        last_update=time.time()
    )
    manager.save_checkpoint(checkpoint)
    manager.part_path.write_bytes(b'\0' * 1024)

    # hash 不同，不应该恢复
    assert not manager.should_resume("new_hash", 1024)


def test_checkpoint_manager_should_resume_too_little_progress(temp_dir):
    """测试进度太少的场景。"""
    file_path = temp_dir / "output.bin"
    manager = CheckpointManager(file_path)

    file_size = 1024

    # 只完成了 5%
    checkpoint = DownloadCheckpoint(
        file_path=str(file_path),
        file_size=file_size,
        xet_hash="abc123",
        sha256="def456",
        completed_terms=[0],
        bytes_written=50,  # 5%
        last_update=time.time()
    )
    manager.save_checkpoint(checkpoint)
    manager.part_path.write_bytes(b'\0' * file_size)

    # 进度太少（< 10%），不应该恢复
    assert not manager.should_resume("abc123", file_size, min_completed_ratio=0.1)


# ============================================================================
# create_checkpoint 工厂函数测试
# ============================================================================

def test_create_checkpoint_factory():
    """测试工厂函数。"""
    file_path = Path("/path/to/file.bin")

    checkpoint = create_checkpoint(
        file_path=file_path,
        file_size=1024,
        xet_hash="abc123",
        sha256="def456"
    )

    assert checkpoint.file_path == str(file_path)
    assert checkpoint.file_size == 1024
    assert checkpoint.xet_hash == "abc123"
    assert checkpoint.sha256 == "def456"
    assert checkpoint.completed_terms == []
    assert checkpoint.bytes_written == 0
    assert checkpoint.last_update > 0
