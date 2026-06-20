"""XET Network Layer - HTTP 请求和 CAS API 客户端。

提供网络请求的抽象和 CAS 服务访问。
"""

from .retry import (
    with_retry,
    RetryError,
    calculate_backoff,
    should_retry,
)

from .http_utils import (
    create_session,
    fetch_with_range,
    fetch_url,
    download_file,
    post_json,
    get_json,
)

from .auth import XetAuth
from .cas_client import CASClient
from .url_refresh_coordinator import URLRefreshCoordinator
from .adaptive_concurrency import AdaptiveConcurrencyController
from .low_speed_timeout import LowSpeedTimeoutError

__all__ = [
    # Retry
    'with_retry',
    'RetryError',
    'calculate_backoff',
    'should_retry',

    # HTTP Utils
    'create_session',
    'fetch_with_range',
    'fetch_url',
    'download_file',
    'post_json',
    'get_json',

    # Auth & CAS
    'XetAuth',
    'CASClient',

    # Advanced Features
    'URLRefreshCoordinator',
    'AdaptiveConcurrencyController',
    'LowSpeedTimeoutError',
]
