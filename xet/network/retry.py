"""网络请求重试装饰器。

提供指数退避的重试机制，用于处理网络不稳定和临时错误。
"""
from __future__ import annotations

import time
import logging
from typing import Callable, TypeVar, Any, Tuple, Type
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryError(Exception):
    """重试失败后抛出的异常。

    包装了最后一次尝试的原始异常。
    """
    pass


def with_retry(
    max_attempts: int = 5,
    backoff_base: float = 1.5,
    max_backoff: float = 60.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """重试装饰器，支持指数退避。

    对指定的异常类型进行重试，使用指数退避策略。
    退避时间 = min(backoff_base ** (attempt - 1), max_backoff)

    Args:
        max_attempts: 最大尝试次数（包含首次），至少为 1
        backoff_base: 退避基数，通常 1.5 到 2.0
        max_backoff: 最大退避时间（秒），避免等待过久
        retry_on: 要重试的异常类型元组，默认重试所有异常

    Returns:
        装饰器函数

    Raises:
        RetryError: 所有重试都失败后抛出
        ValueError: max_attempts < 1

    Example:
        >>> @with_retry(max_attempts=3, backoff_base=2.0)
        ... def fetch_data(url):
        ...     return requests.get(url).content

        >>> # 自定义重试异常
        >>> @with_retry(retry_on=(requests.RequestException,))
        ... def fetch_json(url):
        ...     return requests.get(url).json()
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts 必须 >= 1, 实际: {max_attempts}")

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except retry_on as e:
                    last_exception = e

                    if attempt == max_attempts:
                        # 最后一次尝试失败，放弃
                        func_name = getattr(func, '__name__', 'unknown')
                        logger.error(
                            f"[Retry] {func_name} 重试 {max_attempts} 次后失败: {e}"
                        )
                        raise RetryError(
                            f"{func_name} 重试 {max_attempts} 次后失败"
                        ) from e

                    # 计算退避时间（指数增长）
                    backoff = min(
                        backoff_base ** (attempt - 1),
                        max_backoff
                    )

                    func_name = getattr(func, '__name__', 'unknown')
                    logger.warning(
                        f"[Retry] {func_name} 第 {attempt}/{max_attempts} 次尝试失败: "
                        f"{type(e).__name__}: {e}, 等待 {backoff:.2f}s 后重试"
                    )

                    time.sleep(backoff)

                except Exception as e:
                    # 不在 retry_on 中的异常，直接抛出
                    func_name = getattr(func, '__name__', 'unknown')
                    logger.debug(
                        f"[Retry] {func_name} 遇到非重试异常 {type(e).__name__}, "
                        f"直接抛出"
                    )
                    raise

            # 理论上不会到这里
            assert last_exception is not None
            raise RetryError("重试逻辑错误") from last_exception

        return wrapper
    return decorator


def calculate_backoff(
    attempt: int,
    backoff_base: float,
    max_backoff: float
) -> float:
    """计算退避时间（纯函数，便于测试）。

    Args:
        attempt: 当前尝试次数（从 1 开始）
        backoff_base: 退避基数
        max_backoff: 最大退避时间

    Returns:
        退避时间（秒）

    Example:
        >>> calculate_backoff(1, 1.5, 60.0)
        1.0
        >>> calculate_backoff(2, 1.5, 60.0)
        1.5
        >>> calculate_backoff(3, 1.5, 60.0)
        2.25
    """
    backoff = backoff_base ** (attempt - 1)
    return min(backoff, max_backoff)


def should_retry(
    exception: Exception,
    retry_on: Tuple[Type[Exception], ...]
) -> bool:
    """判断是否应该重试该异常（纯函数）。

    Args:
        exception: 捕获的异常
        retry_on: 要重试的异常类型元组

    Returns:
        True 表示应该重试

    Example:
        >>> should_retry(ValueError(), (ValueError,))
        True
        >>> should_retry(KeyError(), (ValueError,))
        False
    """
    return isinstance(exception, retry_on)
