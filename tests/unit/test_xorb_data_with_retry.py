"""network.cas_client.get_xorb_data_with_retry 高级重试逻辑测试。"""
import pytest
import time
from unittest.mock import Mock, patch, call
import requests

from xet.network.cas_client import CASClient
from xet.network.auth import XetAuth
from xet.network.url_refresh_coordinator import URLRefreshCoordinator
from xet.network.adaptive_concurrency import AdaptiveConcurrencyController
from xet.network.low_speed_timeout import LowSpeedTimeoutError
from xet.protocol.types import HttpRange, QueryReconstructionResponse


@pytest.fixture
def mock_session():
    """创建 Mock session。"""
    session = Mock(spec=requests.Session)
    session.timeout = (10, 300)
    return session


@pytest.fixture
def mock_auth():
    """创建 Mock auth。"""
    auth = Mock(spec=XetAuth)
    return auth


@pytest.fixture
def mock_coordinator():
    """创建 Mock URLRefreshCoordinator。"""
    coordinator = Mock(spec=URLRefreshCoordinator)
    coordinator.is_exhausted = False
    coordinator.acquire_refresh.return_value = True
    return coordinator


@pytest.fixture
def mock_acc():
    """创建 Mock AdaptiveConcurrencyController。"""
    acc = Mock(spec=AdaptiveConcurrencyController)
    acc.acquire.return_value = True
    return acc


# ============================================================================
# get_xorb_data_with_retry 基本功能测试
# ============================================================================

def test_retry_success_without_acc(mock_session):
    """测试基本下载成功（无 ACC）。"""
    mock_response = Mock()
    mock_response.content = b"xorb_data"
    mock_response.raise_for_status.return_value = None
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=1023)
    xorb_hash = "abc123" * 10 + "abcd"
    file_hash = "def456" * 10 + "efgh"

    data = client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)

    assert data == b"xorb_data"
    mock_session.get.assert_called_once()


def test_retry_success_with_acc(mock_session, mock_acc):
    """测试下载成功并报告给 ACC。"""
    mock_response = Mock()
    mock_response.content = b"xorb_data"
    mock_response.raise_for_status.return_value = None
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        acc=mock_acc
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=1023)
    xorb_hash = "abc123" * 10 + "abcd"
    file_hash = "def456" * 10 + "efgh"

    data = client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)

    assert data == b"xorb_data"
    mock_acc.acquire.assert_called_once()
    mock_acc.release.assert_called_once()
    mock_acc.report_success.assert_called_once()


def test_retry_acc_timeout(mock_session, mock_acc):
    """测试 ACC acquire 超时。"""
    mock_acc.acquire.return_value = False

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        acc=mock_acc
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=1023)
    xorb_hash = "abc123" * 10 + "abcd"
    file_hash = "def456" * 10 + "efgh"

    with pytest.raises(RuntimeError, match="AdaptiveConcurrencyController acquire 超时"):
        client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)


# ============================================================================
# 401 处理测试
# ============================================================================

def test_retry_401_refresh_token(mock_session, mock_auth):
    """测试 401 自动刷新 token 并重新获取 reconstruction。"""
    # Mock token cache
    mock_auth._token_cache = None

    # Mock token 刷新
    from xet.protocol.types import XetTokenInfo
    mock_auth.get_token.return_value = XetTokenInfo(
        access_token="new_token",
        endpoint="https://cas.example.com",
        expiration=int(time.time()) + 3600
    )

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="old_token",
        session=mock_session,
        auth=mock_auth,
        repo_id="user/repo",
        retry_max=3
    )

    # Mock get_reconstruction 和 _find_xorb_in_recon，同时禁用装饰器重试
    mock_response_401 = Mock()
    mock_response_401.status_code = 401

    with patch.object(client, 'get_reconstruction') as mock_get_recon, \
         patch.object(client, '_find_xorb_in_recon') as mock_find_xorb, \
         patch.object(client, 'get_xorb_data') as mock_get_xorb:

        mock_recon = Mock(spec=QueryReconstructionResponse)
        mock_get_recon.return_value = mock_recon
        new_url = "https://cdn.example.com/xorb_new"
        new_range = HttpRange(start=0, end=1023)
        mock_find_xorb.return_value = (new_url, new_range)

        # 第一次调用抛出 401，第二次成功
        mock_get_xorb.side_effect = [
            requests.HTTPError("401", response=mock_response_401),
            b"xorb_data_after_refresh"
        ]

        url = "https://cdn.example.com/xorb"
        url_range = HttpRange(start=0, end=1023)
        xorb_hash = "abc123" * 10 + "abcd"
        file_hash = "def456" * 10 + "efgh"

        data = client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)

        assert data == b"xorb_data_after_refresh"
        mock_auth.clear_cache.assert_called_once()
        mock_get_recon.assert_called_once_with(file_hash)
        mock_find_xorb.assert_called_once()


