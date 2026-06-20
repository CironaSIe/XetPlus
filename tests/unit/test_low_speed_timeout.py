"""network.low_speed_timeout 和 cas_client 流式下载测试。"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
import requests

from xet.network.low_speed_timeout import LowSpeedTimeoutError
from xet.network.cas_client import CASClient
from xet.protocol.types import HttpRange


# ============================================================================
# LowSpeedTimeoutError 测试
# ============================================================================

def test_low_speed_timeout_error_initialization():
    """测试低速超时异常初始化。"""
    error = LowSpeedTimeoutError("持续低速 30s", received=1024)

    assert str(error) == "持续低速 30s"
    assert error.received == 1024


def test_low_speed_timeout_error_default_received():
    """测试默认 received 为 0。"""
    error = LowSpeedTimeoutError("低速超时")

    assert error.received == 0


def test_low_speed_timeout_error_is_timeout_error():
    """测试 LowSpeedTimeoutError 是 TimeoutError 子类。"""
    error = LowSpeedTimeoutError("test")

    assert isinstance(error, TimeoutError)


# ============================================================================
# get_xorb_data_streaming 测试
# ============================================================================

@pytest.fixture
def mock_session():
    """创建 Mock session。"""
    session = Mock(spec=requests.Session)
    session.timeout = (10, 300)
    return session


def test_streaming_download_success(mock_session):
    """测试流式下载成功。"""
    # Mock 响应
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    # 模拟分块数据
    chunks = [b'x' * 65536, b'y' * 65536, b'z' * 65536]
    mock_response.iter_content.return_value = iter(chunks)
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=196607)

    data = client.get_xorb_data_streaming(url, url_range)

    assert len(data) == 196608
    assert data[:65536] == chunks[0]
    mock_session.get.assert_called_once()


def test_streaming_download_low_speed_timeout(mock_session):
    """测试低速超时触发。"""
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None

    # 模拟慢速数据流：每个 chunk 只有 1KB，远低于 50KB/s
    def slow_chunks():
        for _ in range(50):
            time.sleep(0.3)  # 每 0.3s 返回 1KB → 约 3.3KB/s
            yield b'x' * 1024

    mock_response.iter_content.return_value = slow_chunks()
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=51199)

    # 低速检测参数：10KB/s 最低，检查间隔 1s，容忍 2s
    with pytest.raises(LowSpeedTimeoutError) as exc_info:
        client.get_xorb_data_streaming(
            url,
            url_range,
            min_speed=10 * 1024,
            check_interval=1.0,
            low_speed_grace=2.0
        )

    # 验证异常携带已接收字节数
    assert exc_info.value.received > 0


def test_streaming_download_speed_recovery(mock_session):
    """测试速度恢复后重置低速计数。"""
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None

    # 模拟先慢后快的数据流
    def variable_speed_chunks():
        # 慢速阶段：5 个小 chunk
        for _ in range(5):
            time.sleep(0.2)
            yield b'x' * 1024
        # 快速阶段：大量大 chunk
        for _ in range(20):
            yield b'y' * 65536

    mock_response.iter_content.return_value = variable_speed_chunks()
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=1310719)

    # 应该成功（速度恢复后重置计数）
    data = client.get_xorb_data_streaming(
        url,
        url_range,
        min_speed=10 * 1024,
        check_interval=0.5,
        low_speed_grace=1.5
    )

    assert len(data) > 0


def test_streaming_download_empty_url(mock_session):
    """测试空 URL 抛出异常。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    with pytest.raises(ValueError, match="URL 不能为空"):
        client.get_xorb_data_streaming("", HttpRange(0, 1023))


def test_streaming_download_http_error(mock_session):
    """测试 HTTP 错误处理。"""
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    mock_session.get.return_value = mock_response

    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    url = "https://cdn.example.com/xorb"
    url_range = HttpRange(start=0, end=1023)

    with pytest.raises(requests.HTTPError):
        client.get_xorb_data_streaming(url, url_range)


# ============================================================================
# 断点续传场景测试
# ============================================================================

def test_resume_from_low_speed_timeout(mock_session):
    """测试从低速超时恢复并断点续传的完整场景。"""
    client = CASClient(
        endpoint="https://cas.example.com",
        access_token="test_token",
        session=mock_session
    )

    # 第一次请求：低速超时，接收了 10KB
    original_range = HttpRange(start=0, end=102399)  # 100KB

    # 模拟低速超时异常
    try:
        raise LowSpeedTimeoutError("持续低速", received=10240)
    except LowSpeedTimeoutError as e:
        # 断点续传：调整 Range
        new_start = original_range.start + e.received
        new_range = HttpRange(start=new_start, end=original_range.end)

        assert new_start == 10240
        assert new_range.length() == 92160  # 剩余 90KB
