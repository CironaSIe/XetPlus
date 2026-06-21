"""HOST 优选模块 - 国内网络加速。

通过 DoH 查询 + 双向测速（直连/代理）选择最优 IP，显著提升国内访问速度。

流程:
1. DoH 查询各域名 IP（多家 DNS 并行，取并集）
2. TCP 双向测速：直连 vs 通过代理
3. HTTP Transfer 测速：真实下载速度
4. 按域名选择最优 IP + 是否走代理
5. monkey-patch socket.getaddrinfo 返回优选 IP

缓存（两层）:
- DoH 缓存 (~/.xet/cache/host_doh.json, TTL 24h): 域名→IP列表
- 优选缓存 (~/.xet/cache/host_optimize.json, TTL 1h): 最优IP+速度
"""
import socket
import time
import json
import logging
import ssl
import concurrent.futures
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Set
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


# HuggingFace 相关域名分组
HOST_GROUPS: Dict[str, List[str]] = {
    "api": [
        "huggingface.co",  # HF API（文件列表/token/resolve）
    ],
    "cas": [
        "cas-server.xethub.hf.co",  # CAS reconstruction
        "cas.xethub.hf.co",  # CAS 备用
        "us.aws.cas.xethub.hf.co",  # US AWS CAS
        "eu.cas.xethub.hf.co",  # EU CAS
    ],
    "data": [
        "transfer.xethub.hf.co",  # xorb 数据下载（流量最大）
    ],
}

# DoH 服务器（国内优先 + 海外备选）
DOH_SERVERS: List[str] = [
    "https://dns.alidns.com/resolve",           # 阿里云 (国内直连)
    "https://223.5.5.5/dns-query",              # 阿里云备选
    "https://cloudflare-dns.com/dns-query",      # Cloudflare
    "https://1.1.1.1/dns-query",                 # Cloudflare IP
    "https://dns.google/resolve",                # Google
    "https://dns.quad9.net/dns-query",            # Quad9
]


def _format_speed(bps: float) -> str:
    """格式化速度为人类可读格式。"""
    if bps >= 1024 * 1024:
        return f"{bps / (1024*1024):.1f}MB/s"
    elif bps >= 1024:
        return f"{bps / 1024:.1f}KB/s"
    else:
        return f"{bps:.0f}B/s"


