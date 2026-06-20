"""storage.writer 模块单元测试。"""
import pytest
from pathlib import Path
import tempfile
import shutil

from xet.storage.writer import (
    FileWriter,
    SequentialWriter,
    GlobalWriter,
    create_writer,
)


@pytest.fixture
def temp_dir():
    """创建临时目录。"""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# SequentialWriter 测试
# ============================================================================

def test_sequential_writer_basic(temp_dir):
    """测试基本顺序写入。"""
    output_path = temp_dir / "output.bin"

    writer = SequentialWriter(output_path)
    writer.write_at(0, b"hello")
    writer.write_at(5, b"world")
    writer.close()

    # 验证文件内容
    assert output_path.exists()
    assert output_path.read_bytes() == b"helloworld"


def test_sequential_writer_out_of_order(temp_dir):
    """测试乱序写入（应该失败）。"""
    output_path = temp_dir / "output.bin"

    writer = SequentialWriter(output_path)
    writer.write_at(0, b"hello")

    # 尝试回退偏移
    with pytest.raises(ValueError, match="只支持顺序写入"):
        writer.write_at(3, b"xxx")

    writer.close()


def test_sequential_writer_context_manager(temp_dir):
    """测试 context manager 支持。"""
    output_path = temp_dir / "output.bin"

    with SequentialWriter(output_path) as writer:
        writer.write_at(0, b"data1")
        writer.write_at(5, b"data2")

    # 自动关闭
    assert output_path.exists()
    assert output_path.read_bytes() == b"data1data2"


def test_sequential_writer_closed(temp_dir):
    """测试关闭后写入（应该失败）。"""
    output_path = temp_dir / "output.bin"

    writer = SequentialWriter(output_path)
    writer.close()

    with pytest.raises(RuntimeError, match="已关闭"):
        writer.write_at(0, b"data")


def test_sequential_writer_flush(temp_dir):
    """测试 flush 操作。"""
    output_path = temp_dir / "output.bin"

    writer = SequentialWriter(output_path)
    writer.write_at(0, b"data")
    writer.flush()  # 应该不报错
    writer.close()


def test_sequential_writer_empty(temp_dir):
    """测试不写入任何数据就关闭。"""
    output_path = temp_dir / "output.bin"

    writer = SequentialWriter(output_path)
    writer.close()

    # 文件不应该被创建
    assert not output_path.exists()


# ============================================================================
# GlobalWriter 测试
# ============================================================================

def test_global_writer_basic(temp_dir):
    """测试基本随机写入。"""
    output_path = temp_dir / "output.bin"
    total_size = 10

    writer = GlobalWriter(output_path, total_size)
    writer.write_at(0, b"hello")
    writer.write_at(5, b"world")
    writer.finalize()

    # 验证文件内容
    assert output_path.exists()
    data = output_path.read_bytes()
    assert data[:5] == b"hello"
    assert data[5:10] == b"world"


def test_global_writer_random_access(temp_dir):
    """测试随机访问写入。"""
    output_path = temp_dir / "output.bin"
    total_size = 100

    writer = GlobalWriter(output_path, total_size)

    # 先写中间
    writer.write_at(50, b"middle")

    # 再写开头
    writer.write_at(0, b"start")

    # 最后写结尾
    writer.write_at(94, b"end")

    writer.finalize()

    # 验证
    data = output_path.read_bytes()
    assert data[0:5] == b"start"
    assert data[50:56] == b"middle"
    assert data[94:97] == b"end"


def test_global_writer_part_file(temp_dir):
    """测试 .part 文件机制。"""
    output_path = temp_dir / "output.bin"
    part_path = output_path.with_suffix('.bin.part')
    total_size = 10

    writer = GlobalWriter(output_path, total_size)

    # .part 文件应该存在
    assert part_path.exists()
    assert not output_path.exists()

    writer.write_at(0, b"hello")
    writer.finalize()

    # finalize 后 .part 被重命名
    assert output_path.exists()
    assert not part_path.exists()


def test_global_writer_bounds_check(temp_dir):
    """测试越界检查。"""
    output_path = temp_dir / "output.bin"
    total_size = 10

    writer = GlobalWriter(output_path, total_size)

    # 尝试越界写入
    with pytest.raises(ValueError, match="写入越界"):
        writer.write_at(8, b"toolong")

    writer.close()


def test_global_writer_negative_offset(temp_dir):
    """测试负偏移。"""
    output_path = temp_dir / "output.bin"
    total_size = 10

    writer = GlobalWriter(output_path, total_size)

    with pytest.raises(ValueError, match="不能为负数"):
        writer.write_at(-1, b"data")

    writer.close()


def test_global_writer_invalid_total_size(temp_dir):
    """测试无效的 total_size。"""
    output_path = temp_dir / "output.bin"

    with pytest.raises(ValueError, match="必须 > 0"):
        GlobalWriter(output_path, 0)

    with pytest.raises(ValueError, match="必须 > 0"):
        GlobalWriter(output_path, -100)


