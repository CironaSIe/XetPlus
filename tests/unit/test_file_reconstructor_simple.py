"""pipeline.file_reconstructor 模块简化单元测试。"""
import pytest
import tempfile
import shutil
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from xet.pipeline.file_reconstructor import FileReconstructor, ReconstructionError


@pytest.fixture
def temp_dir():
    """创建临时目录。"""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def mock_cas_client():
    """创建 Mock CAS 客户端。"""
    client = Mock()

    # Mock get_reconstruction
    mock_recon = Mock()
    mock_recon.offset_into_first_range = 0
    mock_recon.terms = [Mock(unpacked_length=100)]
    mock_recon.fetch_info = {"xorb1": [Mock()]}

    client.get_reconstruction.return_value = mock_recon

    return client


# ============================================================================
# FileReconstructor 初始化测试
# ============================================================================

def test_file_reconstructor_creation(mock_cas_client, temp_dir):
    """测试创建 FileReconstructor。"""
    output_path = temp_dir / "output.bin"
    checkpoint_path = temp_dir / "checkpoint.json"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
        checkpoint_path=checkpoint_path,
        max_workers=4,
    )

    assert reconstructor.cas_client == mock_cas_client
    assert reconstructor.output_path == output_path
    assert reconstructor.checkpoint_manager is not None
    assert reconstructor.progress_tracker is not None
    assert reconstructor.scheduler is not None
    assert reconstructor.assembler is not None


def test_file_reconstructor_without_checkpoint(mock_cas_client, temp_dir):
    """测试不启用 checkpoint 的 FileReconstructor。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
        checkpoint_path=None,  # 不启用 checkpoint
    )

    assert reconstructor.checkpoint_manager is None


def test_file_reconstructor_with_callback(mock_cas_client, temp_dir):
    """测试带进度回调的 FileReconstructor。"""
    output_path = temp_dir / "output.bin"
    callback = Mock()

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
        progress_callback=callback,
    )

    assert reconstructor.progress_tracker is not None


def test_file_reconstructor_with_stop_event(mock_cas_client, temp_dir):
    """测试带 stop_event 的 FileReconstructor。"""
    output_path = temp_dir / "output.bin"
    stop_event = threading.Event()

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
        stop_event=stop_event,
    )

    assert reconstructor._stop_event == stop_event


# ============================================================================
# 端到端重建测试
# ============================================================================

def test_reconstruct_file_success(mock_cas_client, temp_dir):
    """测试成功重建文件。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    # Mock 下载和组装
    with patch.object(reconstructor.scheduler, "download_all_xorbs") as mock_download, \
         patch.object(reconstructor.assembler, "assemble_file") as mock_assemble:

        mock_download.return_value = {"xorb1": b"xorb_data"}

        # 创建输出文件（模拟组装）
        def create_output(*args, **kwargs):
            output_path.write_bytes(b"A" * 100)

        mock_assemble.side_effect = create_output

        result = reconstructor.reconstruct_file(
            file_hash="a" * 64,  # 使用 64 字符 hash
            expected_size=100,
        )

        assert result == output_path
        assert output_path.exists()
        assert output_path.stat().st_size == 100


def test_reconstruct_file_size_mismatch(mock_cas_client, temp_dir):
    """测试文件大小不匹配。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    with patch.object(reconstructor.scheduler, "download_all_xorbs") as mock_download, \
         patch.object(reconstructor.assembler, "assemble_file") as mock_assemble:

        mock_download.return_value = {}

        def create_wrong_size(*args, **kwargs):
            output_path.write_bytes(b"A" * 50)  # 实际 50，期望 100

        mock_assemble.side_effect = create_wrong_size

        with pytest.raises(ReconstructionError, match="文件大小不匹配"):
            reconstructor.reconstruct_file(
                file_hash="a" * 64,
                expected_size=100,
            )


def test_reconstruct_file_download_failure(mock_cas_client, temp_dir):
    """测试下载失败。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    with patch.object(reconstructor.scheduler, "download_all_xorbs") as mock_download:
        mock_download.side_effect = RuntimeError("Download failed")

        with pytest.raises(ReconstructionError, match="文件重建失败"):
            reconstructor.reconstruct_file(
                file_hash="a" * 64,
                expected_size=100,
            )


def test_reconstruct_file_keyboard_interrupt(mock_cas_client, temp_dir):
    """测试用户中断。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    with patch.object(reconstructor.scheduler, "download_all_xorbs") as mock_download:
        mock_download.side_effect = KeyboardInterrupt("用户中断")

        with pytest.raises(KeyboardInterrupt):
            reconstructor.reconstruct_file(
                file_hash="a" * 64,
                expected_size=100,
            )


# ============================================================================
# 进度获取测试
# ============================================================================

def test_get_progress(mock_cas_client, temp_dir):
    """测试获取进度信息。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    # 增加一些进度
    reconstructor.progress_tracker.set_total_bytes(1000)
    reconstructor.progress_tracker.increment_assembled(250)

    progress = reconstructor.get_progress()

    assert progress["total_bytes"] == 1000
    assert progress["assembled_bytes"] == 250
    assert progress["progress_pct"] == 25.0


def test_format_progress(mock_cas_client, temp_dir):
    """测试格式化进度。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    reconstructor.progress_tracker.set_total_bytes(1000)
    reconstructor.progress_tracker.increment_assembled(500)

    formatted = reconstructor.format_progress()

    assert "50.0%" in formatted


# ============================================================================
# 停止和清理测试
# ============================================================================

def test_stop(mock_cas_client, temp_dir):
    """测试停止重建。"""
    output_path = temp_dir / "output.bin"

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
    )

    # stop_event 应该未设置
    assert not reconstructor._stop_event.is_set()

    reconstructor.stop()

    # stop_event 应该被设置
    assert reconstructor._stop_event.is_set()


def test_cleanup_empty_temp_dir(mock_cas_client, temp_dir):
    """测试清理空的临时目录。"""
    output_path = temp_dir / "output.bin"
    temp_dir_path = temp_dir / "temp"
    temp_dir_path.mkdir()

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
        temp_dir=temp_dir_path,
    )

    # 临时目录应该存在且为空
    assert temp_dir_path.exists()

    reconstructor.cleanup()

    # 空的临时目录应该被删除
    assert not temp_dir_path.exists()


def test_cleanup_non_empty_temp_dir(mock_cas_client, temp_dir):
    """测试清理非空的临时目录。"""
    output_path = temp_dir / "output.bin"
    temp_dir_path = temp_dir / "temp"
    temp_dir_path.mkdir()

    # 在临时目录中创建一个文件
    (temp_dir_path / "file.txt").write_text("test")

    reconstructor = FileReconstructor(
        cas_client=mock_cas_client,
        output_path=output_path,
        temp_dir=temp_dir_path,
    )

    reconstructor.cleanup()

    # 非空的临时目录不应被删除
    assert temp_dir_path.exists()
