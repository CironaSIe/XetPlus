# Phase 3 开发计划 - Network Layer (网络层)

## 目标

实现 CAS API 客户端和 HTTP 工具函数，支持重试、错误处理、ACC（Alternative Content Cache）回退机制。

---

## 核心设计

### 1. 重试装饰器（Decorator Pattern）

```python
@with_retry(max_attempts=5, backoff_base=1.5)
def fetch_data(url: str) -> bytes:
    """业务逻辑，重试由装饰器处理。"""
    return requests.get(url).content
```

**特性**：
- 指数退避（exponential backoff）
- 可配置重试次数
- 只对网络错误重试，不重试 4xx 客户端错误

### 2. CAS API 客户端

```python
class CASClient:
    """CAS (Content-Addressable Storage) API 客户端。"""
    
    def get_token(self, auth_url: str) -> XetTokenInfo:
        """获取访问 token。"""
    
    def query_reconstruction(self, url: str, ...) -> QueryReconstructionResponse:
        """查询文件重建信息。"""
    
    def fetch_xorb(self, url: str, byte_range: HttpRange) -> bytes:
        """下载 xorb 数据。"""
```

**特性**：
- 自动重试
- ACC 回退（token 过期时）
- 统一的错误处理

---

## 任务清单

### Task 3.1: 实现重试装饰器（1 天）

**文件**: `xet/network/retry.py`

```python
import time
import logging
from typing import Callable, TypeVar, Any
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryError(Exception):
    """重试失败后抛出的异常。"""
    pass


def with_retry(
    max_attempts: int = 5,
    backoff_base: float = 1.5,
    max_backoff: float = 60.0,
    retry_on: tuple = (Exception,)
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """重试装饰器。
    
    支持指数退避，只对指定异常重试。
    
    Args:
        max_attempts: 最大尝试次数（包含首次）
        backoff_base: 退避基数
        max_backoff: 最大退避时间（秒）
        retry_on: 要重试的异常类型元组
    
    Example:
        @with_retry(max_attempts=3, backoff_base=2.0)
        def fetch_data(url):
            return requests.get(url).content
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        # 最后一次尝试失败
                        logger.error(
                            f"{func.__name__} 重试 {max_attempts} 次后失败: {e}"
                        )
                        raise RetryError(
                            f"重试 {max_attempts} 次后失败"
                        ) from e
                    
                    # 计算退避时间
                    backoff = min(
                        backoff_base ** (attempt - 1),
                        max_backoff
                    )
                    
                    logger.warning(
                        f"{func.__name__} 第 {attempt} 次尝试失败: {e}, "
                        f"{backoff:.1f}s 后重试"
                    )
                    
                    time.sleep(backoff)
            
            # 不应该到这里
            raise RetryError("重试逻辑错误") from last_exception
        
        return wrapper
    return decorator
```

**验收标准**：
- [ ] 重试装饰器实现
- [ ] 指数退避计算正确
- [ ] 可配置重试次数和异常类型
- [ ] 单元测试覆盖 90%+

---

### Task 3.2: 实现 HTTP 工具函数（2 天）

**文件**: `xet/network/http_utils.py`

```python
import requests
from typing import Optional, Dict
from pathlib import Path

from xet.protocol.types import HttpRange


def create_session(proxy: Optional[str] = None) -> requests.Session:
    """创建 HTTP session。
    
    Args:
        proxy: 代理 URL（如 http://127.0.0.1:8080）
    
    Returns:
        配置好的 Session 实例
    """
    session = requests.Session()
    
    if proxy:
        session.proxies = {
            'http': proxy,
            'https': proxy,
        }
    
    # 设置超时
    session.timeout = (10, 300)  # (connect, read)
    
    return session


def fetch_with_range(
    session: requests.Session,
    url: str,
    byte_range: HttpRange,
    headers: Optional[Dict[str, str]] = None
) -> bytes:
    """使用 HTTP Range 下载数据。
    
    Args:
        session: requests.Session 实例
        url: 目标 URL
        byte_range: 字节范围
        headers: 额外的 HTTP headers
    
    Returns:
        下载的数据
    
    Raises:
        requests.HTTPError: HTTP 错误
    """
    req_headers = headers or {}
    req_headers['Range'] = byte_range.to_header()
    
    resp = session.get(url, headers=req_headers)
    resp.raise_for_status()
    
    return resp.content


def download_file(
    session: requests.Session,
    url: str,
    output_path: Path,
    chunk_size: int = 64 * 1024
) -> None:
    """流式下载文件。
    
    Args:
        session: requests.Session 实例
        url: 目标 URL
        output_path: 输出文件路径
        chunk_size: 每次读取的块大小
    
    Raises:
        requests.HTTPError: HTTP 错误
    """
    resp = session.get(url, stream=True)
    resp.raise_for_status()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
```

**验收标准**：
- [ ] Session 创建（支持代理）
- [ ] Range 下载
- [ ] 流式下载
- [ ] 单元测试覆盖 85%+

---

### Task 3.3: 实现 CAS API 客户端（4 天）

**文件**: `xet/network/cas_client.py`

#### 核心功能

