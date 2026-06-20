"""network.auth 模块单元测试。"""
import pytest
import time
from unittest.mock import Mock, patch

import requests

from xet.network.auth import XetAuth
from xet.protocol.types import XetTokenInfo


@pytest.fixture
def mock_session():
    """创建 Mock session。"""
    session = Mock(spec=requests.Session)
    session.timeout = (10, 300)
    return session


# ============================================================================
# XetAuth 基本功能测试
# ============================================================================

def test_auth_initialization(mock_session):
    """测试认证管理器初始化。"""
    auth = XetAuth("hf_test_token", mock_session)

    assert auth.hf_token == "hf_test_token"
    assert auth.session == mock_session
    assert auth._token_cache is None


def test_get_token_with_auth_url(mock_session):
    """测试使用显式 auth_url 获取 token。"""
    # Mock 响应
    mock_response = Mock()
    mock_response.json.return_value = {
        "accessToken": "cas_token_123",
        "endpoint": "https://cas.example.com",
        "expiration": int(time.time()) + 3600
    }
    mock_session.get.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)
    token_info = auth.get_token(
        "user/repo",
        auth_url="https://huggingface.co/api/models/user/repo/xet-read-token/abc123"
    )

    assert token_info.access_token == "cas_token_123"
    assert token_info.endpoint == "https://cas.example.com"
    assert token_info.expiration > time.time()

    # 验证请求
    mock_session.get.assert_called_once()
    call_args = mock_session.get.call_args
    assert "Authorization" in call_args[1]["headers"]


def test_get_token_with_fallback(mock_session):
    """测试无 auth_url 时的 fallback 获取。"""
    # Mock HEAD 请求（解析 revision）
    mock_head_response = Mock()
    mock_head_response.status_code = 302
    mock_head_response.headers = {
        "Location": "/models/user/repo/resolve/commit123/file.txt",
        "Link": ""  # 无 Link header
    }

    # Mock GET 请求（获取 token）
    mock_get_response = Mock()
    mock_get_response.json.return_value = {
        "accessToken": "cas_token_456",
        "endpoint": "https://cas-server.xethub.hf.co",
        "expiration": int(time.time()) + 3600
    }

    mock_session.head.return_value = mock_head_response
    mock_session.get.return_value = mock_get_response

    auth = XetAuth("hf_test_token", mock_session)
    token_info = auth.get_token("user/repo", repo_type="model", revision="main")

    assert token_info.access_token == "cas_token_456"
    assert token_info.endpoint == "https://cas-server.xethub.hf.co"

    # 验证调用
    assert mock_session.head.call_count == 1
    assert mock_session.get.call_count == 1


