"""GlobalWriter - 并行批量写入器。

支持多线程安全的批量文件写入，减少系统调用和 fsync 开销。

参考实现：
- xet.py: StreamFileReconstructor._writer_parallel()
- Rust: SequentialWriter.run_vectorized()

设计要点：
1. 单独 writer 线程消费写队列
2. 批量获取 (offset, data) 元组
3. 按 offset 排序后批量 seek + write
4. 统一 fsync 减少磁盘同步开销
5. Windows 兼容：CreateFileW + FILE_SHARE_WRITE
"""
import os
import queue
import threading
import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class GlobalWriter:
    """并行批量写入器 - 支持多段并行写入同一文件。

    特点：
    - 单独 writer 线程，避免主线程阻塞
    - 批量写入，减少系统调用次数
    - 统一 fsync，减少磁盘同步开销
    - Windows 兼容：支持多线程共享文件句柄

    使用方式：
    ```python
    writer = GlobalWriter(output_path, batch_size=8)
    writer.start()

    # 主线程提交写入请求
    for offset, data in write_items:
        writer.put(offset, data)

    # 完成写入
    total_bytes = writer.finish()
    ```

    Attributes:
        output_path: 输出文件路径
        batch_size: 批量写入大小（默认 8）
        progress_callback: 进度回调函数
        stop_event: 停止信号
    """

    def __init__(
        self,
        output_path: Path,
        batch_size: int = 8,
        progress_callback: Optional[Callable[[int], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        """初始化 GlobalWriter。

        Args:
            output_path: 输出文件路径
            batch_size: 批量写入大小（默认 8，建议等于并发数）
            progress_callback: 进度回调函数，参数为已写入字节数
            stop_event: 停止信号
        """
        self.output_path = output_path
        self.batch_size = batch_size
        self.progress_callback = progress_callback
        self.stop_event = stop_event or threading.Event()

        # 写队列：(offset, data) 元组
        # maxsize = batch_size * 2 避免过度缓冲
        self._write_queue = queue.Queue(maxsize=batch_size * 2)

        # Writer 线程
        self._writer_thread = None
        self._writer_exception = None
        self._bytes_written = 0
        self._started = False

    def start(self):
        """启动 writer 线程。"""
        if self._started:
            raise RuntimeError("GlobalWriter 已启动")

        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="GlobalWriter",
            daemon=True,
        )
        self._writer_thread.start()
        self._started = True

        logger.debug(f"[GlobalWriter] 线程已启动: {self.output_path}")

    def put(self, offset: int, data: bytes, timeout: float = 10.0):
        """放入写队列（阻塞）。

        Args:
            offset: 文件偏移量（字节）
            data: 数据内容
            timeout: 超时时间（秒）

        Raises:
            RuntimeError: writer 线程异常
            queue.Full: 队列已满（超时）
        """
        # 检查 writer 线程是否异常
        if self._writer_exception is not None:
            raise RuntimeError(f"GlobalWriter 线程异常: {self._writer_exception}")

        try:
            self._write_queue.put((offset, data), timeout=timeout)
        except queue.Full:
            raise queue.Full(
                f"GlobalWriter 写队列已满（超时 {timeout}s），"
                f"可能 writer 线程阻塞或处理速度过慢"
            )

    def finish(self, timeout: float = 60.0) -> int:
        """完成写入，等待线程结束。

        Args:
            timeout: 等待超时（秒）

        Returns:
            已写入字节数

        Raises:
            RuntimeError: writer 线程异常
            TimeoutError: 等待超时
        """
        if not self._started:
            raise RuntimeError("GlobalWriter 未启动")

        # 发送结束标志
        self._write_queue.put(None)

        # 等待线程结束
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=timeout)
            if self._writer_thread.is_alive():
                raise TimeoutError(f"GlobalWriter 线程等待超时: {timeout}s")

        # 检查异常
        if self._writer_exception is not None:
            raise RuntimeError(f"GlobalWriter 线程异常: {self._writer_exception}")

        logger.info(
            f"[GlobalWriter] 写入完成: {self.output_path.name}, "
            f"{self._bytes_written / 1024 / 1024:.2f} MB"
        )

        return self._bytes_written

    def _open_file_shared_write(self, path: str):
        """以允许并发读写的模式打开文件（Windows 兼容）。

        Windows 特殊处理：
        - 标准 open('r+b') 获取独占锁，多线程写入会阻塞
        - 使用 CreateFileW + FILE_SHARE_WRITE 允许多线程共享文件句柄

        Linux/macOS：
        - 标准 open() 默认允许多进程/线程共享读写

        参考：xet.py/xet/reconstructor.py:_open_file_shared_write()

        Args:
            path: 文件路径

        Returns:
            文件对象（无缓冲）

        Raises:
            OSError: 文件打开失败
        """
        if os.name == 'nt':
            import ctypes
            import msvcrt

            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_ALWAYS = 4
            INVALID_HANDLE_VALUE = -1

            # 使用 CreateFileW（宽字符版本，支持中文路径）
            handle = ctypes.windll.kernel32.CreateFileW(
                path,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,  # 🔑 关键：允许其他线程读写
                None,            # 安全属性
                OPEN_ALWAYS,     # 文件不存在时创建
                0,               # 无特殊属性
                None,            # 无模板文件
            )

            if handle == INVALID_HANDLE_VALUE or (handle & 0xFFFFFFFF) == 0xFFFFFFFF:
                error = ctypes.GetLastError()
                raise OSError(
                    f"[GlobalWriter] CreateFileW 打开失败 "
                    f"(error={error}): {path}"
                )

            # 将 Windows HANDLE 转为 C runtime fd，再包装为 Python file object
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR)
            return open(fd, 'r+b', buffering=0)  # 无缓冲
        else:
            # Linux/macOS: 如果文件不存在，先创建
            # 使用 'w+b' 模式创建，然后关闭重新以 'r+b' 打开（确保文件存在）
            if not os.path.exists(path):
                # 创建空文件
                open(path, 'wb').close()

            return open(path, 'r+b', buffering=0)

    def _writer_loop(self):
        """Writer 线程主循环（批量写入模式）。

        流程：
        1. 从队列获取 (offset, data) 元组
        2. 累积到 batch
        3. 达到 batch_size 后，批量写入
        4. 按 offset 排序，确保顺序写入
        5. 统一 fsync，减少磁盘同步开销
        """
        try:
            batch = []

            with self._open_file_shared_write(str(self.output_path)) as f:
                while True:
                    try:
                        # 阻塞等待（最多 30 秒）
                        item = self._write_queue.get(timeout=30)

                        # 结束标志
                        if item is None:
                            # 写入剩余 batch
                            if batch:
                                self._flush_batch(f, batch)
                            break

                        batch.append(item)

                        # 达到 batch_size，批量写入
                        if len(batch) >= self.batch_size:
                            self._flush_batch(f, batch)
                            batch = []

                    except queue.Empty:
                        # 超时但非停止信号，继续等待
                        if self.stop_event.is_set():
                            logger.warning("[GlobalWriter] 检测到停止信号，提前退出")
                            # 写入剩余 batch
                            if batch:
                                self._flush_batch(f, batch)
                            break
                        continue

            logger.debug(f"[GlobalWriter] 线程正常退出")

        except Exception as e:
            logger.error(f"[GlobalWriter] 线程异常: {e}", exc_info=True)
            self._writer_exception = e

    def _flush_batch(self, f, batch):
        """批量写入一批数据。

        Args:
            f: 文件对象
            batch: [(offset, data), ...] 列表
        """
        if not batch:
            return

        # 按 offset 排序（确保顺序写入，减少磁盘寻道）
        batch.sort(key=lambda x: x[0])

        # 批量 seek + write
        for offset, data in batch:
            f.seek(offset)
            f.write(data)

        # 统一 fsync（确保数据落盘）
        f.flush()
        os.fsync(f.fileno())

        # 更新进度
        total = sum(len(d) for _, d in batch)
        self._bytes_written += total

        if self.progress_callback:
            self.progress_callback(total)

        logger.debug(
            f"[GlobalWriter] 批量写入: {len(batch)} items, "
            f"{total / 1024 / 1024:.2f} MB, "
            f"total: {self._bytes_written / 1024 / 1024:.2f} MB"
        )