def create_robust_session(
    proxy: str = "",
    trust_env: bool = False,
    retries: int = 3,
) -> requests.Session:
    """创建带重试的 Session。"""
    session = requests.Session()
    session.trust_env = trust_env

    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    retry_strategy = Retry(
        total=retries,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


class HostOptimizer:
    """HOST 优选管理器。

    执行 DoH 查询 + 测速，选择最优 IP 并 monkey-patch socket.getaddrinfo。

    Attributes:
        proxy: 代理 URL（如 http://127.0.0.1:7890）
        mappings: 优选结果 {domain: {"ip": "1.2.3.4", "use_proxy": False, "rtt": 0.1}}
    """

    CACHE_PATH = Path.home() / ".xet" / "cache" / "host_optimize.json"
    CACHE_TTL = 3600  # 优选缓存 1 小时

    DOH_CACHE_PATH = Path.home() / ".xet" / "cache" / "host_doh.json"
    DOH_CACHE_TTL = 86400  # DoH 缓存 24 小时

    def __init__(
        self,
        proxy: str = "",
        cache_dir: Optional[str] = None,
        dns_servers: Optional[List[str]] = None,
    ):
        """初始化 HOST 优选器。

        Args:
            proxy: 代理 URL
            cache_dir: 缓存目录（默认 ~/.xet/cache/）
            dns_servers: 自定义 DoH 服务器列表
        """
        self.proxy = proxy
        if cache_dir:
            cache_path = Path(cache_dir)
            self.cache_path = cache_path / "host_optimize.json"
            self.doh_cache_path = cache_path / "host_doh.json"
        else:
            self.cache_path = self.CACHE_PATH
            self.doh_cache_path = self.DOH_CACHE_PATH

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.doh_servers = dns_servers if dns_servers else DOH_SERVERS

        # 优选结果
        self.mappings: Dict[str, Dict] = {}

        # 原始 getaddrinfo（用于 fallback）
        self._original_getaddrinfo = socket.getaddrinfo
        self._patched = False

        # DoH 缓存数据
        self._doh_ips: Dict[str, List[str]] = {}

    def optimize(
        self,
        force_refresh: bool = False,
        force_doh: bool = False,
    ) -> Tuple[Dict[str, Dict], bool, bool]:
        """执行 HOST 优选。

        Args:
            force_refresh: 强制刷新全部（重新测速）
            force_doh: 仅强制刷新 DoH（重新查 IP）

        Returns:
            (mappings, used_opt_cache, used_doh_cache)
        """
        # 1. 尝试加载优选缓存
        if not force_refresh and self._load_cache():
            logger.info(f"[HostOpt] 使用优选缓存: {len(self.mappings)} 个域名")
            self._install_patch()
            return self.mappings, True, False

        logger.info("[HostOpt] 开始 HOST 优选...")

        # 2. DoH 查询（带缓存）
        all_ips: Dict[str, List[str]] = {}
        if not force_doh and self._load_doh_cache():
            all_ips = self._doh_ips
            logger.info(f"[HostOpt] 使用 DoH 缓存: {len(all_ips)} 个域名")
        else:
            for group, domains in HOST_GROUPS.items():
                for domain in domains:
                    ips = self._query_doh_multi(domain)
                    if ips:
                        all_ips[domain] = ips
                        logger.info(f"[HostOpt] {domain}: 获得 {len(ips)} 个 IP")
                    else:
                        logger.warning(f"[HostOpt] {domain}: DoH 查询无结果")

            if all_ips:
                self._save_doh_cache(all_ips)

        if not all_ips:
            logger.warning("[HostOpt] DoH 查询失败，HOST 优选未生效")
            return self.mappings, False, False

        # 3. TCP 双向测速
        results = self._speed_test_all(all_ips)

        if not results:
            logger.warning("[HostOpt] 所有 IP 均不可达")
            return self.mappings, False, bool(all_ips)

        # 4. HTTP Transfer 测速（对 Top 候选）
        transfer_results = self._transfer_test_top(results)

        # 5. 按域名选最优
        for domain, candidates in results.items():
            transfers = transfer_results.get(domain, [])
            if transfers:
                # 有 Transfer 结果：按速度降序 → 直连优先 → RTT 升序
                transfers.sort(key=lambda x: (-x[3], x[1], x[2]))
                best_ip, best_proxy, best_rtt, best_speed = transfers[0]
                self.mappings[domain] = {
                    "ip": best_ip,
                    "use_proxy": best_proxy,
                    "rtt": best_rtt,
                    "speed": best_speed,
                }
                mode = "代理" if best_proxy else "直连"
                logger.info(
                    f"[HostOpt] ✅ {domain} → {best_ip} "
                    f"({mode}, RTT={best_rtt*1000:.0f}ms, {_format_speed(best_speed)})"
                )
            else:
                # 无 Transfer，fallback TCP RTT
                candidates.sort(key=lambda x: (x[1], x[2]))
                best_ip, best_proxy, best_rtt = candidates[0]
                self.mappings[domain] = {
                    "ip": best_ip,
                    "use_proxy": best_proxy,
                    "rtt": best_rtt,
                    "speed": 0,
                }
                mode = "代理" if best_proxy else "直连"
                logger.info(
                    f"[HostOpt] ⚠️ {domain} → {best_ip} "
                    f"({mode}, RTT={best_rtt*1000:.0f}ms, Transfer=N/A)"
                )

        # 6. 保存缓存 + 安装 patch
        if self.mappings:
            self._save_cache()
            self._install_patch()
            logger.info(f"[HostOpt] ✅ HOST 优选完成: {len(self.mappings)} 个域名")

        return self.mappings, False, False

    def _query_doh_multi(self, domain: str) -> List[str]:
        """从多家 DoH 查询域名 IP，取并集。"""
        ips: Set[str] = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._query_doh_single, url, domain): url
                for url in self.doh_servers
            }
            try:
                for future in concurrent.futures.as_completed(futures, timeout=8):
                    try:
                        result = future.result(timeout=1)
                        ips.update(result)
                    except Exception as e:
                        logger.debug(f"[HostOpt] DoH 查询失败: {e}")
            except concurrent.futures.TimeoutError:
                # 部分 DoH 服务器超时，但可能已经有结果
                logger.debug(f"[HostOpt] DoH 查询部分超时，已获得 {len(ips)} 个 IP")
                # 取消未完成的 futures
                for future in futures:
                    if not future.done():
                        future.cancel()
        return list(ips)

    def _query_doh_single(self, doh_url: str, domain: str) -> List[str]:
        """单个 DoH 查询。"""
        session = create_robust_session(
            proxy=self.proxy if self.proxy else "",
            trust_env=not bool(self.proxy),
            retries=1,
        )
        try:
            resp = session.get(
                doh_url,
                params={"name": domain, "type": "A"},
                headers={"accept": "application/dns-json"},
                timeout=(3, 5),
            )
            data = resp.json()
            return [
                a["data"]
                for a in data.get("Answer", [])
                if a.get("type") == 1  # A 记录
            ]
        finally:
            session.close()

    def _speed_test_all(
        self, all_ips: Dict[str, List[str]]
    ) -> Dict[str, List[Tuple[str, bool, float]]]:
        """对所有 IP 并行测速。

        Returns:
            {domain: [(ip, use_proxy, rtt), ...]}
        """
        results: Dict[str, List] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures: Dict = {}
            for domain, ips in all_ips.items():
                for ip in ips:
                    # 直连测速
                    futures[
                        executor.submit(self._tcp_rtt, ip, 443, False)
                    ] = (domain, ip, False)
                    # 代理测速（如果配置）
                    if self.proxy:
                        futures[
                            executor.submit(self._tcp_rtt, ip, 443, True)
                        ] = (domain, ip, True)

            for future in concurrent.futures.as_completed(futures, timeout=10):
                domain, ip, use_proxy = futures[future]
                try:
                    rtt = future.result()
                    if rtt is not None:
                        results.setdefault(domain, []).append(
                            (ip, use_proxy, rtt)
                        )
                except Exception as e:
                    logger.debug(f"[HostOpt] 测速异常 {ip}: {e}")
        return results

    def _tcp_rtt(self, ip: str, port: int, use_proxy: bool) -> Optional[float]:
        """TCP 连接测速。

        Returns:
            RTT（秒），失败返回 None
        """
        if use_proxy and self.proxy:
            # 代理测速：测代理服务器本身
            parsed = urlparse(self.proxy)
            target_host = parsed.hostname
            target_port = parsed.port or 8080
            if not target_host:
                return None
        else:
            # 直连测速
            target_host, target_port = ip, port

        try:
            start = time.time()
            sock = socket.create_connection(
                (target_host, target_port), timeout=3
            )
            rtt = time.time() - start
            sock.close()
            return rtt
        except (socket.timeout, OSError):
            return None

    def _transfer_test_top(
        self, results: Dict[str, List[Tuple[str, bool, float]]]
    ) -> Dict[str, List[Tuple[str, bool, float, float]]]:
        """HTTP Transfer 测速（对每个域名的 Top 候选）。

        Returns:
            {domain: [(ip, use_proxy, rtt, speed), ...]}
        """
        MAX_CANDIDATES = 3
        transfer_results: Dict[str, List] = {}
        transfer_futures: Dict = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for domain, candidates in results.items():
                # 按 RTT 排序，取前 N 个
                candidates.sort(key=lambda x: (x[1], x[2]))
                top = candidates[:MAX_CANDIDATES]
                for ip, use_proxy, rtt in top:
                    transfer_futures[
                        executor.submit(
                            self._http_transfer_test, ip, domain, use_proxy
                        )
                    ] = (domain, ip, use_proxy, rtt)

            for future in concurrent.futures.as_completed(
                transfer_futures, timeout=30
            ):
                domain, ip, use_proxy, rtt = transfer_futures[future]
                try:
                    speed = future.result()
                    if speed is not None:
                        transfer_results.setdefault(domain, []).append(
                            (ip, use_proxy, rtt, speed)
                        )
                except Exception as e:
                    logger.debug(f"[HostOpt] Transfer 测速异常 {ip}: {e}")

        return transfer_results

    def _http_transfer_test(
        self, ip: str, domain: str, use_proxy: bool
    ) -> Optional[float]:
        """HTTP Transfer 测速。

        Returns:
            下载速度 (bytes/s)，失败返回 None
        """
        TEST_DURATION = 1.0
        CHUNK_SIZE = 16384
        RANGE_MAX = 262144

        try:
            start = time.time()

            if use_proxy and self.proxy:
                # 代理模式
                session = create_robust_session(proxy=self.proxy, retries=0)
                url = f"https://{domain}/"
                resp = session.get(
                    url,
                    timeout=(5, 10),
                    stream=True,
                    headers={
                        "Range": f"bytes=0-{RANGE_MAX}",
                        "User-Agent": "xet-dl/host-optimize",
                    },
                )
                needs_close = True
                conn = None
            else:
                # 直连模式：直连 IP + SNI=domain
                import http.client as _http_client
                ctx = ssl.create_default_context()
                conn = _http_client.HTTPSConnection(
                    ip, 443,
                    context=ctx,
                    server_hostname=domain,
                    timeout=10,
                )
                conn.request(
                    "GET", "/",
                    headers={
                        "Host": domain,
                        "User-Agent": "xet-dl/host-optimize",
                        "Range": f"bytes=0-{RANGE_MAX}",
                    },
                )
                resp = conn.getresponse()
                needs_close = False
                session = None

            # 读数据测速
            total_bytes = 0
            deadline = start + TEST_DURATION

            if hasattr(resp, "iter_content"):
                # requests.Response
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if time.time() > deadline:
                        break
            else:
                # http.client.HTTPResponse
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if time.time() > deadline:
                        break

            elapsed = time.time() - start
            speed = (total_bytes / elapsed) if elapsed > 0.001 and total_bytes > 0 else None

            return speed

        except Exception as e:
            logger.debug(f"[HostOpt] Transfer 测速失败 {ip}: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if needs_close and session is not None:
                session.close()

    def _install_patch(self) -> None:
        """monkey-patch socket.getaddrinfo。"""
        if self._patched or not self.mappings:
            return

        mappings = self.mappings
        original = self._original_getaddrinfo

        def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            # 命中优选域名
            if host in mappings:
                ip = mappings[host]["ip"]
                logger.debug(f"[HostOpt] DNS 命中: {host} → {ip}")
                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        6,
                        "",
                        (ip, port if isinstance(port, int) else 0),
                    )
                ]
            # 未优选域名，使用原始 DNS
            return original(host, port, family, type, proto, flags)

        socket.getaddrinfo = patched_getaddrinfo
        self._patched = True
        logger.info("[HostOpt] socket.getaddrinfo 已 patch")

    def uninstall_patch(self) -> None:
        """恢复原始 getaddrinfo。"""
        if self._patched:
            socket.getaddrinfo = self._original_getaddrinfo
            self._patched = False
            logger.info("[HostOpt] socket.getaddrinfo 已恢复")

    def get_proxy_for_domain(self, domain: str) -> Optional[str]:
        """按域名决定是否走代理。

        - 直连可达的域名返回 None（不走代理）
        - 需要代理的域名返回 proxy URL
        - 未优选的域名 fallback 到全局 proxy 设置

        特殊情况：如果优选结果要求代理但当前无代理配置，
        仍返回 None 尝试直连（预期可能失败，但让连接层处理）。

        Args:
            domain: 域名（不含端口和路径）

        Returns:
            proxy URL 或 None
        """
        if domain not in self.mappings:
            # 未优选的域名，使用全局代理设置
            return self.proxy if self.proxy else None

        # 已优选的域名，根据测速结果决定
        use_proxy = self.mappings[domain].get("use_proxy", True)

        if use_proxy:
            if self.proxy:
                return self.proxy
            else:
                # 优选结果要求代理但当前无代理：尝试直连（可能失败）
                logger.debug(
                    f"[HostOpt] {domain} 优选结果要求代理，但当前无代理配置，将尝试直连（可能超时）"
                )
                return None
        else:
            return None

    def _load_cache(self) -> bool:
        """加载优选缓存。"""
        if not self.cache_path.exists():
            return False

        try:
            with open(self.cache_path, 'r') as f:
                data = json.load(f)

            timestamp = data.get("timestamp", 0)
            if time.time() - timestamp > self.CACHE_TTL:
                logger.debug("[HostOpt] 优选缓存已过期")
                return False

            # 检查代理配置是否变化
            cached_proxy = data.get("proxy_config", "")
            if cached_proxy != self.proxy:
                logger.info(
                    f"[HostOpt] 代理配置变化（缓存: {cached_proxy or '无'} → 当前: {self.proxy or '无'}），清除缓存"
                )
                return False

            self.mappings = data.get("mappings", {})

            # 检查代理依赖：如果某些域名需要代理但当前没有代理配置
            if not self.proxy:
                proxy_required_domains = [
                    domain for domain, info in self.mappings.items()
                    if info.get("use_proxy", False)
                ]
                if proxy_required_domains:
                    logger.warning(
                        f"[HostOpt] 警告: 以下域名的优选结果要求使用代理，但当前未配置代理:\n"
                        f"  {', '.join(proxy_required_domains)}\n"
                        f"  这些域名的访问可能会失败。建议:\n"
                        f"  1. 配置代理: --proxy http://127.0.0.1:xxxx\n"
                        f"  2. 或刷新优选: --optimize-hosts (无代理环境下重新优选)"
                    )

            return bool(self.mappings)

        except Exception as e:
            logger.warning(f"[HostOpt] 加载优选缓存失败: {e}")
            return False

    def _save_cache(self) -> None:
        """保存优选缓存。"""
        try:
            data = {
                "timestamp": time.time(),
                "proxy_config": self.proxy,  # 记录代理配置
                "mappings": self.mappings,
            }
            with open(self.cache_path, 'w') as f:
                json.dump(
                    {
                        "timestamp": int(time.time()),
                        "mappings": self.mappings,
                    },
                    f,
                    indent=2,
                )
            logger.debug(f"[HostOpt] 优选缓存已保存: {self.cache_path}")
        except Exception as e:
            logger.warning(f"[HostOpt] 保存优选缓存失败: {e}")

    def _load_doh_cache(self) -> bool:
        """加载 DoH 缓存。"""
        if not self.doh_cache_path.exists():
            return False

        try:
            with open(self.doh_cache_path, 'r') as f:
                data = json.load(f)

            timestamp = data.get("timestamp", 0)
            if time.time() - timestamp > self.DOH_CACHE_TTL:
                logger.debug("[HostOpt] DoH 缓存已过期")
                return False

            self._doh_ips = data.get("ips", {})
            return bool(self._doh_ips)

        except Exception as e:
            logger.warning(f"[HostOpt] 加载 DoH 缓存失败: {e}")
            return False

    def _save_doh_cache(self, ips: Dict[str, List[str]]) -> None:
        """保存 DoH 缓存。"""
        try:
            with open(self.doh_cache_path, 'w') as f:
                json.dump(
                    {
                        "timestamp": int(time.time()),
                        "ips": ips,
                    },
                    f,
                    indent=2,
                )
            logger.debug(f"[HostOpt] DoH 缓存已保存: {self.doh_cache_path}")
        except Exception as e:
            logger.warning(f"[HostOpt] 保存 DoH 缓存失败: {e}")