def test_token_cache_reuse(mock_session):
    """测试 token 缓存复用。"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "accessToken": "cas_token_789",
        "endpoint": "https://cas.example.com",
        "expiration": int(time.time()) + 3600
    }
    mock_session.get.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)

    # 第一次调用
    token1 = auth.get_token("user/repo", auth_url="https://example.com/token")
    assert mock_session.get.call_count == 1

    # 第二次调用（应使用缓存）
    token2 = auth.get_token("user/repo", auth_url="https://example.com/token")
    assert mock_session.get.call_count == 1  # 没有新请求
    assert token1 == token2


def test_token_cache_expires(mock_session):
    """测试 token 缓存过期后重新获取。"""
    # 第一次响应（即将过期）
    mock_response1 = Mock()
    mock_response1.json.return_value = {
        "accessToken": "old_token",
        "endpoint": "https://cas.example.com",
        "expiration": int(time.time()) + 30  # 30 秒后过期（小于 60s 缓冲）
    }

    # 第二次响应
    mock_response2 = Mock()
    mock_response2.json.return_value = {
        "accessToken": "new_token",
        "endpoint": "https://cas.example.com",
        "expiration": int(time.time()) + 3600
    }

    mock_session.get.side_effect = [mock_response1, mock_response2]

    auth = XetAuth("hf_test_token", mock_session)

    # 第一次调用
    token1 = auth.get_token("user/repo", auth_url="https://example.com/token")
    assert token1.access_token == "old_token"

    # 第二次调用（缓存过期，重新获取）
    token2 = auth.get_token("user/repo", auth_url="https://example.com/token")
    assert token2.access_token == "new_token"
    assert mock_session.get.call_count == 2


def test_clear_cache(mock_session):
    """测试清除缓存。"""
    mock_response = Mock()
    mock_response.json.return_value = {
        "accessToken": "token",
        "endpoint": "https://cas.example.com",
        "expiration": int(time.time()) + 3600
    }
    mock_session.get.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)

    # 获取 token
    auth.get_token("user/repo", auth_url="https://example.com/token")
    assert auth._token_cache is not None

    # 清除缓存
    auth.clear_cache()
    assert auth._token_cache is None

    # 再次获取（应发起新请求）
    auth.get_token("user/repo", auth_url="https://example.com/token")
    assert mock_session.get.call_count == 2


# ============================================================================
# Link header 解析测试
# ============================================================================

def test_parse_link_header_with_auth():
    """测试解析包含 xet-auth 的 Link header。"""
    link_header = '<https://huggingface.co/api/models/user/repo/xet-read-token/abc123>; rel="xet-auth"'

    auth_url = XetAuth._parse_link_header(link_header)

    assert auth_url == "https://huggingface.co/api/models/user/repo/xet-read-token/abc123"


def test_parse_link_header_multiple_links():
    """测试解析包含多个链接的 Link header。"""
    link_header = (
        '<https://example.com/auth>; rel="xet-auth", '
        '<https://example.com/recon>; rel="xet-reconstruction-info"'
    )

    auth_url = XetAuth._parse_link_header(link_header)

    assert auth_url == "https://example.com/auth"


def test_parse_link_header_empty():
    """测试解析空 Link header。"""
    auth_url = XetAuth._parse_link_header("")
    assert auth_url is None


def test_parse_link_header_no_xet_auth():
    """测试解析不包含 xet-auth 的 Link header。"""
    link_header = '<https://example.com/other>; rel="other"'

    auth_url = XetAuth._parse_link_header(link_header)

    assert auth_url is None


# ============================================================================
# 错误处理测试
# ============================================================================

def test_http_error_handling(mock_session):
    """测试 HTTP 错误处理。"""
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
    mock_session.get.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)

    with pytest.raises(requests.HTTPError):
        auth.get_token("user/repo", auth_url="https://example.com/token")


def test_invalid_revision_response(mock_session):
    """测试无效的 revision 响应。"""
    # 返回 200 而不是重定向
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_session.head.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)

    with pytest.raises(ValueError, match="预期重定向"):
        auth.get_token("user/repo", repo_type="model", revision="main")


def test_malformed_location_header(mock_session):
    """测试格式错误的 Location header。"""
    mock_response = Mock()
    mock_response.status_code = 302
    mock_response.headers = {
        "Location": "/invalid/path",  # 没有 /resolve/
        "Link": ""
    }
    mock_session.head.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)

    with pytest.raises(ValueError, match="无法从 Location header 解析"):
        auth.get_token("user/repo", repo_type="model", revision="main")


# ============================================================================
# 公开仓库兼容性测试
# ============================================================================

def test_public_repo_token_minimal_response(mock_session):
    """测试公开仓库只返回 accessToken 的情况。"""
    # 只返回 accessToken，缺少 endpoint 和 expiration
    mock_response = Mock()
    mock_response.json.return_value = {
        "accessToken": "public_token"
    }
    mock_session.get.return_value = mock_response

    auth = XetAuth("hf_test_token", mock_session)
    token_info = auth.get_token("user/repo", auth_url="https://example.com/token")

    assert token_info.access_token == "public_token"
    assert token_info.endpoint == "https://cas-server.xethub.hf.co"  # 默认值
    assert token_info.expiration > time.time()  # 默认 1 小时后
