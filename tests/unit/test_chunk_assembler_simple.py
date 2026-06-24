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
# 解压 xorb 测试（当前 API: _decompress_single_xorb）
# ============================================================================

def test_decompress_single_xorb_interface(temp_dir):
    """测试 _decompress_single_xorb 方法存在且可调用。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    # 确认方法存在
    assert hasattr(assembler, '_decompress_single_xorb')
    assert callable(assembler._decompress_single_xorb)


def test_decompress_single_xorb_bad_hash(temp_dir):
    """测试传入无效 hash 时抛出异常。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    mock_recon = Mock()
    mock_recon.fetch_info = {}  # 空 fetch_info，任何 hash 都找不到

    with pytest.raises(ValueError, match="没有 fetch_info"):
        assembler._decompress_single_xorb("unknown_xorb", b"data", mock_recon)


def test_decompress_single_xorb_import_error_handling(temp_dir):
    """测试缺少依赖库时的 ImportError 处理。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    mock_recon = Mock()
    mock_recon.fetch_info = {"xorb1": [Mock(chunk_range=Mock(start=0), url_range=Mock(length=lambda: 100))]}

    # Mock XorbDeserializer import to raise ImportError
    with patch.dict('sys.modules', {'xet.storage.xorb_deserializer': None}):
        with pytest.raises(ImportError, match="需要 lz4 和 blake3 库"):
            assembler._decompress_single_xorb("xorb1", b"data", mock_recon)


def test_chunk_assembler_xorb_cache(temp_dir):
    """测试 xorb 内存缓存。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    # 初始缓存为空
    assert len(assembler._xorb_cache) == 0

    # 模拟缓存写入（使用简单的 Mock 数据）
    mock_xorb_data = Mock()
    assembler._xorb_cache["test_xorb"] = mock_xorb_data

    assert "test_xorb" in assembler._xorb_cache
    assert len(assembler._xorb_cache) == 1


def test_chunk_assembler_prefetch_interface(temp_dir):
    """测试 assemble_file_with_prefetch 接口存在。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    # 确认新 API 方法存在
    assert hasattr(assembler, 'assemble_file_with_prefetch')
    assert callable(assembler.assemble_file_with_prefetch)


def test_chunk_assembler_temp_dir_handling(temp_dir):
    """测试临时目录处理。"""
    assembler = ChunkAssembler(temp_dir=temp_dir)

    assert assembler.temp_dir == temp_dir

    # None temp_dir 也应该工作
    assembler_none = ChunkAssembler(temp_dir=None)
    assert assembler_none.temp_dir is None