# ============================================================================
# DomainAwareSession - 按域名动态路由代理
# ============================================================================

class DomainAwareSession(requests.Session):
    """按域名决定是否走代理的 Session。

    核心功能：
    - 根据 HostOptimizer 的测速结果动态选择代理
    - 优选的直连域名不走代理（速度快）
    - 需要代理的域名走代理（访问受限资源）
    - 未优选的域名使用默认代理设置

    用法：
        optimizer = HostOptimizer(proxy="http://127.0.0.1:7890")
        optimizer.optimize()
        session = DomainAwareSession(host_optimizer=optimizer, default_proxy=proxy)

        # 挂载 HTTPAdapter（重要！）
        adapter = HTTPAdapter(max_retries=Retry(...))
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # 正常使用
        session.get("https://huggingface.co/api/...")  # 自动走代理
        session.get("https://transfer.xethub.hf.co/...")  # 自动直连
    """

    def __init__(
        self,
        host_optimizer: Optional[HostOptimizer] = None,
        default_proxy: str = "",
        **kwargs,
    ):
        """初始化 DomainAwareSession。

        Args:
            host_optimizer: HOST 优选器（启用 --optimize-hosts 时传入）
            default_proxy: 默认代理（未启用 HOST 优选时使用）
            **kwargs: 传递给 requests.Session 的其他参数
        """
        super().__init__(**kwargs)
        self.host_optimizer = host_optimizer
        self.default_proxy = default_proxy
        self.trust_env = False  # 不读取系统代理环境变量

    def request(self, method, url, **kwargs):
        """覆盖 request 方法，按域名动态设置代理。

        Args:
            method: HTTP 方法
            url: 请求 URL
            **kwargs: 其他请求参数

        Returns:
            requests.Response
        """
        if self.host_optimizer:
            # 提取域名
            from urllib.parse import urlparse
            domain = urlparse(url).hostname

            # 按域名决定代理
            proxy = self.host_optimizer.get_proxy_for_domain(domain)
            if proxy:
                # 需要走代理
                kwargs.setdefault(
                    "proxies", {"http": proxy, "https": proxy}
                )
            else:
                # 直连（强制不走代理，覆盖 session.proxies）
                kwargs["proxies"] = {"http": "", "https": ""}
        elif self.default_proxy:
            # 未启用优选，使用默认代理
            kwargs.setdefault(
                "proxies",
                {"http": self.default_proxy, "https": self.default_proxy},
            )

        return super().request(method, url, **kwargs)


