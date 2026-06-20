"""network.cas_client 模块单元测试。"""
import pytest
from unittest.mock import Mock, patch

import requests

from xet.network.cas_client import CASClient
from xet.network.auth import XetAuth
from xet.protocol.types import HttpRange, XetFileInfo


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
# CASClient 初始化测试
# ============================================================================

def test_cas_client_initialization(mock_session):
    """测试 CAS 客户端初始化。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    assert client.endpoint == "https://cas.example.com"
    assert client.access_token == "test_token"
    assert client.session == mock_session
    assert len(client.session_id) == 16
    assert client._v2_available is None


def test_cas_client_endpoint_strip_slash(mock_session):
    """测试 endpoint 自动去除尾部斜杠。"""
    client = CASClient(
        endpoint="https://cas.example.com/",
        access_token="test_token",
        session=mock_session
    )

    assert client.endpoint == "https://cas.example.com"


# ============================================================================
# get_reconstruction 测试
# ============================================================================

def test_get_reconstruction_v2_success(mock_session):
    """测试 V2 API 成功获取 reconstruction。"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "offset_into_first_range": 0,
        "terms": [
            {
                "hash": "abc123",
                "range": {"start": 0, "end": 10},
                "unpacked_length": 1024
            }
        ],
        "fetch_info": {
            "abc123": [
                {
                    "url": "https://cdn.example.com/xorb",
                    "url_range": {"start": 0, "end": 1023},
                    "range": {"start": 0, "end": 10}
                }
            ]
        }
    }
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    recon = client.get_reconstruction("file_hash_123")

    assert recon.offset_into_first_range == 0
    assert len(recon.terms) == 1
    assert recon.terms[0].hash == "abc123"
    assert "abc123" in recon.fetch_info

    # 验证使用了 V2 API
    mock_session.get.assert_called_once()
    call_args = mock_session.get.call_args
    assert "/v2/reconstructions/" in call_args[0][0]


def test_get_reconstruction_v2_fallback_to_v1(mock_session):
    """测试 V2 失败后 fallback 到 V1。"""
    # V2 返回 404
    mock_response_v2 = Mock()
    mock_response_v2.status_code = 404

    # V1 返回 200
    mock_response_v1 = Mock()
    mock_response_v1.status_code = 200
    mock_response_v1.json.return_value = {
        "offset_into_first_range": 0,
        "terms": [],
        "fetch_info": {}
    }

    mock_session.get.side_effect = [mock_response_v2, mock_response_v1]

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    recon = client.get_reconstruction("file_hash_123")

    assert recon.offset_into_first_range == 0
    assert mock_session.get.call_count == 2
    assert client._v2_available is False


def test_get_reconstruction_401_refresh_token(mock_session, mock_auth):
    """测试 401 时自动刷新 token。"""
    # 第一次返回 401
    mock_response_401 = Mock()
    mock_response_401.status_code = 401
    mock_response_401.raise_for_status.side_effect = requests.HTTPError("401")

    # 第二次返回 200
    mock_response_200 = Mock()
    mock_response_200.status_code = 200
    mock_response_200.json.return_value = {
        "offset_into_first_range": 0,
        "terms": [],
        "fetch_info": {}
    }

    mock_session.get.side_effect = [mock_response_401, mock_response_200]

    # Mock auth.get_token 返回新 token
    from xet.protocol.types import XetTokenInfo
    import time
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

    recon = client.get_reconstruction("file_hash_123")

    # 验证 token 已刷新
    assert client.access_token == "new_token"
    mock_auth.clear_cache.assert_called_once()
    mock_auth.get_token.assert_called_once()


def test_get_reconstruction_no_auth_on_401(mock_session):
    """测试 401 但无 auth 配置时抛出异常。"""
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = requests.HTTPError("401")
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=None  # 无 auth 配置
    )

    with pytest.raises(RuntimeError, match="无法刷新 token"):
        client.get_reconstruction("file_hash_123")


# ============================================================================
# get_xorb_data 测试
# ============================================================================

def test_get_xorb_data_success(mock_session):
    """测试成功下载 xorb 数据。"""
    mock_response = Mock()
    mock_response.content = b"xorb_data_content"
    mock_response.raise_for_status.return_value = None
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb/abc123"
    url_range = HttpRange(start=0, end=1023)
    data = client.get_xorb_data(url, url_range)

    assert data == b"xorb_data_content"

    # 验证请求头
    call_args = mock_session.get.call_args
    headers = call_args[1]['headers']
    assert headers['Range'] == 'bytes=0-1023'
    assert headers['X-Xet-Session-Id'] == client.session_id
    assert headers['Authorization'] is None  # 关键：无 Authorization