1. **Token 获取**
```python
def get_token(self, auth_url: str, hf_token: str) -> XetTokenInfo:
    """从 HuggingFace 获取 CAS access token。"""
```

2. **Reconstruction 查询**
```python
def query_reconstruction(
    self,
    recon_url: str,
    token: XetTokenInfo,
    file_hash: str,
    byte_range: Optional[HttpRange] = None
) -> QueryReconstructionResponse:
    """查询文件重建信息。"""
```

3. **Xorb 下载**
```python
def fetch_xorb(
    self,
    fetch_info: CASReconstructionFetchInfo,
    token: XetTokenInfo
) -> bytes:
    """下载单个 xorb 数据。"""
```

4. **ACC 回退**
```python
def fetch_xorb_with_acc_fallback(
    self,
    fetch_info: CASReconstructionFetchInfo,
    token: XetTokenInfo
) -> bytes:
    """下载 xorb，失败时回退到 ACC。"""
```

#### 设计要点

- 所有网络请求都用 `@with_retry` 装饰
- Token 过期自动刷新
- ACC URL 从 fetch_info 提取
- 统一的错误处理

**验收标准**：
- [ ] Token 获取实现
- [ ] Reconstruction 查询实现
- [ ] Xorb 下载实现
- [ ] ACC 回退机制
- [ ] 单元测试覆盖 85%+
- [ ] 集成测试（使用真实 API）

---

### Task 3.4: 编写单元测试（2 天）

**文件**: 
- `tests/unit/test_retry.py`
- `tests/unit/test_http_utils.py`
- `tests/unit/test_cas_client.py`

#### 测试用例

**retry.py (10 个)**:
```python
def test_retry_success_first_try()
def test_retry_success_second_try()
def test_retry_all_failed()
def test_retry_backoff_calculation()
def test_retry_max_backoff()
def test_retry_custom_exception()
def test_retry_no_retry_on_other_exception()
def test_retry_zero_attempts()
def test_retry_one_attempt()
def test_retry_preserves_return_value()
```

**http_utils.py (8 个)**:
```python
def test_create_session_no_proxy()
def test_create_session_with_proxy()
def test_fetch_with_range()
def test_fetch_with_range_custom_headers()
def test_fetch_with_range_http_error()
def test_download_file()
def test_download_file_stream()
def test_download_file_http_error()
```

**cas_client.py (12 个)**:
```python
def test_cas_client_init()
def test_get_token()
def test_get_token_http_error()
def test_query_reconstruction()
def test_query_reconstruction_with_range()
def test_query_reconstruction_http_error()
def test_fetch_xorb()
def test_fetch_xorb_http_error()
def test_fetch_xorb_with_acc_fallback_success()
def test_fetch_xorb_with_acc_fallback_fallback()
def test_fetch_xorb_with_acc_fallback_both_fail()
def test_token_refresh()
```

---

### Task 3.5: 集成测试（1 天）

**文件**: `tests/integration/test_network_integration.py`

使用真实 HuggingFace API 测试：
1. 完整的 token 获取流程
2. Reconstruction 查询（使用测试文件）
3. Xorb 下载（小文件）
4. ACC 回退机制

---

## 时间估算

| 任务 | 预计时间 |
|------|---------|
| Task 3.1 | 8 小时 |
| Task 3.2 | 16 小时 |
| Task 3.3 | 32 小时 |
| Task 3.4 | 16 小时 |
| Task 3.5 | 8 小时 |
| **总计** | **80 小时** |

按每天工作 6 小时计算 = **13 个工作日**

---

## 设计决策

### 为什么用装饰器模式？

**旧版问题**: 重试逻辑散布在各处，难以统一修改

**新版方案**:
```python
@with_retry(max_attempts=5)
def fetch_data(url):
    return requests.get(url).content
```

**优势**:
- 业务逻辑清晰
- 重试策略统一
- 易于测试

### 为什么需要 ACC 回退？

**场景**: CAS 主服务器可能返回 403（token 过期或流量限制）

**解决方案**:
```python
try:
    data = fetch_from_primary(url)
except HTTPError as e:
    if e.status_code == 403:
        data = fetch_from_acc(acc_url)  # 回退
```

**优势**: 提高下载成功率

---

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| API 变更 | 低 | 高 | 参考官方规范 XET.SPEC.md |
| Token 过期 | 中 | 中 | 自动刷新 + ACC 回退 |
| 网络不稳定 | 中 | 中 | 重试机制 |

---

## 验收标准（Phase 3 完成）

- [ ] `xet/network/retry.py` 完成
- [ ] `xet/network/http_utils.py` 完成
- [ ] `xet/network/cas_client.py` 完成
- [ ] 单元测试覆盖率 85%+
- [ ] 集成测试通过（真实 API）
- [ ] 所有测试通过
- [ ] 文档完整

---

## 下一步（Phase 4）

完成 Phase 3 后，开始 Pipeline Layer 开发：
- `pipeline/scheduler.py` - 下载调度器
- `pipeline/downloader.py` - 并发下载管理
- `pipeline/assembler.py` - 数据组装

---

## 立即行动

**开始 Task 3.1**: 实现重试装饰器

```bash
cd ~/xetplus
vim xet/network/retry.py
```
