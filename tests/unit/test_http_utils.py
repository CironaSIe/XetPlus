"""network.http_utils 模块单元测试。"""
import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

import requests

from xet.network.http_utils import (
    create_session,
    fetch_with_range,
    fetch_url,
    download_file,
    post_json,
    get_json,
)
from xet.protocol.types import HttpRange


@pytest.fixture
def temp_dir():
    """创建临时目录。"""
    tmpdir = Path(tempfile.mkdtemp())
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================================
# create_session 测试
# ============================================================================

def test_create_session_no_proxy():
    """测试创建无代理的 session。"""
    session = create_session()

    assert isinstance(session, requests.Session)
    assert not session.proxies  # 无代理
    assert hasattr(session, 'timeout')
    assert session.timeout == (10, 300)


def test_create_session_with_proxy():
    """测试创建带代理的 session。"""
    proxy = "http://127.0.0.1:8080"
    session = create_session(proxy=proxy)

    assert session.proxies['http'] == proxy
    assert session.proxies['https'] == proxy


def test_create_session_custom_timeout():
    """测试自定义超时。"""
    session = create_session(timeout=(5, 60))

    assert session.timeout == (5, 60)


# ============================================================================
# fetch_with_range 测试
# ============================================================================

def test_fetch_with_range():
    """测试 Range 下载。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.content = b"partial data"
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    byte_range = HttpRange(start=0, end=1023)
    result = fetch_with_range(mock_session, "http://example.com/file", byte_range)

    assert result == b"partial data"
    mock_session.get.assert_called_once()

    # 检查 headers
    call_args = mock_session.get.call_args
    headers = call_args[1]['headers']
    assert headers['Range'] == 'bytes=0-1023'


def test_fetch_with_range_custom_headers():
    """测试带自定义 headers 的 Range 下载。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.content = b"data"
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    byte_range = HttpRange(start=100, end=199)
    custom_headers = {'Authorization': 'Bearer token123'}

    result = fetch_with_range(
        mock_session,
        "http://example.com/file",
        byte_range,
        headers=custom_headers
    )

    assert result == b"data"

    # 检查 headers 合并
    call_args = mock_session.get.call_args
    headers = call_args[1]['headers']
    assert headers['Range'] == 'bytes=100-199'
    assert headers['Authorization'] == 'Bearer token123'


def test_fetch_with_range_http_error():
    """测试 HTTP 错误。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    byte_range = HttpRange(start=0, end=99)

    with pytest.raises(requests.HTTPError):
        fetch_with_range(mock_session, "http://example.com/file", byte_range)


# ============================================================================
# fetch_url 测试
# ============================================================================

def test_fetch_url():
    """测试完整 URL 下载。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.content = b"full content"
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    result = fetch_url(mock_session, "http://example.com/file")

    assert result == b"full content"
    mock_session.get.assert_called_once()


def test_fetch_url_with_headers():
    """测试带 headers 的下载。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.content = b"data"
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    headers = {'User-Agent': 'TestAgent/1.0'}
    result = fetch_url(mock_session, "http://example.com/file", headers=headers)

    call_args = mock_session.get.call_args
    assert call_args[1]['headers'] == headers


# ============================================================================
# download_file 测试
# ============================================================================

def test_download_file(temp_dir):
    """测试流式下载文件。"""
    output_path = temp_dir / "output.bin"

    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.iter_content.return_value = [b"chunk1", b"chunk2", b"chunk3"]
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    download_file(mock_session, "http://example.com/file", output_path)

    # 验证文件内容
    assert output_path.exists()
    assert output_path.read_bytes() == b"chunk1chunk2chunk3"

    # 验证使用了 stream=True
    call_args = mock_session.get.call_args
    assert call_args[1]['stream'] is True


def test_download_file_custom_chunk_size(temp_dir):
    """测试自定义 chunk size。"""
    output_path = temp_dir / "output.bin"

    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.iter_content.return_value = [b"data"]
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    download_file(mock_session, "http://example.com/file", output_path, chunk_size=1024)

    # 验证 chunk_size 参数传递
    mock_response.iter_content.assert_called_with(chunk_size=1024)


def test_download_file_creates_directory(temp_dir):
    """测试自动创建目录。"""
    output_path = temp_dir / "subdir" / "nested" / "output.bin"

    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.iter_content.return_value = [b"data"]
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    download_file(mock_session, "http://example.com/file", output_path)

    # 验证目录被创建
    assert output_path.parent.exists()
    assert output_path.exists()


def test_download_file_http_error(temp_dir):
    """测试下载时的 HTTP 错误。"""
    output_path = temp_dir / "output.bin"

    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("404")
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    with pytest.raises(requests.HTTPError):
        download_file(mock_session, "http://example.com/file", output_path)

    # 文件不应该被创建
    assert not output_path.exists()


# ============================================================================
# post_json 测试
# ============================================================================

def test_post_json():
    """测试 POST JSON 请求。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.json.return_value = {"result": "success"}
    mock_session.post.return_value = mock_response
    mock_session.timeout = (10, 300)

    json_data = {"key": "value"}
    result = post_json(mock_session, "http://example.com/api", json_data)

    assert result == {"result": "success"}
    mock_session.post.assert_called_once()

    # 检查 json 参数
    call_args = mock_session.post.call_args
    assert call_args[1]['json'] == json_data


def test_post_json_with_headers():
    """测试带 headers 的 POST 请求。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.json.return_value = {"status": "ok"}
    mock_session.post.return_value = mock_response
    mock_session.timeout = (10, 300)

    headers = {'Authorization': 'Bearer token'}
    result = post_json(
        mock_session,
        "http://example.com/api",
        {"data": "test"},
        headers=headers
    )

    call_args = mock_session.post.call_args
    assert call_args[1]['headers'] == headers


def test_post_json_http_error():
    """测试 POST 时的 HTTP 错误。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("400")
    mock_session.post.return_value = mock_response
    mock_session.timeout = (10, 300)

    with pytest.raises(requests.HTTPError):
        post_json(mock_session, "http://example.com/api", {})


# ============================================================================
# get_json 测试
# ============================================================================

def test_get_json():
    """测试 GET JSON 请求。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.json.return_value = {"key": "value", "list": [1, 2, 3]}
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    result = get_json(mock_session, "http://example.com/api/data")

    assert result == {"key": "value", "list": [1, 2, 3]}
    mock_session.get.assert_called_once()


def test_get_json_with_headers():
    """测试带 headers 的 GET 请求。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.json.return_value = {"data": "test"}
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    headers = {'Accept': 'application/json'}
    result = get_json(mock_session, "http://example.com/api", headers=headers)

    call_args = mock_session.get.call_args
    assert call_args[1]['headers'] == headers


def test_get_json_invalid_json():
    """测试无效的 JSON 响应。"""
    mock_session = Mock(spec=requests.Session)
    mock_response = Mock()
    mock_response.json.side_effect = ValueError("Invalid JSON")
    mock_session.get.return_value = mock_response
    mock_session.timeout = (10, 300)

    with pytest.raises(ValueError):
        get_json(mock_session, "http://example.com/api")
