"""network.cas_client 辅助方法测试。"""
import pytest
import time
import threading
from unittest.mock import Mock, patch
import requests

from xet.network.cas_client import CASClient
from xet.network.auth import XetAuth
from xet.protocol.types import (
    HttpRange,
    QueryReconstructionResponse,
    CASReconstructionFetchInfo,
    CASReconstructionTerm,
    ChunkRange,
)


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


# ============================================================================
# _ensure_token 测试
# ============================================================================

def test_ensure_token_no_auth(mock_session):
    """测试无 auth 时不执行检查。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=None
    )

    # 不应抛出异常
    client._ensure_token()


def test_ensure_token_no_cache(mock_session, mock_auth):
    """测试无缓存时不刷新。"""
    mock_auth._token_cache = None

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=mock_auth
    )

    client._ensure_token()

    # 不应调用刷新
    assert mock_auth.clear_cache.call_count == 0


def test_ensure_token_not_expiring(mock_session, mock_auth):
    """测试 token 未到期不刷新。"""
    from xet.protocol.types import XetTokenInfo

    # Token 1 小时后过期
    mock_auth._token_cache = XetTokenInfo(
        access_token="test_token",
        endpoint="https://cas.example.com",
        expiration=int(time.time()) + 3600
    )

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=mock_auth
    )

    client._ensure_token()

    # 不应调用刷新（距离过期还有 > 10 分钟）
    assert mock_auth.clear_cache.call_count == 0


def test_ensure_token_expiring_soon(mock_session, mock_auth):
    """测试 token 即将过期时主动刷新。"""
    from xet.protocol.types import XetTokenInfo

    # Token 5 分钟后过期（< 10 分钟缓冲）
    mock_auth._token_cache = XetTokenInfo(
        access_token="old_token",
        endpoint="https://cas.example.com",
        expiration=int(time.time()) + 300
    )

    # Mock 刷新后的新 token
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
        repo_id="user/repo"
    )

    client._ensure_token()

    # 应该调用刷新
    mock_auth.clear_cache.assert_called_once()
    mock_auth.get_token.assert_called_once()
    assert client.access_token == "new_token"


# ============================================================================
# _force_refresh_token 测试
# ============================================================================

def test_force_refresh_token_no_auth(mock_session):
    """测试无 auth 时抛出异常。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=None
    )

    with pytest.raises(RuntimeError, match="未配置 XetAuth"):
        client._force_refresh_token()


def test_force_refresh_token_success(mock_session, mock_auth):
    """测试强制刷新成功。"""
    from xet.protocol.types import XetTokenInfo

    mock_auth.get_token.return_value = XetTokenInfo(
        access_token="refreshed_token",
        endpoint="https://cas.example.com",
        expiration=int(time.time()) + 3600
    )

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="old_token",
        session=mock_session,
        auth=mock_auth,
        repo_id="user/repo"
    )

    client._force_refresh_token()

    assert client.access_token == "refreshed_token"
    mock_auth.clear_cache.assert_called_once()
    mock_auth.get_token.assert_called_once()


def test_force_refresh_token_retry(mock_session, mock_auth):
    """测试刷新失败后重试。"""
    from xet.protocol.types import XetTokenInfo

    # 前 2 次失败，第 3 次成功
    mock_auth.get_token.side_effect = [
        RuntimeError("Network error"),
        RuntimeError("Network error"),
        XetTokenInfo(
            access_token="refreshed_token",
            endpoint="https://cas.example.com",
            expiration=int(time.time()) + 3600
        )
    ]

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="old_token",
        session=mock_session,
        auth=mock_auth,
        repo_id="user/repo"
    )

    with patch.object(client, '_interruptible_sleep'):
        client._force_refresh_token(max_retries=3)

    assert client.access_token == "refreshed_token"
    assert mock_auth.get_token.call_count == 3


def test_force_refresh_token_exhausted(mock_session, mock_auth):
    """测试重试耗尽。"""
    mock_auth.get_token.side_effect = RuntimeError("Persistent error")

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="old_token",
        session=mock_session,
        auth=mock_auth,
        repo_id="user/repo"
    )

    with patch.object(client, '_interruptible_sleep'):
        with pytest.raises(RuntimeError, match="Token 刷新失败"):
            client._force_refresh_token(max_retries=2)


# ============================================================================
# _interruptible_sleep 测试
# ============================================================================

