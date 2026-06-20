"""文件写入接口和实现。

提供统一的文件写入抽象，支持不同的写入策略：
- SequentialWriter: 顺序写入（HDD 友好）
- GlobalWriter: 随机写入（并行下载）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class FileWriter(ABC):
    """文件写入抽象接口。

    所有 Writer 实现都必须支持 context manager 协议。

    Example:
        >>> with SequentialWriter(Path("output.bin")) as writer:
        ...     writer.write_at(0, b"hello")
        ...     writer.write_at(5, b"world")
    """

    def __init__(self, path: Path):
        """初始化 Writer。

        Args:
            path: 目标文件路径
        """
        self.path = path
        self._closed = False

    @abstractmethod
    def write_at(self, offset: int, data: bytes) -> None:
        """在指定偏移处写入数据。

        Args:
            offset: 字节偏移（从 0 开始）
            data: 要写入的数据

        Raises:
            ValueError: 偏移或数据无效
            IOError: 写入失败
        """
        pass

    @abstractmethod
    def flush(self) -> None:
        """刷新缓冲区到磁盘。

        确保所有已写入的数据持久化到存储。
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭文件句柄。

        释放所有资源。调用后不能再进行写入操作。
        """
        pass

    def __enter__(self) -> FileWriter:
        """进入 context manager。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出 context manager，自动关闭文件。"""
        if not self._closed:
            self.close()


class SequentialWriter(FileWriter):
    """顺序写入器。

    只支持按偏移顺序写入，适合：
    - 下载顺序与文件偏移顺序一致的场景
    - HDD 存储（减少磁头移动）
    - 流式写入

    限制：
    - write_at() 的 offset 必须严格递增
    - 不支持随机访问
    - 不支持覆盖已写入的数据

    Example:
        >>> writer = SequentialWriter(Path("output.bin"))
        >>> writer.write_at(0, b"chunk1")    # OK
        >>> writer.write_at(6, b"chunk2")    # OK
        >>> writer.write_at(3, b"xxx")       # ERROR: 偏移回退
    """

    def __init__(self, path: Path):
        """初始化顺序写入器。

        Args:
            path: 目标文件路径
        """
        super().__init__(path)
        self._fp: Optional[object] = None
        self._current_offset = 0

    def write_at(self, offset: int, data: bytes) -> None:
        """顺序写入数据。

        Args:
            offset: 必须等于当前偏移
            data: 要写入的数据

        Raises:
            ValueError: offset 不等于当前偏移
            RuntimeError: Writer 已关闭
        """
        if self._closed:
            raise RuntimeError("Writer 已关闭")

        if offset != self._current_offset:
            raise ValueError(
                f"SequentialWriter 只支持顺序写入: "
                f"期望 offset={self._current_offset}, 实际 {offset}"
            )

        # 延迟打开文件（首次写入时）
        if self._fp is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fp = open(self.path, 'wb')

        self._fp.write(data)
        self._current_offset += len(data)

    def flush(self) -> None:
        """刷新缓冲区。"""
        if self._fp is not None:
            self._fp.flush()

    def close(self) -> None:
        """关闭文件。"""
        if self._closed:
            return

        if self._fp is not None:
            self._fp.close()
            self._fp = None

        self._closed = True


class GlobalWriter(FileWriter):
    """全局写入器（支持随机访问）。

    支持任意偏移写入，适合：
    - 并行下载多个片段
    - SSD 存储
    - 需要断点续传

    特性：
    - 预分配文件大小（减少碎片）
    - 使用 .part 临时文件（Windows 兼容）
    - 完成后原子重命名

    工作流程：
    1. 创建 {path}.part 文件并预分配大小
    2. 随机写入各个偏移的数据
    3. 调用 finalize() 重命名为目标文件

    Example:
        >>> writer = GlobalWriter(Path("output.bin"), total_size=1000)
        >>> writer.write_at(500, b"middle")  # 先写中间
        >>> writer.write_at(0, b"start")     # 再写开头
        >>> writer.finalize()                # 完成
    """

    def __init__(self, path: Path, total_size: int):
        """初始化全局写入器。

        Args:
            path: 目标文件路径
            total_size: 文件总大小（字节）

        Raises:
            ValueError: total_size <= 0
        """
        super().__init__(path)

        if total_size <= 0:
            raise ValueError(f"total_size 必须 > 0, 实际: {total_size}")

        self.total_size = total_size
        self.part_path = path.with_suffix(path.suffix + '.part')
        self._fp: Optional[object] = None
        self._finalized = False

        self._init_file()

    def _init_file(self) -> None:
        """初始化临时文件并预分配大小。"""
        # 确保目录存在
        self.part_path.parent.mkdir(parents=True, exist_ok=True)

        # 创建并预分配大小
        with open(self.part_path, 'wb') as f:
            # 使用 seek + write 预分配（跨平台兼容）
            f.seek(self.total_size - 1)
            f.write(b'\0')

        # 以读写模式打开
        self._fp = open(self.part_path, 'r+b')

    def write_at(self, offset: int, data: bytes) -> None:
        """在指定偏移写入数据。

        Args:
            offset: 字节偏移
            data: 要写入的数据

        Raises:
            ValueError: 写入越界
            RuntimeError: Writer 已关闭或已 finalize
        """
        if self._finalized:
            raise RuntimeError("Writer 已 finalize，不能再写入")

        if self._closed:
            raise RuntimeError("Writer 已关闭")

        if offset < 0:
            raise ValueError(f"offset 不能为负数: {offset}")

        if offset + len(data) > self.total_size:
            raise ValueError(
                f"写入越界: offset={offset}, len={len(data)}, "
                f"total_size={self.total_size}"
            )

        self._fp.seek(offset)
        written = self._fp.write(data)

        # 确保全部写入
        if written != len(data):
            raise IOError(
                f"写入不完整: 期望 {len(data)} bytes, 实际 {written} bytes"
            )

    def flush(self) -> None:
        """刷新缓冲区。"""
        if self._fp is not None:
            self._fp.flush()

    def close(self) -> None:
        """关闭文件（不执行 finalize）。

        注意：如果想保留 .part 文件，请调用此方法。
        如果想完成下载并重命名，请调用 finalize()。
        """
        if self._closed:
            return

        if self._fp is not None:
            self._fp.close()
            self._fp = None

        self._closed = True

    def finalize(self) -> None:
        """完成写入并重命名为目标文件。

        这是原子操作（在同一文件系统内）。

        Raises:
            RuntimeError: 已经 finalize 过
        """
        if self._finalized:
            raise RuntimeError("已经 finalize 过")

        # 关闭文件
        if not self._closed:
            self.close()

        # 原子重命名
        self.part_path.rename(self.path)
        self._finalized = True


def create_writer(
    path: Path,
    mode: str = 'sequential',
    total_size: Optional[int] = None
) -> FileWriter:
    """工厂函数：创建 Writer 实例。

    Args:
        path: 目标文件路径
        mode: 写入模式 ('sequential' 或 'global')
        total_size: 文件总大小（mode='global' 时必需）

    Returns:
        FileWriter 实例

    Raises:
        ValueError: 参数无效

    Example:
        >>> writer = create_writer(Path("output.bin"), mode='sequential')
        >>> # 或
        >>> writer = create_writer(Path("output.bin"), mode='global', total_size=1024)
    """
    if mode == 'sequential':
        return SequentialWriter(path)
    elif mode == 'global':
        if total_size is None:
            raise ValueError("mode='global' 需要提供 total_size 参数")
        return GlobalWriter(path, total_size)
    else:
        raise ValueError(f"不支持的 mode: {mode}")