def test_global_writer_write_after_finalize(temp_dir):
    """测试 finalize 后写入（应该失败）。"""
    output_path = temp_dir / "output.bin"
    total_size = 10

    writer = GlobalWriter(output_path, total_size)
    writer.write_at(0, b"data")
    writer.finalize()

    # finalize 后不能再写入
    with pytest.raises(RuntimeError, match="已 finalize"):
        writer.write_at(5, b"more")


def test_global_writer_double_finalize(temp_dir):
    """测试重复 finalize（应该失败）。"""
    output_path = temp_dir / "output.bin"
    total_size = 10

    writer = GlobalWriter(output_path, total_size)
    writer.write_at(0, b"data")
    writer.finalize()

    with pytest.raises(RuntimeError, match="已经 finalize 过"):
        writer.finalize()


def test_global_writer_close_without_finalize(temp_dir):
    """测试 close 而不 finalize（.part 文件保留）。"""
    output_path = temp_dir / "output.bin"
    part_path = output_path.with_suffix('.bin.part')
    total_size = 10

    writer = GlobalWriter(output_path, total_size)
    writer.write_at(0, b"data")
    writer.close()

    # .part 文件保留，目标文件不存在
    assert part_path.exists()
    assert not output_path.exists()


def test_global_writer_context_manager(temp_dir):
    """测试 context manager（不自动 finalize）。"""
    output_path = temp_dir / "output.bin"
    part_path = output_path.with_suffix('.bin.part')
    total_size = 10

    with GlobalWriter(output_path, total_size) as writer:
        writer.write_at(0, b"data")
        # 注意：context manager 不自动 finalize

    # 只是 close，.part 文件保留
    assert part_path.exists()
    assert not output_path.exists()


def test_global_writer_context_manager_with_finalize(temp_dir):
    """测试 context manager + 手动 finalize。"""
    output_path = temp_dir / "output.bin"
    total_size = 10

    with GlobalWriter(output_path, total_size) as writer:
        writer.write_at(0, b"data")
        writer.finalize()

    # finalize 后目标文件存在
    assert output_path.exists()


def test_global_writer_preallocation(temp_dir):
    """测试文件预分配。"""
    output_path = temp_dir / "output.bin"
    part_path = output_path.with_suffix('.bin.part')
    total_size = 1024

    writer = GlobalWriter(output_path, total_size)

    # .part 文件应该已经是正确大小
    assert part_path.stat().st_size == total_size

    writer.close()


# ============================================================================
# create_writer 工厂函数测试
# ============================================================================

def test_create_writer_sequential(temp_dir):
    """测试创建 SequentialWriter。"""
    output_path = temp_dir / "output.bin"

    writer = create_writer(output_path, mode='sequential')
    assert isinstance(writer, SequentialWriter)
    writer.close()


def test_create_writer_global(temp_dir):
    """测试创建 GlobalWriter。"""
    output_path = temp_dir / "output.bin"

    writer = create_writer(output_path, mode='global', total_size=100)
    assert isinstance(writer, GlobalWriter)
    writer.close()


def test_create_writer_global_no_size(temp_dir):
    """测试创建 GlobalWriter 但不提供 total_size（应该失败）。"""
    output_path = temp_dir / "output.bin"

    with pytest.raises(ValueError, match="需要提供 total_size"):
        create_writer(output_path, mode='global')


def test_create_writer_invalid_mode(temp_dir):
    """测试不支持的 mode。"""
    output_path = temp_dir / "output.bin"

    with pytest.raises(ValueError, match="不支持的 mode"):
        create_writer(output_path, mode='invalid')


# ============================================================================
# 集成场景测试
# ============================================================================

def test_writer_large_file(temp_dir):
    """测试大文件写入（1 MB）。"""
    output_path = temp_dir / "large.bin"
    total_size = 1024 * 1024  # 1 MB
    chunk_size = 64 * 1024     # 64 KB

    writer = GlobalWriter(output_path, total_size)

    # 写入多个 chunk
    for offset in range(0, total_size, chunk_size):
        size = min(chunk_size, total_size - offset)
        data = bytes([offset % 256]) * size
        writer.write_at(offset, data)

    writer.finalize()

    # 验证文件大小
    assert output_path.stat().st_size == total_size


def test_writer_sparse_write(temp_dir):
    """测试稀疏写入（只写部分区域）。"""
    output_path = temp_dir / "sparse.bin"
    total_size = 1000

    writer = GlobalWriter(output_path, total_size)

    # 只写几个小区域
    writer.write_at(0, b"start")
    writer.write_at(500, b"middle")
    writer.write_at(995, b"end")

    writer.finalize()

    # 验证
    data = output_path.read_bytes()
    assert data[0:5] == b"start"
    assert data[500:506] == b"middle"
    assert data[995:998] == b"end"

    # 未写入的区域应该是 \0
    assert data[100] == 0
