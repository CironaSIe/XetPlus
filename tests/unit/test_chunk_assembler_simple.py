"""pipeline.chunk_assembler 模块简化单元测试。"""
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from xet.pipeline.chunk_assembler import ChunkAssembler
from xet.pipeline.progress_tracker import ProgressTracker


@pytest.fixture
def temp_dir():
    """创建临时目录。"""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# ChunkAssembler 初始化测试
# ============================================================================

def test_chunk_assembler_creation(temp_dir):
    """测试创建 ChunkAssembler。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    assert assembler.temp_dir == temp_dir
    assert temp_dir.exists()


def test_chunk_assembler_none_temp_dir():
    """测试 temp_dir 为 None。"""
    assembler = ChunkAssembler(temp_dir=None)

    assert assembler.temp_dir is None


# ============================================================================
# 解压 xorb 测试
# ============================================================================

def test_decompress_all_xorbs(temp_dir):
    """测试解压所有 xorb。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    xorb_data_map = {
        "xorb1": b"compressed_xorb1",
        "xorb2": b"compressed_xorb2",
    }

    # Mock decompress_xorb 函数
    with patch("xet.pipeline.chunk_assembler.decompress_xorb") as mock_decompress:
        mock_decompress.side_effect = [
            {"chunk1": b"chunk1_data"},
            {"chunk2": b"chunk2_data"},
        ]

        chunk_cache = assembler._decompress_all_xorbs(xorb_data_map)

        assert len(chunk_cache) == 2
        assert chunk_cache["chunk1"] == b"chunk1_data"
        assert chunk_cache["chunk2"] == b"chunk2_data"

        # 验证调用
        assert mock_decompress.call_count == 2


def test_decompress_all_xorbs_merge_chunks(temp_dir):
    """测试解压时合并多个 xorb 的 chunk。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    xorb_data_map = {
        "xorb1": b"compressed_xorb1",
        "xorb2": b"compressed_xorb2",
    }

    with patch("xet.pipeline.chunk_assembler.decompress_xorb") as mock_decompress:
        # 第一个 xorb 包含 chunk1 和 chunk2
        # 第二个 xorb 包含 chunk3
        mock_decompress.side_effect = [
            {"chunk1": b"data1", "chunk2": b"data2"},
            {"chunk3": b"data3"},
        ]

        chunk_cache = assembler._decompress_all_xorbs(xorb_data_map)

        assert len(chunk_cache) == 3
        assert "chunk1" in chunk_cache
        assert "chunk2" in chunk_cache
        assert "chunk3" in chunk_cache


def test_decompress_all_xorbs_failure(temp_dir):
    """测试解压失败。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    xorb_data_map = {"xorb1": b"corrupted"}

    with patch("xet.pipeline.chunk_assembler.decompress_xorb") as mock_decompress:
        mock_decompress.side_effect = RuntimeError("Decompress failed")

        with pytest.raises(RuntimeError, match="解压 xorb 失败"):
            assembler._decompress_all_xorbs(xorb_data_map)


def test_decompress_all_xorbs_missing_library(temp_dir):
    """测试缺少 merkle-hash-rust 库。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    xorb_data_map = {"xorb1": b"data"}

    with patch("xet.pipeline.chunk_assembler.decompress_xorb", side_effect=ImportError):
        with pytest.raises(ImportError, match="需要 merkle-hash-rust 库"):
            assembler._decompress_all_xorbs(xorb_data_map)


# ============================================================================
# 获取 chunk 数据测试
# ============================================================================

def test_get_chunk_data_success(temp_dir):
    """测试从缓存获取 chunk 数据。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    chunk_cache = {
        "chunk1": b"data1",
        "chunk2": b"data2",
    }

    data = assembler._get_chunk_data("chunk1", chunk_cache)

    assert data == b"data1"


def test_get_chunk_data_missing(temp_dir):
    """测试获取缺失的 chunk。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    chunk_cache = {"chunk1": b"data1"}

    with pytest.raises(ValueError, match="Chunk 缺失"):
        assembler._get_chunk_data("chunk_missing", chunk_cache)
