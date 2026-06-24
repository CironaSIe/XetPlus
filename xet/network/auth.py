"""XET 认证模块。

处理从 HuggingFace Hub 获取 CAS (Content Addressable Storage) 访问 token 的逻辑。
支持 token 缓存和自动刷新。
"""
import time
import logging
import re
from typing import Optional, Tuple

import requests

from xet.protocol.types import XetTokenInfo

logger = logging.getLogger(__name__)

# 仓库类型 → API URL 中复数路径的映射表
REPO_TYPE_PLURAL_MAP = {
    "model": "models",
    "dataset": "datasets",
    "space": "spaces",
}


class XetAuth:
    """HuggingFace → CAS Token 认证管理器。

    负责：
    1. 从 HuggingFace API 获取 CAS read token
    2. 缓存 token 以避免重复请求
    3. 自动检测过期并刷新
    4. 解析 HTTP Link header 提取认证端点 URL

    Attributes:
        hf_token: HuggingFace access token（用于认证）
        session: requests.Session 实例（复用连接池和代理配置）
        _token_cache: 缓存的 XetTokenInfo 对象
    """

    def __init__(self, hf_token: str, session: requests.Session, hf_endpoint: Optional[str] = None):
        """初始化认证管理器。

        Args:
            hf_token: HuggingFace 用户 access token
            session: 已配置好的 requests.Session（含代理等设置）
            hf_endpoint: 自定义 HF API 端点（如 https://hf-mirror.com），默认 huggingface.co
        """
        self.hf_token = hf_token
        self.session = session
        self.hf_endpoint = (hf_endpoint or "https://huggingface.co").rstrip("/")
        self._token_cache: Optional[XetTokenInfo] = None

    def get_token(
        self,
        repo_id: str,
        repo_type: str = "model",
        revision: str = "main",
        auth_url: Optional[str] = None
    ) -> XetTokenInfo:
        """获取有效的 CAS token。

        如果缓存中的 token 未过期则直接返回，否则重新请求。

        Args:
            repo_id: HuggingFace 仓库 ID（如 "user/repo"）
            repo_type: 仓库类型（"model", "dataset"）
            revision: Git 分支/标签（默认 "main"）
            auth_url: 可选的显式 auth URL（优先使用）

        Returns:
            包含 access_token、endpoint、expiration 的 XetTokenInfo

        Raises:
            requests.HTTPError: token 获取失败
        """
        # 检查缓存（提前 60s 刷新，避免边界情况）
        if self._token_cache and time.time() < self._token_cache.expiration - 60:
            logger.debug("[XetAuth] 使用缓存的 token")
            return self._token_cache

        # 获取新 token
        if auth_url:
            self._token_cache = self._request_token_from_url(auth_url)
        else:
            self._token_cache = self._request_token(repo_id, repo_type, revision)

        logger.info(
            f"[XetAuth] 获取新 token, endpoint={self._token_cache.endpoint}, "
            f"expires at {self._token_cache.expiration}"
        )
        return self._token_cache

    def clear_cache(self):
        """清除缓存的 token（用于强制刷新）。"""
        self._token_cache = None

    def _resolve_revision(
        self, repo_id: str, repo_type: str, revision: str
    ) -> Tuple[str, Optional[str]]:
        """将 revision（分支名/tag）解析为 commit hash。

        通过 GET 请求 /api/{type}s/{repo}/revision/ 端点获取 commit hash。

        Args:
            repo_id: 仓库 ID
            repo_type: 仓库类型
            revision: 分支名或 tag

        Returns:
            (commit_hash, auth_url) 元组
            - commit_hash: 40 字符 git commit hash（来自 JSON body 的 "sha" 字段）
            - auth_url: 始终为 None（/revision/ 端点不返回 Link header）
        """
        repo_type_plural = REPO_TYPE_PLURAL_MAP.get(repo_type, f"{repo_type}s")
        url = f"{self.hf_endpoint}/api/{repo_type_plural}/{repo_id}/revision/{revision}"

        logger.debug(f"[XetAuth] 解析 revision: {repo_id}@{revision}")

        headers = {"Authorization": f"Bearer {self.hf_token}"} if self.hf_token else {}
        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        commit_hash = data.get("sha")
        if not commit_hash:
            raise ValueError(f"[XetAuth] /revision/ 响应中无 sha 字段")

        return commit_hash, None

    def _request_token(
        self, repo_id: str, repo_type: str, revision: str
    ) -> XetTokenInfo:
        """通过标准 API 获取 token。

        流程：
        1. HEAD resolve API（不跟随重定向）→ 获取 commit hash + auth URL
        2. 用 auth URL 请求 CAS token

        Args:
            repo_id: 仓库 ID
            repo_type: 仓库类型
            revision: 分支/标签

        Returns:
            XetTokenInfo 实例
        """
        commit_hash, auth_url = self._resolve_revision(repo_id, repo_type, revision)

        if auth_url:
            return self._request_token_from_url(auth_url)

        # 无 auth_url 时：用 commit hash 构造 xet-read-token URL
        repo_type_plural = REPO_TYPE_PLURAL_MAP.get(repo_type, f"{repo_type}s")
        url = f"{self.hf_endpoint}/api/{repo_type_plural}/{repo_id}/xet-read-token/{commit_hash}"

        return self._request_token_from_url(url)

    def _request_token_from_url(self, auth_url: str) -> XetTokenInfo:
        """通过显式 URL 获取 token。

        从 HEAD 响应的 Link header 中提取的 xet-auth URL。

        Args:
            auth_url: xet-auth 的完整 URL

        Returns:
            XetTokenInfo 实例
        """
        headers = {"Authorization": f"Bearer {self.hf_token}"}

        logger.info(f"[XetAuth] 从 URL 请求 token: {auth_url}")

        resp = self.session.get(auth_url, headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()

        # 处理公开仓库兼容性（可能只返回 accessToken）
        access_token = data['accessToken']
        endpoint = data.get('endpoint', 'https://cas-server.xethub.hf.co')
        expiration = data.get('expiration', int(time.time()) + 3600)

        return XetTokenInfo(
            access_token=access_token,
            endpoint=endpoint,
            expiration=int(expiration)
        )

    @staticmethod
    def _parse_link_header(link_header: str) -> Optional[str]:
        """解析 HTTP Link header 提取 xet-auth URL。

        Link header 格式示例：
        <https://huggingface.co/api/.../xet-read-token/abc123>; rel="xet-auth"

        Args:
            link_header: Link header 的原始字符串

        Returns:
            auth_url 或 None
        """
        if not link_header:
            return None

        # 使用正则表达式匹配所有 link 条目
        pattern = r'<([^>]+)>;\s*rel="([^"]+)"'
        matches = re.findall(pattern, link_header)

        for url, rel in matches:
            if rel == 'xet-auth':
                return url

        return None