def test_interruptible_sleep_no_stop_event(mock_session):
    """测试无 stop_event 时正常睡眠。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        stop_event=None
    )

    start = time.time()
    client._interruptible_sleep(0.2)
    elapsed = time.time() - start

    assert elapsed >= 0.2


def test_interruptible_sleep_interrupted():
    """测试 stop_event 触发中断。"""
    stop_event = threading.Event()
    mock_session = Mock(spec=requests.Session)

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        stop_event=stop_event
    )

    # 在另一个线程中触发 stop_event
    def trigger_stop():
        time.sleep(0.1)
        stop_event.set()

    t = threading.Thread(target=trigger_stop)
    t.start()

    start = time.time()
    with pytest.raises(KeyboardInterrupt):
        client._interruptible_sleep(5.0)  # 请求睡眠 5s，但应在 0.1s 后中断
    elapsed = time.time() - start

    assert elapsed < 1.0  # 远小于 5s
    t.join()


# ============================================================================
# _check_interrupt 测试
# ============================================================================

def test_check_interrupt_no_stop_event(mock_session):
    """测试无 stop_event 时不中断。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        stop_event=None
    )

    # 不应抛出异常
    client._check_interrupt()


def test_check_interrupt_triggered():
    """测试 stop_event 触发时抛出异常。"""
    stop_event = threading.Event()
    stop_event.set()
    mock_session = Mock(spec=requests.Session)

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        stop_event=stop_event
    )

    with pytest.raises(KeyboardInterrupt, match="用户中断"):
        client._check_interrupt()


# ============================================================================
# _find_xorb_in_recon 测试
# ============================================================================

def test_find_xorb_in_recon_simple(mock_session):
    """测试在 reconstruction 中查找 xorb（单个 fetch_info）。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    xorb_hash = "abc123" * 10 + "abcd"
    fetch_info = CASReconstructionFetchInfo(
        url="https://cdn.example.com/xorb",
        url_range=HttpRange(start=0, end=1023),
        chunk_range=ChunkRange(start=0, end=10)
    )
    recon = QueryReconstructionResponse(
        offset_into_first_range=0,
        terms=[],
        fetch_info={xorb_hash: [fetch_info]}
    )

    url, url_range = client._find_xorb_in_recon(xorb_hash, recon)

    assert url == "https://cdn.example.com/xorb"
    assert url_range.start == 0
    assert url_range.end == 1023


def test_find_xorb_in_recon_not_found(mock_session):
    """测试找不到 xorb 时抛出异常。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    xorb_hash = "missing_hash" * 5 + "1234"
    recon = QueryReconstructionResponse(
        offset_into_first_range=0,
        terms=[],
        fetch_info={}
    )

    with pytest.raises(ValueError, match="找不到 xorb"):
        client._find_xorb_in_recon(xorb_hash, recon)


def test_find_xorb_in_recon_empty_fetch_info(mock_session):
    """测试 fetch_info 为空时抛出异常。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    xorb_hash = "abc123" * 10 + "abcd"
    recon = QueryReconstructionResponse(
        offset_into_first_range=0,
        terms=[],
        fetch_info={xorb_hash: []}  # 空列表
    )

    with pytest.raises(ValueError, match="fetch_info 为空"):
        client._find_xorb_in_recon(xorb_hash, recon)


def test_find_xorb_in_recon_with_range_match(mock_session):
    """测试使用 url_range 精确匹配。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    xorb_hash = "abc123" * 10 + "abcd"
    fetch_info1 = CASReconstructionFetchInfo(
        url="https://cdn.example.com/xorb1",
        url_range=HttpRange(start=0, end=1023),
        chunk_range=ChunkRange(start=0, end=10)
    )
    fetch_info2 = CASReconstructionFetchInfo(
        url="https://cdn.example.com/xorb2",
        url_range=HttpRange(start=1024, end=2047),
        chunk_range=ChunkRange(start=10, end=20)
    )
    recon = QueryReconstructionResponse(
        offset_into_first_range=0,
        terms=[],
        fetch_info={xorb_hash: [fetch_info1, fetch_info2]}
    )

    # 查找第二个范围
    url, url_range = client._find_xorb_in_recon(
        xorb_hash, recon, url_range=HttpRange(start=1500, end=1999)
    )

    assert url == "https://cdn.example.com/xorb2"
    assert url_range.start == 1024
    assert url_range.end == 2047
