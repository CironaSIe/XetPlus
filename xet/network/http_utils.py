"""HTTP 工具函数。

提供 HTTP 请求的常用操作，包括 Range 下载、流式下载等。
"""
from __future__ import annotations

import requests
from typing import Optional, Dict
from pathlib import Path

from xet.protocol.types import HttpRange


def create_session(
    proxy: Optional[str] = None,
    timeout: tuple[int, int] = (10, 300)
) -> requests.Session:
    """创建配置好的 HTTP Session。

    Args:
        proxy: 代理 URL（如 http://127.0.0.1:8080）
        timeout: (connect_timeout, read_timeout) 元组（秒）

    Returns:
        配置好的 Session 实例

    Example:
        >>> session = create_session()
        >>> # 使用代理
        >>> session = create_session(proxy='http://127.0.0.1:8080')
    """
    session = requests.Session()

    # 配置代理
    if proxy:
        session.proxies = {
            'http': proxy,
            'https': proxy,
        }

    # 设置默认超时
    # 注意：requests 不支持直接在 Session 设置 timeout
    # 需要在每次请求时传入
    session.timeout = timeout  # type: ignore

    return session


def fetch_with_range(
    session: requests.Session,
    url: str,
    byte_range: HttpRange,
    headers: Optional[Dict[str, str]] = None
) -> bytes:
    """使用 HTTP Range 下载指定范围的数据。

    Args:
        session: requests.Session 实例
        url: 目标 URL
        byte_range: 字节范围
        headers: 额外的 HTTP headers

    Returns:
        下载的数据

    Raises:
        requests.HTTPError: HTTP 错误（4xx, 5xx）
        requests.RequestException: 网络错误

    Example:
        >>> session = create_session()
        >>> byte_range = HttpRange(start=0, end=1023)
        >>> data = fetch_with_range(session, url, byte_range)
        >>> len(data)
        1024
    """
    req_headers = headers.copy() if headers else {}
    req_headers['Range'] = byte_range.to_header()

    timeout = getattr(session, 'timeout', (10, 300))
    resp = session.get(url, headers=req_headers, timeout=timeout)
    resp.raise_for_status()

    return resp.content


def fetch_url(
    session: requests.Session,
    url: str,
    headers: Optional[Dict[str, str]] = None
) -> bytes:
    """下载完整 URL 内容。

    Args:
        session: requests.Session 实例
        url: 目标 URL
        headers: 额外的 HTTP headers

    Returns:
        下载的数据

    Raises:
        requests.HTTPError: HTTP 错误
        requests.RequestException: 网络错误
    """
    timeout = getattr(session, 'timeout', (10, 300))
    resp = session.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    return resp.content


def download_file(
    session: requests.Session,
    url: str,
    output_path: Path,
    chunk_size: int = 64 * 1024,
    headers: Optional[Dict[str, str]] = None
) -> None:
    """流式下载文件到磁盘。

    使用流式传输，适合大文件下载。

    Args:
        session: requests.Session 实例
        url: 目标 URL
        output_path: 输出文件路径
        chunk_size: 每次读取的块大小（字节）
        headers: 额外的 HTTP headers

    Raises:
        requests.HTTPError: HTTP 错误
        requests.RequestException: 网络错误
        IOError: 文件写入错误

    Example:
        >>> session = create_session()
        >>> download_file(session, url, Path('output.bin'))
    """
    timeout = getattr(session, 'timeout', (10, 300))
    resp = session.get(url, headers=headers, stream=True, timeout=timeout)
    resp.raise_for_status()

    # 确保目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:  # 过滤掉 keep-alive 的空 chunk
                f.write(chunk)


def post_json(
    session: requests.Session,
    url: str,
    json_data: dict,
    headers: Optional[Dict[str, str]] = None
) -> dict:
    """发送 POST JSON 请求。

    Args:
        session: requests.Session 实例
        url: 目标 URL
        json_data: 要发送的 JSON 数据
        headers: 额外的 HTTP headers

    Returns:
        响应的 JSON 数据

    Raises:
        requests.HTTPError: HTTP 错误
        requests.RequestException: 网络错误
        ValueError: 响应不是有效 JSON
    """
    timeout = getattr(session, 'timeout', (10, 300))
    resp = session.post(url, json=json_data, headers=headers, timeout=timeout)
    resp.raise_for_status()

    return resp.json()


def get_json(
    session: requests.Session,
    url: str,
    headers: Optional[Dict[str, str]] = None
) -> dict:
    """发送 GET 请求并解析 JSON。

    Args:
        session: requests.Session 实例
        url: 目标 URL
        headers: 额外的 HTTP headers

    Returns:
        响应的 JSON 数据

    Raises:
        requests.HTTPError: HTTP 错误
        requests.RequestException: 网络错误
        ValueError: 响应不是有效 JSON
    """
    timeout = getattr(session, 'timeout', (10, 300))
    resp = session.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    return resp.json()