# ============================================================================
# 便捷工厂函数 - 一步创建完整配置的 Session
# ============================================================================

def create_optimized_session(
    proxy: str = "",
    optimize_hosts: bool = False,
    cache_dir: Optional[str] = None,
    refresh_hosts: bool = False,
    dns_servers: Optional[List[str]] = None,
) -> Tuple[requests.Session, Optional[HostOptimizer]]:
    """一步创建带 HOST 优选的 Session。

    便捷函数，封装了完整的优选+Session创建流程。

    Args:
        proxy: 代理 URL（如 http://127.0.0.1:7890）
        optimize_hosts: 是否启用 HOST 优选
        cache_dir: 缓存目录
        refresh_hosts: 强制刷新 HOST 优选缓存
        dns_servers: 自定义 DoH 服务器列表

    Returns:
        (session, host_optimizer) 元组
        - session: 配置好的 Session（DomainAwareSession 或普通 Session）
        - host_optimizer: HostOptimizer 实例，未启用时为 None

    示例：
        # 启用 IP 优选
        session, optimizer = create_optimized_session(
            proxy="http://127.0.0.1:7890",
            optimize_hosts=True,
        )

        # 未启用 IP 优选
        session, _ = create_optimized_session(
            proxy="http://127.0.0.1:7890",
            optimize_hosts=False,
        )
    """
    host_optimizer: Optional[HostOptimizer] = None

    # 1. 执行 HOST 优选
    if optimize_hosts:
        host_optimizer = HostOptimizer(
            proxy=proxy,
            cache_dir=cache_dir,
            dns_servers=dns_servers,
        )
        host_optimizer.optimize(force_refresh=refresh_hosts)
        logger.info("[Session] HOST 优选已启用")

    # 2. 创建 Session
    if host_optimizer:
        # 使用 DomainAwareSession（按域名动态代理）
        session = DomainAwareSession(
            host_optimizer=host_optimizer,
            default_proxy=proxy,
        )
    else:
        # 使用普通 Session
        session = create_robust_session(proxy=proxy, trust_env=False)

    # 3. 挂载 HTTPAdapter（DomainAwareSession 需要手动挂载）
    if host_optimizer:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD", "POST", "PUT", "DELETE"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

    return session, host_optimizer


