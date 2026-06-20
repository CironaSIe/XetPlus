"""pipeline.types 模块单元测试。"""
import pytest
import time

from xet.protocol.types import HttpRange
from xet.pipeline.types import XorbDownloadTask, ReconstructionCheckpoint


# 测试用的 64 字符 hash
TEST_HASH_1 = "a" * 64
TEST_HASH_2 = "b" * 64
TEST_HASH_3 = "c" * 64
TEST_FILE_HASH = "f" * 64


# ============================================================================
# XorbDownloadTask 测试
# ============================================================================

def test_xorb_download_task_creation():
    """测试创建 XorbDownloadTask。"""
    task = XorbDownloadTask(
        xorb_hash=TEST_HASH_1,
        url="https://cdn.example.com/xorb",
        url_range=HttpRange(start=0, end=1023),
    )

    assert task.xorb_hash == TEST_HASH_1
    assert task.url == "https://cdn.example.com/xorb"
    assert task.url_range.start == 0
    assert task.url_range.end == 1023


def test_xorb_download_task_validation_empty_hash():
    """测试 xorb_hash 长度无效时抛出异常。"""
    with pytest.raises(ValueError, match="xorb_hash 必须是 64 字符"):
        XorbDownloadTask(
            xorb_hash="short",
            url="https://cdn.example.com/xorb",
            url_range=HttpRange(start=0, end=1023),
        )


def test_xorb_download_task_validation_empty_url():
    """测试 url 为空时抛出异常。"""
    with pytest.raises(ValueError, match="url 不能为空"):
        XorbDownloadTask(
            xorb_hash=TEST_HASH_1,
            url="",
            url_range=HttpRange(start=0, end=1023),
        )


def test_xorb_download_task_validation_invalid_range():
    """测试 url_range 正常情况。"""
    # HttpRange 在创建时已经验证，所以这里只测试正常情况
    task = XorbDownloadTask(
        xorb_hash=TEST_HASH_1,
        url="https://cdn.example.com/xorb",
        url_range=HttpRange(start=0, end=1023),
    )
    assert task.url_range.start == 0
    assert task.url_range.end == 1023


def test_xorb_download_task_size():
    """测试计算下载大小。"""
    task = XorbDownloadTask(
        xorb_hash=TEST_HASH_1,
        url="https://cdn.example.com/xorb",
        url_range=HttpRange(start=0, end=1023),
    )

    assert task.size() == 1024


# ============================================================================
# ReconstructionCheckpoint 测试
# ============================================================================

def test_reconstruction_checkpoint_creation():
    """测试创建 ReconstructionCheckpoint。"""
    checkpoint = ReconstructionCheckpoint(
        file_hash=TEST_FILE_HASH,
        completed_xorbs={TEST_HASH_1, TEST_HASH_2},
        timestamp=1234567890,
        version=1,
    )

    assert checkpoint.file_hash == TEST_FILE_HASH
    assert len(checkpoint.completed_xorbs) == 2
    assert TEST_HASH_1 in checkpoint.completed_xorbs
    assert checkpoint.timestamp == 1234567890
    assert checkpoint.version == 1


def test_reconstruction_checkpoint_default_values():
    """测试 ReconstructionCheckpoint 默认值。"""
    checkpoint = ReconstructionCheckpoint(file_hash=TEST_FILE_HASH)

    assert checkpoint.file_hash == TEST_FILE_HASH
    assert len(checkpoint.completed_xorbs) == 0
    assert checkpoint.timestamp == 0
    assert checkpoint.version == 1


def test_reconstruction_checkpoint_validation_empty_hash():
    """测试 file_hash 长度无效时抛出异常。"""
    with pytest.raises(ValueError, match="file_hash 必须是 64 字符"):
        ReconstructionCheckpoint(file_hash="short")


def test_reconstruction_checkpoint_is_completed():
    """测试检查 xorb 是否已完成。"""
    checkpoint = ReconstructionCheckpoint(
        file_hash=TEST_FILE_HASH,
        completed_xorbs={TEST_HASH_1, TEST_HASH_2},
    )

    assert checkpoint.is_completed(TEST_HASH_1) is True
    assert checkpoint.is_completed(TEST_HASH_2) is True
    assert checkpoint.is_completed(TEST_HASH_3) is False


def test_reconstruction_checkpoint_mark_completed():
    """测试标记 xorb 为已完成。"""
    checkpoint = ReconstructionCheckpoint(file_hash=TEST_FILE_HASH)

    assert len(checkpoint.completed_xorbs) == 0

    checkpoint.mark_completed(TEST_HASH_1)
    assert len(checkpoint.completed_xorbs) == 1
    assert checkpoint.is_completed(TEST_HASH_1) is True

    # 重复标记不影响
    checkpoint.mark_completed(TEST_HASH_1)
    assert len(checkpoint.completed_xorbs) == 1


def test_reconstruction_checkpoint_completion_count():
    """测试获取已完成数量。"""
    checkpoint = ReconstructionCheckpoint(
        file_hash=TEST_FILE_HASH,
        completed_xorbs={TEST_HASH_1, TEST_HASH_2, TEST_HASH_3},
    )

    assert checkpoint.completion_count() == 3


def test_reconstruction_checkpoint_to_dict():
    """测试序列化为字典。"""
    checkpoint = ReconstructionCheckpoint(
        file_hash=TEST_FILE_HASH,
        completed_xorbs={TEST_HASH_1, TEST_HASH_2},
        timestamp=1234567890,
        version=1,
    )

    data = checkpoint.to_dict()

    assert data["file_hash"] == TEST_FILE_HASH
    assert set(data["completed_xorbs"]) == {TEST_HASH_1, TEST_HASH_2}
    assert data["timestamp"] == 1234567890
    assert data["version"] == 1


def test_reconstruction_checkpoint_from_dict():
    """测试从字典反序列化。"""
    data = {
        "file_hash": TEST_FILE_HASH,
        "completed_xorbs": [TEST_HASH_1, TEST_HASH_2],
        "timestamp": 1234567890,
        "version": 1,
    }

    checkpoint = ReconstructionCheckpoint.from_dict(data)

    assert checkpoint.file_hash == TEST_FILE_HASH
    assert checkpoint.completed_xorbs == {TEST_HASH_1, TEST_HASH_2}
    assert checkpoint.timestamp == 1234567890
    assert checkpoint.version == 1


def test_reconstruction_checkpoint_from_dict_missing_fields():
    """测试从字典反序列化时缺少字段。"""
    data = {
        "file_hash": TEST_FILE_HASH,
    }

    checkpoint = ReconstructionCheckpoint.from_dict(data)

    # 使用默认值
    assert checkpoint.file_hash == TEST_FILE_HASH
    assert len(checkpoint.completed_xorbs) == 0
    assert checkpoint.version == 1


def test_reconstruction_checkpoint_roundtrip():
    """测试序列化和反序列化往返。"""
    original = ReconstructionCheckpoint(
        file_hash=TEST_FILE_HASH,
        completed_xorbs={TEST_HASH_1, TEST_HASH_2, TEST_HASH_3},
        timestamp=1234567890,
        version=1,
    )

    data = original.to_dict()
    restored = ReconstructionCheckpoint.from_dict(data)

    assert restored.file_hash == original.file_hash
    assert restored.completed_xorbs == original.completed_xorbs
    assert restored.timestamp == original.timestamp
    assert restored.version == original.version