# ============================================================================
# 403 处理测试
# ============================================================================

def test_retry_403_with_coordinator(mock_session, mock_auth, mock_coordinator):
    """测试 403 通过 URLRefreshCoordinator 协调刷新。"""
    # Mock token cache
    mock_auth._token_cache = None

    # Mock token 刷新
    from xet.protocol.types import XetTokenInfo
    mock_auth.get_token.return_value = XetTokenInfo(
        access_token="new_token",
        endpoint="https://cas.example.com",
        expiration=int(time.time()) + 3600
    )

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=mock_auth,
        repo_id="user/repo",
        url_coordinator=mock_coordinator,
        retry_max=3
    )

    # Mock get_reconstruction, _find_xorb_in_recon, get_xorb_data 和 _interruptible_sleep
    mock_response_403 = Mock()
    mock_response_403.status_code = 403

    with patch.object(client, 'get_reconstruction') as mock_get_recon, \
         patch.object(client, '_find_xorb_in_recon') as mock_find_xorb, \
         patch.object(client, 'get_xorb_data') as mock_get_xorb, \
         patch.object(client, '_interruptible_sleep'):

        mock_recon = Mock(spec=QueryReconstructionResponse)
        mock_get_recon.return_value = mock_recon
        new_url = "https://cdn.example.com/xorb_new"
        new_range = HttpRange(start=0, end=1023)
        mock_find_xorb.return_value = (new_url, new_range)

        # 第一次调用抛出 403，第二次成功
        mock_get_xorb.side_effect = [
            requests.HTTPError("403", response=mock_response_403),
            b"xorb_data_after_403"
        ]

        url = "https://cdn.example.com/xorb"
        url_range = HttpRange(start=0, end=1023)
        xorb_hash = "abc123" * 10 + "abcd"
        file_hash = "def456" * 10 + "efgh"

        data = client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)

        assert data == b"xorb_data_after_403"
        mock_coordinator.acquire_refresh.assert_called_once()
        mock_coordinator.release_refresh.assert_called_once_with(success=True)


def test_retry_403_coordinator_exhausted(mock_session, mock_coordinator):
    """测试 403 时 coordinator exhausted 直接放弃。"""
    mock_coordinator.is_exhausted = True

    mock_response_403 = Mock()
    mock_response_403.status_code = 403

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        url_coordinator=mock_coordinator
    )

    # Mock get_xorb_data 抛出 403
    with patch.object(client, 'get_xorb_data') as mock_get_xorb:
        mock_get_xorb.side_effect = requests.HTTPError("403", response=mock_response_403)

        url = "https://cdn.example.com/xorb"
        url_range = HttpRange(start=0, end=1023)
        xorb_hash = "abc123" * 10 + "abcd"
        file_hash = "def456" * 10 + "efgh"

        with pytest.raises(RuntimeError, match="URL 刷新失败次数过多"):
            client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)


# ============================================================================
# 断点续传测试
# ============================================================================

def test_retry_low_speed_timeout_resume(mock_session):
    """测试低速超时后断点续传。"""
    # 第一次：低速超时
    def mock_streaming_first(*args, **kwargs):
        raise LowSpeedTimeoutError("持续低速", received=10240)

    # 第二次：成功
    def mock_streaming_second(*args, **kwargs):
        return b"remaining_data"

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    with patch.object(client, 'get_xorb_data_streaming', side_effect=[
        LowSpeedTimeoutError("持续低速", received=10240),
        b"remaining_data"
    ]):
        url = "https://cdn.example.com/xorb"
        url_range = HttpRange(start=0, end=102399)
        xorb_hash = "abc123" * 10 + "abcd"
        file_hash = "def456" * 10 + "efgh"

        data = client.get_xorb_data_with_retry(
            url, url_range, xorb_hash, file_hash, use_streaming=True
        )

        assert data == b"remaining_data"


# ============================================================================
# 重试耗尽测试
# ============================================================================

def test_retry_exhausted(mock_session):
    """测试重试次数耗尽。"""
    mock_response = Mock()
    mock_response.status_code = 500

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        retry_max=3
    )

    with patch.object(client, '_interruptible_sleep'), \
         patch.object(client, 'get_xorb_data') as mock_get_xorb:

        # 每次都抛出 500 错误
        def raise_http_error(*args, **kwargs):
            raise requests.HTTPError("500", response=mock_response)

        mock_get_xorb.side_effect = raise_http_error

        url = "https://cdn.example.com/xorb"
        url_range = HttpRange(start=0, end=1023)
        xorb_hash = "abc123" * 10 + "abcd"
        file_hash = "def456" * 10 + "efgh"

        # 应该最终抛出 RuntimeError（重试耗尽）
        with pytest.raises((RuntimeError, requests.HTTPError)):
            client.get_xorb_data_with_retry(url, url_range, xorb_hash, file_hash)

        # 验证重试了 3 次
        assert mock_get_xorb.call_count == 3