def test_get_xorb_data_empty_url(mock_session):
    """测试空 URL 抛出异常。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url_range = HttpRange(start=0, end=1023)

    with pytest.raises(ValueError, match="URL 不能为空"):
        client.get_xorb_data("", url_range)


def test_get_xorb_data_http_error(mock_session):
    """测试 HTTP 错误（重试后失败）。"""
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb/abc123"
    url_range = HttpRange(start=0, end=1023)

    # 装饰器会重试 5 次，最终抛出 RetryError
    from xet.network.retry import RetryError
    with pytest.raises(RetryError):
        client.get_xorb_data(url, url_range)


# ============================================================================
# get_xet_file_info 测试
# ============================================================================

def test_get_xet_file_info_success(mock_session):
    """测试成功获取 Xet 文件信息。"""
    mock_response = Mock()
    mock_response.headers = {
        'X-Xet-Hash': 'abc123' * 10 + 'abcd',  # 64 字符
        'X-Linked-ETag': '"sha256_hash"',
        'X-Linked-Size': '1048576',
        'Location': 'https://cdn.example.com/file',
        'Link': '<https://example.com/auth>; rel="xet-auth"'
    }
    mock_response.raise_for_status.return_value = None
    mock_session.head.return_value = mock_response

    file_info = CASClient.get_xet_file_info(
        "https://huggingface.co/user/repo/file.bin",
        mock_session
    )

    assert file_info.xet_hash == 'abc123' * 10 + 'abcd'
    assert file_info.sha256 == 'sha256_hash'
    assert file_info.size == 1048576
    assert file_info.location == 'https://cdn.example.com/file'
    assert file_info.auth_url == 'https://example.com/auth'


def test_get_xet_file_info_not_xet_file(mock_session):
    """测试非 Xet 文件（缺少 X-Xet-Hash）。"""
    mock_response = Mock()
    mock_response.headers = {}  # 缺少 X-Xet-Hash
    mock_response.raise_for_status.return_value = None
    mock_session.head.return_value = mock_response

    with pytest.raises(ValueError, match="不是 Xet 文件"):
        CASClient.get_xet_file_info(
            "https://huggingface.co/user/repo/file.bin",
            mock_session
        )


def test_get_xet_file_info_case_insensitive_headers(mock_session):
    """测试大小写不敏感的 headers（CASClient 检查时支持）。"""
    mock_response = Mock()
    # 小写 headers（CASClient.get_xet_file_info 检查时支持）
    mock_response.headers = {
        'x-xet-hash': 'lowercase_hash' * 3 + 'ab',  # 64 字符
        'x-linked-etag': '"sha256"',
        'x-linked-size': '2048'
    }
    mock_response.raise_for_status.return_value = None
    mock_session.head.return_value = mock_response

    # CASClient.get_xet_file_info 会先检查小写，然后调用 from_headers
    # 但 from_headers 需要标准大小写，所以这里测试 CASClient 的检查逻辑
    # 实际上 from_headers 已经支持了小写 fallback
    file_info = CASClient.get_xet_file_info(
        "https://huggingface.co/user/repo/file.bin",
        mock_session
    )

    assert file_info.xet_hash == 'lowercase_hash' * 3 + 'ab'
    assert file_info.sha256 == 'sha256'
    assert file_info.size == 2048


# ============================================================================
# 辅助方法测试
# ============================================================================

def test_get_headers(mock_session):
    """测试获取标准请求头。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token_123",
        session=mock_session
    )

    headers = client._get_headers()

    assert headers['Authorization'] == 'Bearer test_token_123'


def test_refresh_token_success(mock_session, mock_auth):
    """测试成功刷新 token。"""
    from xet.protocol.types import XetTokenInfo
    import time

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

    client._refresh_token()

    assert client.access_token == "refreshed_token"
    mock_auth.clear_cache.assert_called_once()
    mock_auth.get_token.assert_called_once_with("user/repo", auth_url=None)


def test_refresh_token_no_auth(mock_session):
    """测试无 auth 配置时刷新失败。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session,
        auth=None
    )

    with pytest.raises(RuntimeError, match="无法刷新 token"):
        client._refresh_token()
