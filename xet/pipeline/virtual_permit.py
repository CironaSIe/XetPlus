"""虚拟许可机制 - 避免下载启动时的 FIFO 等待。

实现类似 Rust 版本的 Seed Permit 机制，下载启动时临时增加信号量许可，
避免等待 FIFO 队列，减少启动延迟。
"""
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class VirtualPermit:
    """可分割的虚拟许可。

    虚拟许可类似于信号量许可，但不需要实际从信号量获取，
    可以自由分割和释放。

    使用场景：
    - 下载启动时获取一个虚拟许可（不等待）
    - 从虚拟许可分割出实际需要的大小
    - 用完后归还给信号量

    Attributes:
        _semaphore: 关联的信号量
        _remaining: 剩余许可大小（字节）
    """

    def __init__(self, semaphore: threading.Semaphore, size: int):
        """初始化虚拟许可。

        Args:
            semaphore: 关联的信号量（用于最终释放）
            size: 许可大小（字节）
        """
        if size <= 0:
            raise ValueError(f"虚拟许可大小必须 > 0: {size}")

        self._semaphore = semaphore
        self._remaining = size
        self._used = 0
        self._lock = threading.Lock()

        logger.debug(f"[VirtualPermit] 创建: size={size / 1024 / 1024:.2f}MB")

    def split(self, size: int) -> Optional['VirtualPermit']:
        """分割出指定大小的许可（不等待）。

        Args:
            size: 要分割的大小（字节）

        Returns:
            新的虚拟许可，如果剩余不足返回 None
        """
        with self._lock:
            if size <= self._remaining:
                self._remaining -= size
                self._used += size
                # 返回新的虚拟许可
                return VirtualPermit(self._semaphore, size)
            else:
                return None

    def release(self) -> None:
        """释放虚拟许可（归还给信号量）。"""
        with self._lock:
            if self._remaining > 0:
                # 将剩余部分归还给信号量
                # 注意：threading.Semaphore 的 release() 增加计数
                self._semaphore.release()
                logger.debug(
                    f"[VirtualPermit] 释放: remaining={self._remaining / 1024 / 1024:.2f}MB"
                )
                self._remaining = 0

    def remaining(self) -> int:
        """获取剩余许可大小。

        Returns:
            剩余字节数
        """
        with self._lock:
            return self._remaining

    def __enter__(self):
        """上下文管理器入口。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出（自动释放）。"""
        self.release()

    def __repr__(self) -> str:
        """字符串表示。"""
        return (
            f"VirtualPermit("
            f"remaining={self._remaining / 1024 / 1024:.2f}MB, "
            f"used={self._used / 1024 / 1024:.2f}MB)"
        )


class DynamicSemaphore:
    """动态信号量 - 支持临时增加许可。

    扩展标准信号量，支持临时增加许可数量（虚拟许可），
    避免下载启动时的 FIFO 等待。

    Attributes:
        _base_value: 基础许可数量
        _current_value: 当前许可数量
        _semaphore: 底层信号量
    """

    def __init__(self, value: int):
        """初始化动态信号量。

        Args:
            value: 初始许可数量
        """
        if value <= 0:
            raise ValueError(f"信号量初始值必须 > 0: {value}")

        self._base_value = value
        self._current_value = value
        self._semaphore = threading.Semaphore(value)
        self._lock = threading.Lock()

        logger.debug(f"[DynamicSemaphore] 初始化: base={value}")

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """获取许可（标准信号量接口）。

        Args:
            blocking: 是否阻塞等待
            timeout: 超时时间（秒）

        Returns:
            是否成功获取
        """
        return self._semaphore.acquire(blocking=blocking, timeout=timeout)

    def release(self) -> None:
        """释放许可（标准信号量接口）。"""
        with self._lock:
            self._semaphore.release()
            self._current_value += 1

    def increment_to_target(self, target: int) -> VirtualPermit:
        """临时增加许可到目标值，返回虚拟许可。

        Args:
            target: 目标许可数量

        Returns:
            虚拟许可（代表临时增加的部分）
        """
        with self._lock:
            if target <= self._current_value:
                # 已经达到目标，返回空虚拟许可
                return VirtualPermit(self._semaphore, 0)

            delta = target - self._current_value
            # 临时增加信号量计数
            for _ in range(delta):
                self._semaphore.release()

            self._current_value = target

            logger.debug(
                f"[DynamicSemaphore] 临时增加: "
                f"{self._current_value - delta} -> {target} (+{delta})"
            )

            # 返回虚拟许可（用于后续释放）
            return VirtualPermit(self._semaphore, delta)

    def get_current_value(self) -> int:
        """获取当前许可数量（近似值）。

        Returns:
            当前许可数量
        """
        with self._lock:
            return self._current_value

    def __repr__(self) -> str:
        """字符串表示。"""
        return (
            f"DynamicSemaphore("
            f"base={self._base_value}, "
            f"current={self._current_value})"
        )