def check_hf_endpoint_xet_support(
    endpoint: str,
    test_repo: str = "mykor/granite-embedding-97m-multilingual-r2-GGUF",
    test_file: str = "granite-embedding-97M-multilingual-r2-Q4_K_M.gguf",
    test_commit: str = "45ce642d3fab2033d167ec09641a159010f7d9d9",
    proxy: str = "",
    timeout: int = 10,
) -> Dict[str, any]:
    """检测 HF 端点是否支持 XET 协议。

    测试项目：
    1. 端点可达性（HEAD 请求）
    2. XET 特征头存在（x-linked-etag, x-linked-size, x-repo-commit）
    3. XET Link 头存在（rel="xet-auth", rel="xet-reconstruction-info"）

    Args:
        endpoint: HF 端点 URL（如 https://hf-mirror.com）
        test_repo: 测试用仓库
        test_file: 测试用文件
        test_commit: 测试用 commit hash
        proxy: 代理地址（可选）
        timeout: 超时时间（秒）

    Returns:
        {
            "reachable": bool,           # 端点是否可达
            "supports_xet": bool,        # 是否支持 XET
            "has_xet_headers": bool,     # 是否有 XET 特征头
            "has_link_headers": bool,    # 是否有 Link 头
            "response_time": float,      # 响应时间（秒）
            "status_code": int,          # HTTP 状态码
            "error": str,                # 错误信息（如有）
            "xet_headers": dict,         # XET 相关头（如有）
        }
    """
    result = {
        "reachable": False,
        "supports_xet": False,
        "has_xet_headers": False,
        "has_link_headers": False,
        "response_time": 0.0,
        "status_code": 0,
        "error": None,
        "xet_headers": {},
    }

    # 构造测试 URL
    test_url = f"{endpoint.rstrip('/')}/{test_repo}/resolve/{test_commit}/{test_file}"

    try:
        session = create_robust_session(proxy=proxy, trust_env=False, retries=1)

        start = time.time()
        resp = session.head(test_url, allow_redirects=False, timeout=timeout)
        elapsed = time.time() - start

        result["response_time"] = elapsed
        result["status_code"] = resp.status_code

        # 检查可达性（302/301 是正常的 XET 重定向）
        if resp.status_code in (200, 301, 302, 307, 308):
            result["reachable"] = True

            # 检查 XET 特征头
            xet_etag = resp.headers.get("x-linked-etag") or resp.headers.get("X-Linked-ETag")
            xet_size = resp.headers.get("x-linked-size") or resp.headers.get("X-Linked-Size")
            xet_commit = resp.headers.get("x-repo-commit") or resp.headers.get("X-Repo-Commit")

            if xet_etag or xet_size:
                result["has_xet_headers"] = True
                result["xet_headers"] = {
                    "x-linked-etag": xet_etag,
                    "x-linked-size": xet_size,
                    "x-repo-commit": xet_commit,
                }

            # 检查 Link 头
            link_header = resp.headers.get("Link", "")
            if 'rel="xet-auth"' in link_header or 'rel="xet-reconstruction-info"' in link_header:
                result["has_link_headers"] = True

            # 判断是否完全支持 XET
            result["supports_xet"] = result["has_xet_headers"] and result["has_link_headers"]
        else:
            result["error"] = f"HTTP {resp.status_code}"

    except requests.exceptions.Timeout:
        result["error"] = "Connection timeout"
    except requests.exceptions.ConnectionError as e:
        result["error"] = f"Connection error: {str(e)[:50]}"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)[:50]}"

    return result

