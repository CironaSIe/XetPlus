"""HOST 优选模块 - 国内网络加速。

通过 DoH 查询 + 双向测速（直连/代理）选择最优 IP，显著提升国内访问速度。

流程:
1. DoH 查询各域名 IP（多家 DNS 并行，取并集）
2. TCP 双向测速：直连 vs 通过代理
3. HTTP Transfer 测速：真实下载速度
4. 证书指纹验证：防止中间人攻击
5. 按域名选择最优 IP + 是否走代理
6. monkey-patch socket.getaddrinfo 返回优选 IP

缓存（两层）:
- DoH 缓存 (~/.xet/cache/host_doh.json, TTL 24h): 域名→IP列表
- 优选缓存 (~/.xet/cache/host_optimize.json, TTL 1h): 最优IP+速度+完整IP池
"""
import os
import socket
import time
import json
import logging
import ssl
import hashlib
import concurrent.futures
import threading
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Set
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 全局动态 IP 映射（线程安全）
# 用于运行时更新 IP 映射，支持故障转移
_DYNAMIC_IP_MAPPING: Dict[str, str] = {}
_MAPPING_LOCK = threading.Lock()
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


# 可信证书颁发机构白名单
TRUSTED_ISSUERS = {
    "Amazon",              # AWS Certificate Manager
    "Let's Encrypt",       # 免费证书
    "DigiCert Inc",        # 商业 CA
    "Google Trust Services",
    "Cloudflare, Inc.",
}


# HuggingFace 相关域名分组（默认值）
# 注意：如果设置了 HF_ENDPOINT，会在运行时替换 "api" 组中的 huggingface.co
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


def get_effective_host_groups() -> Dict[str, List[str]]:
    """获取实际生效的域名分组（考虑 HF_ENDPOINT）。

    如果用户设置了 HF_ENDPOINT 环境变量（例如 hf-mirror.com），
    则用实际端点替换默认的 huggingface.co。

    Returns:
        实际生效的域名分组
    """
    groups = {k: list(v) for k, v in HOST_GROUPS.items()}  # 深拷贝

    hf_endpoint = os.environ.get("HF_ENDPOINT", "").strip()
    if hf_endpoint:
        # 移除协议前缀
        if "://" in hf_endpoint:
            hf_endpoint = hf_endpoint.split("://", 1)[1]
        # 移除路径
        if "/" in hf_endpoint:
            hf_endpoint = hf_endpoint.split("/", 1)[0]

        # 如果端点不是默认的 huggingface.co，替换它
        if hf_endpoint and hf_endpoint != "huggingface.co":
            groups["api"] = [hf_endpoint]
            logger.info(f"[HostOpt] 检测到 HF_ENDPOINT={hf_endpoint}，将优选此端点")

    return groups


def get_domain_category(domain: str) -> str:
    """获取域名类别。

    Returns:
        "api": API 域名，国内通常被墙
        "data": CDN 数据域名，国内通常可直连
        "cas": CAS 域名，部分可直连
        "unknown": 未知域名
    """
    for category, domains in HOST_GROUPS.items():
        if domain in domains:
            return category
    return "unknown"


def update_ip_mapping(domain: str, new_ip: str) -> None:
    """动态更新 IP 映射（线程安全）。

    用于故障转移时实时切换 IP，无需重新 patch socket.getaddrinfo。

    Args:
        domain: 域名
        new_ip: 新的 IP 地址
    """
    with _MAPPING_LOCK:
        _DYNAMIC_IP_MAPPING[domain] = new_ip
    logger.info(f"[HostOpt] 动态更新映射: {domain} → {new_ip}")


def get_current_ip_mapping(domain: str) -> Optional[str]:
    """获取当前域名的 IP 映射（线程安全）。

    Args:
        domain: 域名

    Returns:
        当前映射的 IP，如果未映射则返回 None
    """
    with _MAPPING_LOCK:
        return _DYNAMIC_IP_MAPPING.get(domain)

# DoH 服务器（地理分散优化，基于实测结果）
# 测试报告: docs/DOH_TEST_ANALYSIS.md
DOH_SERVERS: List[str] = [
    # === 美洲（3个）===
    "https://cloudflare-dns.com/dns-query",     # Cloudflare 主服务
    "https://dns.google/resolve",               # Google
    "https://dns.nextdns.io/dns-query",         # NextDNS

    # === 欧洲（4个）- 关键！提供不同地理位置的 CDN 节点 ===
    "https://doh.dns.sb/dns-query",             # DNS.SB（德国）✓ 实测唯一不同
    "https://doh.applied-privacy.net/query",    # Applied Privacy（德国）
    "https://dns.digitale-gesellschaft.ch/dns-query",  # Digitale Gesellschaft（瑞士）
    "https://doh.li/dns-query",                 # doh.li（瑞士）

    # === 亚洲（3个）===
    "https://dns.alidns.com/resolve",           # 阿里云（可能返回国内节点）
    "https://dns.pub/dns-query",                # 腾讯 DNSPod
    "https://dns.twnic.tw/dns-query",           # 台湾 TWNIC
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
        access_token: Optional[str] = None,
        file_hash: Optional[str] = None,
        cas_endpoint: Optional[str] = None,
    ):
        """初始化 HOST 优选器。

        Args:
            proxy: 代理 URL
            cache_dir: 缓存目录（默认 ~/.xet/cache/）
            dns_servers: 自定义 DoH 服务器列表
            access_token: CAS 认证 token（用于真实带宽测速，无 token 时仅测连通性）
            file_hash: 文件 MerkleHash（用于 CAS reconstruction 端点测速 + 获取 presigned URL）
            cas_endpoint: CAS 服务地址（如 https://cas-server.xethub.hf.co）
        """
        self.proxy = proxy
        self.access_token = access_token
        self.file_hash = file_hash
        self.cas_endpoint = cas_endpoint
        self._quiet = False  # 控制实时输出（由调用方设置）
        if cache_dir:
            cache_path = Path(cache_dir)
            self.cache_path = cache_path / "host_optimize.json"
            self.doh_cache_path = cache_path / "host_doh.json"
        else:
            self.cache_path = self.CACHE_PATH
            self.doh_cache_path = self.DOH_CACHE_PATH

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.doh_servers = dns_servers if dns_servers else DOH_SERVERS

        # 优选结果（最优 IP）
        self.mappings: Dict[str, Dict] = {}

        # 详细测试结果（所有候选 IP）
        self.detailed_results: Dict[str, List[Dict]] = {}

        # 原始 getaddrinfo（用于 fallback）
        self._original_getaddrinfo = socket.getaddrinfo
        self._patched = False

        # DoH 缓存数据
        self._doh_ips: Dict[str, List[str]] = {}

    def set_access_token(self, token: Optional[str]) -> None:
        """设置 CAS 认证 token（可在优选后调用，用于后续重新测速）。

        Args:
            token: CAS access_token（JWT 格式），传 None 表示清除
        """
        self.access_token = token
        if token:
            logger.debug("[HostOpt] 已设置 CAS token，可用于真实带宽测速")

    def set_quiet(self, quiet: bool = True) -> None:
        """设置安静模式（抑制实时测速输出）。

        Args:
            quiet: True 表示不输出实时进度
        """
        self._quiet = quiet

    def _has_valid_cas_jwt(self) -> bool:
        """检查 access_token 是否为有效的 CAS JWT。

        CAS JWT 特征：包含至少两个 '.' (base64url.header.payload.signature)
        区别于 HF_TOKEN（通常不含 '.' 或格式不同）。
        只有真正的 CAS JWT 才能通过 CAS API 认证。
        """
        if not self.access_token:
            return False
        # JWT 格式: xxx.yyy.zzz（三段 base64url 用点分隔）
        return self.access_token.count(".") >= 2

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
        # 获取实际生效的域名分组（考虑 HF_ENDPOINT）
        effective_groups = get_effective_host_groups()

        # 收集所有需要查询的域名
        all_domains = []
        for group, domains in effective_groups.items():
            all_domains.extend(domains)

        all_ips: Dict[str, List[str]] = {}
        use_cache = False

        # 检查缓存是否可用：1) 未强制刷新 2) 缓存存在 3) 缓存的域名集合与当前需要的匹配
        if not force_doh and self._load_doh_cache():
            cached_domains = set(self._doh_ips.keys())
            needed_domains = set(all_domains)

            if cached_domains == needed_domains:
                # 缓存完全匹配，直接使用
                all_ips = self._doh_ips
                use_cache = True
                logger.info(f"[HostOpt] 使用 DoH 缓存: {len(all_ips)} 个域名")
            else:
                # 缓存不匹配（HF_ENDPOINT 可能改变了）
                missing = needed_domains - cached_domains
                extra = cached_domains - needed_domains
                if missing or extra:
                    logger.info(
                        f"[HostOpt] DoH 缓存域名不匹配（需要 {needed_domains}，缓存 {cached_domains}），重新查询"
                    )

        if not use_cache:
            for group, domains in effective_groups.items():
                for domain in domains:
                    ips = self._query_doh_multi(domain)
                    if ips:
                        all_ips[domain] = ips
                        logger.info(f"[HostOpt] {domain}: 获得 {len(ips)} 个 IP")
                    else:
                        logger.debug(f"[HostOpt] {domain}: DoH 查询无结果")

            if all_ips:
                self._save_doh_cache(all_ips)
                # 输出各域名 IP 数量汇总
                _ip_summary = ", ".join(f"{d}({len(ips)})" for d, ips in all_ips.items())
                logger.info(f"[HostOpt] DoH 枚举: {_ip_summary}，共 {sum(len(v) for v in all_ips.values())} 个 IP")

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

        # 5. 证书验证（仅对每个域名 Top N 候选，不全部验证）
        cert_results = {}
        cert_top_n = 3  # 每个域最多验证前 3 个
        if transfer_results:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
            futures = {}
            try:
                for domain, transfers in transfer_results.items():
                    # 只取 Top N 做证书验证（按 speed 降序）
                    sorted_transfers = sorted(transfers, key=lambda x: -x[3])
                    for ip, use_proxy, rtt, speed in sorted_transfers[:cert_top_n]:
                        future = executor.submit(
                            self._validate_ip_with_certificate, ip, domain
                        )
                        futures[future] = (domain, ip)

                try:
                    for future in concurrent.futures.as_completed(futures, timeout=30):
                        domain, ip = futures[future]
                        try:
                            valid, issuer, error = future.result()
                            cert_results[(domain, ip)] = (valid, issuer, error)
                        except Exception as e:
                            logger.debug(f"[HostOpt] 证书验证异常 {ip}: {e}")
                            cert_results[(domain, ip)] = (False, None, str(e))
                except concurrent.futures.TimeoutError:
                    logger.debug("[HostOpt] 证书验证部分超时，使用已完成结果")
            finally:
                executor.shutdown(wait=False)

        # 6. 按域名选最优 + 保存详细结果
        for domain, candidates in results.items():
            transfers = transfer_results.get(domain, [])

            # 构建详细结果列表
            detailed = []

            if transfers:
                # 有 Transfer 结果
                for ip, use_proxy, rtt, speed in transfers:
                    cert_valid, cert_issuer, cert_error = cert_results.get(
                        (domain, ip), (False, None, "未验证")
                    )

                    detailed.append({
                        "ip": ip,
                        "use_proxy": use_proxy,
                        "rtt": rtt,
                        "speed": speed,
                        "status": "ok" if cert_valid else "cert_invalid",
                        "cert_valid": cert_valid,
                        "cert_issuer": cert_issuer,
                        "cert_error": cert_error,
                    })

                # 智能选择策略：根据域名类型 + 证书有效性选择最优 IP
                category = get_domain_category(domain)

                # 过滤出证书有效的 IP
                valid_transfers = [
                    t for t in transfers
                    if cert_results.get((domain, t[0]), (False, None, None))[0]
                ]

                if valid_transfers:
                    # 有证书有效的 IP：根据域名类型选择
                    if category == "api":
                        # API 域名：强制代理（国内被墙）
                        proxy_transfers = [t for t in valid_transfers if t[1]]  # use_proxy=True
                        if proxy_transfers:
                            # 代理速度优先 → RTT
                            proxy_transfers.sort(key=lambda x: (-x[3], x[2]))
                            best_ip, best_proxy, best_rtt, best_speed = proxy_transfers[0]
                        else:
                            # 无代理测速结果，fallback 到速度优先（虽然可能不可用）
                            valid_transfers.sort(key=lambda x: (-x[3], x[2]))
                            best_ip, best_proxy, best_rtt, best_speed = valid_transfers[0]
                            logger.warning(
                                f"[HostOpt] ⚠️ {domain} (API域名): 无代理测速结果，"
                                f"使用直连可能被阻断"
                            )

                    elif category == "data":
                        # DATA 域名：优先直连高带宽（CDN 通常可达）
                        direct_transfers = [t for t in valid_transfers if not t[1]]  # use_proxy=False
                        if direct_transfers and direct_transfers[0][3] > 100_000:  # 带宽 > 100KB/s
                            # 直连速度优先 → RTT
                            direct_transfers.sort(key=lambda x: (-x[3], x[2]))
                            best_ip, best_proxy, best_rtt, best_speed = direct_transfers[0]
                        else:
                            # 直连速度不够或无直连，使用代理
                            valid_transfers.sort(key=lambda x: (-x[3], x[2]))
                            best_ip, best_proxy, best_rtt, best_speed = valid_transfers[0]

                    elif category == "cas":
                        # CAS 域名：延迟优先（speed 字段是 TTFB 毫秒数，越低越好）
                        # 优先直连低延迟
                        direct_transfers = [
                            t for t in valid_transfers if not t[1]]
                        if direct_transfers:
                            # 直连：延迟升序（越低越好）→ RTT 保底
                            direct_transfers.sort(key=lambda x: (x[3], x[2]))
                            best_ip, best_proxy, best_rtt, best_speed = direct_transfers[0]
                        else:
                            # 无直连结果，全部按延迟排序
                            valid_transfers.sort(key=lambda x: (x[3], x[2]))
                            best_ip, best_proxy, best_rtt, best_speed = valid_transfers[0]

                    else:
                        # 未知域名：通用策略
                        if self.proxy:
                            # 有代理：纯速度优先
                            valid_transfers.sort(key=lambda x: (-x[3], x[2]))
                        else:
                            # 无代理：速度优先 → 直连优先 → RTT
                            valid_transfers.sort(key=lambda x: (-x[3], x[1], x[2]))
                        best_ip, best_proxy, best_rtt, best_speed = valid_transfers[0]
                else:
                    # 没有证书有效的 IP：fallback 到原策略（可能是代理连接）
                    logger.warning(
                        f"[HostOpt] ⚠️ {domain}: 所有 IP 证书验证失败，"
                        f"fallback 到未验证的 IP"
                    )
                    if self.proxy:
                        transfers.sort(key=lambda x: (-x[3], x[2]))
                    else:
                        transfers.sort(key=lambda x: (-x[3], x[1], x[2]))
                    best_ip, best_proxy, best_rtt, best_speed = transfers[0]

                # 标记失败的候选（TCP 通但 Transfer 失败）
                transfer_ips = {t[0] for t in transfers}
                for ip, use_proxy, rtt in candidates:
                    if ip not in transfer_ips:
                        detailed.append({
                            "ip": ip,
                            "use_proxy": use_proxy,
                            "rtt": rtt,
                            "speed": 0,
                            "status": "transfer_failed",  # TCP 通但 HTTPS 失败
                        })

                self.mappings[domain] = {
                    "ip": best_ip,
                    "use_proxy": best_proxy,
                    "rtt": best_rtt,
                    "speed": best_speed,
                }
                mode = "代理" if best_proxy else "直连"
                cert_valid, cert_issuer, _ = cert_results.get(
                    (domain, best_ip), (False, None, None)
                )
                cert_info = f", 证书={cert_issuer}" if cert_valid and cert_issuer else ""
                category_label = {
                    "api": "API",
                    "data": "DATA",
                    "cas": "CAS",
                    "unknown": ""
                }.get(category, "")
                domain_info = f" [{category_label}]" if category_label else ""
                logger.info(
                    f"[HostOpt] ✅ {domain}{domain_info} → {best_ip} "
                    f"({mode}, RTT={best_rtt*1000:.0f}ms, {_format_speed(best_speed)}{cert_info})"
                )
            else:
                # 无 Transfer，fallback TCP RTT
                # 所有候选都是 Transfer 失败的
                for ip, use_proxy, rtt in candidates:
                    detailed.append({
                        "ip": ip,
                        "use_proxy": use_proxy,
                        "rtt": rtt,
                        "speed": 0,
                        "status": "transfer_failed",
                    })

                # 当用户指定代理时，Transfer 测速失败意味着直连不可用（TLS 阻断）
                # 此时应强制使用代理
                if self.proxy:
                    # 有代理且 Transfer 失败：优先选择代理测速结果
                    # 按 use_proxy=True 优先 → RTT 升序
                    candidates.sort(key=lambda x: (not x[1], x[2]))
                    best_ip, best_proxy, best_rtt = candidates[0]
                    if not best_proxy:
                        logger.warning(
                            f"[HostOpt] ⚠️ {domain}: Transfer 测速失败，"
                            f"但无代理测速结果，fallback 直连（可能不可用）"
                        )
                else:
                    # 无代理：直连优先 → RTT 升序
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

            # 保存详细结果
            self.detailed_results[domain] = detailed

        # 6. 保存缓存 + 安装 patch
        if self.mappings:
            self._save_cache()
            self._install_patch()
            logger.info(f"[HostOpt] ✅ HOST 优选完成: {len(self.mappings)} 个域名")

            # 给出 CAS 测速提示
            cas_domains = [d for d in self.mappings.keys() if get_domain_category(d) == "cas"]
            if cas_domains:
                cas_speeds = [self.mappings[d].get("speed", 0) for d in cas_domains]
                if any(s <= 1.0 for s in cas_speeds):
                    logger.info(
                        "[HostOpt] 💡 提示: CAS 域名测速仅验证了连接性。"
                        "若需真实速度测试，请配置有效的认证 token。"
                    )

        return self.mappings, False, False

    def _query_doh_multi(self, domain: str) -> List[str]:
        """从多家 DoH 查询域名 IP，取并集。"""
        ips: Set[str] = set()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        try:
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
                logger.debug(f"[HostOpt] DoH 查询部分超时，已获得 {len(ips)} 个 IP")
                # 取消所有未完成的 future，防止线程继续重试并污染后续输出
                for f in futures:
                    if not f.done():
                        f.cancel()
        finally:
            executor.shutdown(wait=False)
        return list(ips)

    def _query_doh_single(self, doh_url: str, domain: str) -> List[str]:
        """单个 DoH 查询。

        重要：当配置了代理时，DoH 查询必须通过代理进行，避免 DNS 污染。
        """
        # 强制通过代理进行 DoH 查询（如果配置了代理）
        # retries=0: 不重试，避免 urllib3 的 WARNING 重试消息污染控制台输出
        session = create_robust_session(
            proxy=self.proxy if self.proxy else "",
            trust_env=not bool(self.proxy),
            retries=0,
        )
        try:
            resp = session.get(
                doh_url,
                params={"name": domain, "type": "A"},
                headers={"accept": "application/dns-json"},
                timeout=(3, 5),
            )
            data = resp.json()
            ips = [
                a["data"]
                for a in data.get("Answer", [])
                if a.get("type") == 1  # A 记录
            ]
            if ips and self.proxy:
                logger.debug(f"[HostOpt] DoH via proxy: {domain} -> {len(ips)} IPs")
            return ips
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
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)
        try:
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

            try:
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
            except concurrent.futures.TimeoutError:
                logger.debug("[HostOpt] TCP 测速部分超时，使用已完成结果")
        finally:
            executor.shutdown(wait=False)
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

        分域名类型使用不同测速策略：
        - CAS 域名：_cas_api_test() 测 reconstruction 端点延迟（TTFB ms）
          同时提取 presigned URL 供 DATA 测速使用
        - DATA 域名：_data_throughput_test() 用 presigned URL 测真实下载带宽
        - API 域名：_http_transfer_test() 用 GET / 测速

        Returns:
            {domain: [(ip, use_proxy, rtt, speed), ...]}
            speed 含义因域名而异：
            - CAS: 延迟毫秒数（越低越好）
            - DATA/API: 下载带宽 bytes/s（越高越好）
        """
        transfer_results: Dict[str, List] = {}

        # 用于从 CAS 响应中提取的 presigned URL（供 DATA 域名测速用）
        sample_data_url: Optional[str] = None

        # 全局超时：整个优选测速不超过 60 秒
        _overall_deadline = time.time() + 60
        _total_tests = 0
        _done_count = 0

        # 实时输出函数（尊重 quiet 模式）
        def _print(msg: str, **kwargs):
            if not self._quiet:
                print(msg, flush=True)

        # ---- 按域名类型分类 ----
        _can_do_cas_api = self.file_hash and self._has_valid_cas_jwt()
        _primary_cas_domain = "cas-server.xethub.hf.co"

        # 所有 CAS 域名（不再限制只有主域名或有 JWT 的才进入）
        cas_domains_all = {
            d: cands for d, cands in results.items()
            if get_domain_category(d) == "cas"
        }
        non_cas_domains = {
            d: cands for d, cands in results.items()
            if d not in cas_domains_all
        }

        # CAS 域名：直接使用 RTT 结果作为"速度"指标（RTT 越低越好）
        # 不再逐个做慢速 HTTP API 测试，只做证书验证
        for domain, candidates in cas_domains_all.items():
            if self.proxy:
                candidates.sort(key=lambda x: (x[1], x[2]))
            else:
                candidates.sort(key=lambda x: (x[1], x[2]))

            _cand_list = []
            for ip, use_proxy, rtt in candidates:
                rtt_ms = rtt * 1000  # 转为毫秒
                _cand_list.append((ip, use_proxy, rtt, rtt_ms))
            transfer_results[domain] = _cand_list
            logger.info(f"[HostOpt] {domain}: {len(candidates)} 个候选（基于 RTT 排序）")

        # 对主 CAS 域名的 Top1 直连候选做 1 次快速 API 调用，获取 presigned URL
        if _can_do_cas_api and _primary_cas_domain in cas_domains_all:
            primary_candidates = cas_domains_all[_primary_cas_domain]
            if primary_candidates:
                best_for_api = None
                for ip, use_proxy, rtt in primary_candidates:
                    if not use_proxy:
                        best_for_api = (ip, use_proxy, rtt)
                        break
                if not best_for_api:
                    best_for_api = primary_candidates[0]

                ip, use_proxy, rtt = best_for_api
                logger.info(f"[HostOpt] 获取 presigned URL: {ip} ({'代理' if use_proxy else '直连'})")
                try:
                    api_result = self._cas_api_test(ip, _primary_cas_domain, use_proxy)
                    if api_result:
                        _latency_ms, data_url = api_result
                        if data_url:
                            sample_data_url = data_url
                            logger.info(f"[HostOpt] Presigned URL 获取成功 (latency={_latency_ms:.0f}ms)")
                        else:
                            logger.info(
                                f"[HostOpt] CAS API 响应成功但无 presigned URL "
                                f"(latency={_latency_ms:.0f}ms，DATA 将用 RTT 选 IP)"
                            )
                    else:
                        logger.debug(f"[HostOpt] Presigned URL 获取失败（将跳过 DATA 测速）")
                except Exception as e:
                    logger.debug(f"[HostOpt] Presigned URL 获取异常: {e}")

        # ---- 非 CAS 域名（API / DATA）：HTTP Transfer 测速 ----
        if non_cas_domains:
            # DATA 域名无 presigned URL 时，直接用 RTT（和 CAS 域名一样）
            # 不走无意义的 _http_transfer_test（只会返回 403/1.0）
            _data_no_url_domains = []
            _domains_need_test = {}

            for domain, candidates in non_cas_domains.items():
                category = get_domain_category(domain)
                if category == "data" and not sample_data_url:
                    # 无 presigned URL：RTT 排序，跳过 HTTP 测速
                    if self.proxy:
                        candidates.sort(key=lambda x: (x[1], x[2]))
                    else:
                        candidates.sort(key=lambda x: (x[1], x[2]))
                    _cand_list = [(ip, use_proxy, rtt, rtt * 1000) for ip, use_proxy, rtt in candidates]
                    transfer_results[domain] = _cand_list
                    logger.info(f"[HostOpt] {domain}: {len(candidates)} 个候选（无 presigned URL，基于 RTT 排序）")
                    _data_no_url_domains.append(domain)
                else:
                    _domains_need_test[domain] = candidates

            # 只对需要真实测速的域名发起 HTTP 测试
            if _domains_need_test:
                _n_other = sum(len(cands) for cands in _domains_need_test.values())
                _total_tests = _n_other

                if _total_tests > 0:
                    logger.info(f"[HostOpt] 测速 {_total_tests} 个候选 IP (API/DATA)...")

                executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)
                transfer_futures: Dict = {}
                try:
                    for domain, candidates in _domains_need_test.items():
                        category = get_domain_category(domain)
                        if self.proxy:
                            if category in ("data", "cas"):
                                candidates.sort(key=lambda x: (x[1], x[2]))
                            else:
                                candidates.sort(key=lambda x: (not x[1], x[2]))
                        else:
                            candidates.sort(key=lambda x: (x[1], x[2]))

                        top = candidates
                        for ip, use_proxy, rtt in top:
                            # API 域名：默认 huggingface.co 被墙，有代理时跳过直连
                            if (category == "api" and self.proxy and not use_proxy
                                    and domain == "huggingface.co"):
                                logger.debug(f"[HostOpt] API {ip}: 跳过直连（已配代理，huggingface.co 被墙）")
                                continue

                            # 有 presigned URL 的 DATA 域名用真实测速
                            if category == "data" and sample_data_url and self.access_token:
                                transfer_futures[
                                    executor.submit(
                                        self._data_throughput_test,
                                        ip, domain, sample_data_url, use_proxy,
                                    )
                                ] = (domain, ip, use_proxy, rtt)
                            else:
                                transfer_futures[
                                    executor.submit(
                                        self._http_transfer_test, ip, domain, use_proxy
                                    )
                                ] = (domain, ip, use_proxy, rtt)

                    remaining_timeout = max(10, _overall_deadline - time.time())
                    try:
                        for future in concurrent.futures.as_completed(
                            transfer_futures, timeout=remaining_timeout
                        ):
                            _done_count += 1
                            domain, ip, use_proxy, rtt = transfer_futures[future]
                            mode_str = "代理" if use_proxy else "直连"
                            category = get_domain_category(domain)
                            try:
                                speed = future.result()
                                if speed is not None:
                                    transfer_results.setdefault(domain, []).append(
                                        (ip, use_proxy, rtt, speed)
                                    )
                                    if category == "data":
                                        _print(
                                            f"   [{_done_count}/{_total_tests}] "
                                            f"DATA {ip} ({mode_str}) {_format_speed(speed)}",
                                            flush=True,
                                        )
                                    elif category == "api":
                                        _print(
                                            f"   [{_done_count}/{_total_tests}] "
                                            f"API {ip} ({mode_str}) {_format_speed(speed)}",
                                            flush=True,
                                        )
                                    else:
                                        _print(
                                            f"   [{_done_count}/{_total_tests}] "
                                            f"{domain.split('.')[0]} {ip} ({mode_str}) {_format_speed(speed)}",
                                            flush=True,
                                        )
                                else:
                                    short_name = domain.split(".")[0]
                                    cat_label = {"api": "API", "data": "DATA"}.get(category, short_name)
                                    _print(
                                        f"   [{_done_count}/{_total_tests}] "
                                        f"{cat_label} {ip} ({mode_str}) 无响应",
                                        flush=True,
                                    )
                            except Exception as e:
                                _print(
                                    f"   [{_done_count}/{_total_tests}] "
                                    f"{ip} ({mode_str}) 异常: {type(e).__name__}",
                                    flush=True,
                                )

                            if time.time() > _overall_deadline:
                                logger.debug("[HostOpt] 达到全局超时，停止等待")
                                break
                    except concurrent.futures.TimeoutError:
                        logger.debug("[HostOpt] Transfer 测速部分超时，使用已完成结果")
                finally:
                    executor.shutdown(wait=False)

        return transfer_results

    def _http_transfer_test(
        self, ip: str, domain: str, use_proxy: bool
    ) -> Optional[float]:
        """HTTP Transfer 测速。

        注意：
        - 对于 API/DATA 域名，使用 GET / 测速
        - 对于 CAS 域名，有 token 时使用 Bearer 认证测速，无 token 时仅验证连通性
        - 有 token 但仍返回 4xx：说明该 IP 的 CDN 节点可能有问题（返回 None）
        - 无 token 时返回 1.0 表示"连接可用但未真实测速"

        Returns:
            下载速度 (bytes/s)，失败返回 None
        """
        test_duration = 1.0
        chunk_size = 16384
        range_max = 262144

        # 初始化变量，确保 finally 块可以访问
        conn = None
        session = None
        needs_close = False

        try:
            start = time.time()

            # 构造认证头（有 token 时对 CAS/DATA 域名启用真实测速）
            category = get_domain_category(domain)
            auth_header = None
            if self.access_token and category in ("cas", "data"):
                auth_header = f"Bearer {self.access_token}"

            if use_proxy and self.proxy:
                # 代理模式
                session = create_robust_session(proxy=self.proxy, retries=0)
                session.verify = False  # 不验证证书，我们稍后会手动验证
                url = f"https://{domain}/"
                headers = {
                    "Range": f"bytes=0-{range_max}",
                    "User-Agent": "xet-dl/host-optimize",
                }
                if auth_header:
                    headers["Authorization"] = auth_header
                resp = session.get(
                    url,
                    timeout=(5, 10),
                    stream=True,
                    headers=headers,
                )
                needs_close = True
            else:
                # 直连模式：直连 IP + SNI=domain
                import http.client as _http_client
                ctx = ssl.create_default_context()
                ctx.check_hostname = False  # 我们会手动验证
                ctx.verify_mode = ssl.CERT_REQUIRED

                # Python 3.13+ 不支持 server_hostname 参数
                # 需要先创建连接，再手动 wrap socket
                conn = _http_client.HTTPConnection(ip, 443, timeout=10)
                conn.connect()

                # 手动进行 TLS 握手，设置 SNI
                conn.sock = ctx.wrap_socket(
                    conn.sock,
                    server_hostname=domain
                )

                headers = {
                    "Host": domain,
                    "User-Agent": "xet-dl/host-optimize",
                    "Range": f"bytes=0-{range_max}",
                }
                if auth_header:
                    headers["Authorization"] = auth_header
                conn.request("GET", "/", headers=headers)
                resp = conn.getresponse()

            # 检查 HTTP 状态码
            status_code = getattr(resp, "status_code", None) or getattr(resp, "status", None)

            # 4xx/5xx 处理
            if status_code and status_code >= 400:
                if category == "cas":
                    if self.access_token:
                        # 有 token 仍返回 4xx：CDN 节点问题或端点不支持根路径测速
                        logger.debug(
                            f"[HostOpt] Transfer 测速 {ip} 返回 {status_code} "
                            f"(已携带 token，该节点可能不支持 / 路径测速)"
                        )
                        # 有 token 时返回 None（不是真连通性问题，是无法测速）
                        return None
                    else:
                        logger.debug(
                            f"[HostOpt] {domain} 返回 {status_code}，TLS 连接成功"
                            "（CAS 需要 token 才能真实测速）"
                        )
                        # 无 token：无法测速（连接可用但需认证）
                        return None
                elif category == "data":
                    if self.access_token:
                        # DATA 域名的 transfer 端点需要 presigned URL，普通 Bearer 不够
                        # 403 = TLS 通了 + 服务正常，只是认证方式不对，算可达
                        logger.debug(
                            f"[HostOpt] Transfer 测速 {ip} 返回 {status_code} "
                            f"(transfer 需要_presigned URL，非 Bearer 认证，IP 可达)"
                        )
                        return 1.0  # IP 可达，返回正数让选择逻辑能选到它
                    else:
                        logger.debug(
                            f"[HostOpt] Transfer 测速 {ip} 返回 {status_code}，但 TLS 连接成功"
                        )
                        # 无 presigned URL：无法测速
                        return None
                else:
                    # API 域名
                    logger.debug(f"[HostOpt] Transfer 测速 {ip} 返回 {status_code}，但 TLS 连接成功")
                    return 1.0

            # 读数据测速
            total_bytes = 0
            deadline = start + test_duration

            if hasattr(resp, "iter_content"):
                # requests.Response
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if time.time() > deadline:
                        break
            else:
                # http.client.HTTPResponse
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if time.time() > deadline:
                        break

            elapsed = time.time() - start
            speed = (total_bytes / elapsed) if elapsed > 0.001 and total_bytes > 0 else None

            return speed

        except ssl.SSLError as e:
            # TLS/证书错误（最常见的墙拦截）
            logger.debug(f"[HostOpt] Transfer 测速 TLS 失败 {ip}: {e}")
            return None
        except (socket.timeout, TimeoutError) as e:
            # 超时
            logger.debug(f"[HostOpt] Transfer 测速超时 {ip}: {e}")
            return None
        except (ConnectionError, OSError) as e:
            # 连接错误（拒绝、重置等）
            logger.debug(f"[HostOpt] Transfer 测速连接失败 {ip}: {e}")
            return None
        except Exception as e:
            # 其他错误
            logger.debug(f"[HostOpt] Transfer 测速未知错误 {ip}: {type(e).__name__}: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if needs_close and session is not None:
                session.close()

    # ========================================================================
    #  CAS API 延迟测速 — 用 reconstruction 端点测 CAS 域名响应速度
    # ========================================================================

    def _cas_api_test(
        self, ip: str, domain: str, use_proxy: bool
    ) -> Optional[Tuple[float, Optional[str]]]:
        """CAS 域名延迟测速：调用 /v2/reconstructions/{file_hash} 测 TTFB。

        与 _http_transfer_test 不同，这里使用真实的 CAS API 端点，
        返回的是 API 响应延迟（ms）而非下载带宽。

        Args:
            ip: IP 地址
            domain: 域名（用于 SNI）
            use_proxy: 是否通过代理

        Returns:
            (latency_ms, data_url) 元组：
            - latency_ms: 首字节延迟（毫秒），失败返回 None
            - data_url: 从响应中提取的第一个 presigned URL（用于 DATA 测速），
                        无 file_hash 或解析失败时为 None
        """
        if not self.access_token or not self.file_hash:
            return None

        # 从 cas_endpoint 提取路径
        if not self.cas_endpoint:
            return None
        parsed = urlparse(self.cas_endpoint)
        cas_path = f"{parsed.path}/v2/reconstructions/{self.file_hash}".replace("//", "/")

        conn = None
        session = None
        needs_close = False
        data_url_sample = None

        try:
            start = time.time()

            headers = {
                "Host": domain,
                "Authorization": f"Bearer {self.access_token}",
                "User-Agent": "xet-dl/cas-latency-test",
                "Accept": "application/json",
            }

            if use_proxy and self.proxy:
                session = create_robust_session(proxy=self.proxy, retries=0)
                session.verify = False
                url = f"https://{domain}{cas_path}"
                resp = session.get(url, headers=headers, timeout=(5, 8))
                needs_close = True
            else:
                import http.client as _http_client
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED

                conn = _http_client.HTTPConnection(ip, 443, timeout=6)
                conn.connect()
                conn.sock = ctx.wrap_socket(conn.sock, server_hostname=domain)
                conn.request("GET", cas_path, headers=headers)
                resp = conn.getresponse()

            status_code = getattr(resp, "status_code", None) or getattr(resp, "status", None)

            # 计算首字节延迟 (TTFB)
            ttfb_ms = (time.time() - start) * 1000

            if status_code and status_code >= 400:
                logger.debug(
                    f"[HostOpt] CAS API 测速 {ip} 返回 {status_code}"
                )
                return None

            # 读取响应体（JSON），用 QueryReconstructionResponse 解析（支持 V1/V2）
            body = b""
            if hasattr(resp, "iter_content"):
                for chunk in resp.iter_content(chunk_size=8192):
                    body += chunk
            else:
                body = resp.read()

            # 解析 JSON 提取第一个 presigned URL（支持 V1 fetch_info + V2 xorbs）
            data_url_sample = None
            if body:
                try:
                    import json as _json
                    from xet.protocol.types import QueryReconstructionResponse

                    recon_data = _json.loads(body)
                    recon = QueryReconstructionResponse.from_dict(recon_data)
                    # 从 fetch_info 中取第一个 URL
                    if recon.fetch_info:
                        first_xorb_key = next(iter(recon.fetch_info), None)
                        if first_xorb_key and recon.fetch_info[first_xorb_key]:
                            data_url_sample = recon.fetch_info[first_xorb_key][0].url
                except (ValueError, KeyError, Exception) as e:
                    logger.debug(f"[HostOpt] 解析 CAS 响应提取 URL 失败: {e}")

            latency = ttfb_ms
            logger.debug(
                f"[HostOpt] CAS API {ip}: {latency:.0f}ms"
                + (f" (presigned URL: {data_url_sample[:60]}...)" if data_url_sample else " (无 presigned URL)")
            )
            return (latency, data_url_sample)

        except ssl.SSLError as e:
            logger.debug(f"[HostOpt] CAS API TLS 失败 {ip}: {e}")
            return None
        except (socket.timeout, TimeoutError):
            return None
        except (ConnectionError, OSError):
            return None
        except Exception as e:
            logger.debug(f"[HostOpt] CAS API 异常 {ip}: {type(e).__name__}: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if needs_close and session is not None:
                session.close()

    # ========================================================================
    #  DATA 吞吐量测速 — 用 presigned URL 做 Range 请求测真实下载带宽
    # ========================================================================

    def _data_throughput_test(
        self, ip: str, domain: str, test_url: str, use_proxy: bool
    ) -> Optional[float]:
        """DATA 域名吞吐量测速：用 presigned URL 的 Range 请求测下载带宽。

        Args:
            ip: IP 地址
            domain: 域名（用于 SNI 和 Host 头）
            test_url: 完整的 presigned URL（含签名参数）
            use_proxy: 是否通过代理

        Returns:
            下载速度 (bytes/s)，失败返回 None
        """
        test_duration = 1.5
        chunk_size = 16384

        # 解析 test_url 提取 path+query
        parsed = urlparse(test_url)
        url_path = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path

        conn = None
        session = None
        needs_close = False

        try:
            start = time.time()
            headers = {
                "Host": domain,
                "User-Agent": "xet-dl/data-throughput-test",
                "Range": "bytes=0-262144",
            }

            if use_proxy and self.proxy:
                session = create_robust_session(proxy=self.proxy, retries=0)
                session.verify = False
                url = f"https://{domain}{url_path}"
                resp = session.get(
                    url, headers=headers, timeout=(5, 15), stream=True
                )
                needs_close = True
            else:
                import http.client as _http_client
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED

                conn = _http_client.HTTPConnection(ip, 443, timeout=10)
                conn.connect()
                conn.sock = ctx.wrap_socket(conn.sock, server_hostname=domain)
                conn.request("GET", url_path, headers=headers)
                resp = conn.getresponse()

            status_code = getattr(resp, "status_code", None) or getattr(resp, "status", None)

            if status_code and status_code >= 400:
                logger.debug(
                    f"[HostOpt] DATA 吞吐量测速 {ip} 返回 {status_code}"
                )
                return None

            # 读数据测速
            total_bytes = 0
            deadline = start + test_duration

            if hasattr(resp, "iter_content"):
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if time.time() > deadline:
                        break
            else:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if time.time() > deadline:
                        break

            elapsed = time.time() - start
            speed = (total_bytes / elapsed) if elapsed > 0.001 and total_bytes > 0 else None

            if speed:
                logger.debug(f"[HostOpt] DATA 吞吐量 {ip}: {_format_speed(speed)}")
            return speed

        except ssl.SSLError:
            return None
        except (socket.timeout, TimeoutError):
            return None
        except (ConnectionError, OSError):
            return None
        except Exception as e:
            logger.debug(f"[HostOpt] DATA 吞吐量异常 {ip}: {type(e).__name__}: {e}")
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if needs_close and session is not None:
                session.close()

    def _get_certificate_finger_print(
        self, ip: str, domain: str, use_proxy: bool
    ) -> Optional[Tuple[str, str, bool]]:
        """获取证书指纹和颁发者信息。

        Args:
            ip: IP 地址
            domain: 域名（用于 SNI）
            use_proxy: 是否通过代理连接

        Returns:
            (fingerprint, issuer, cert_valid) 或 None
            - fingerprint: SHA256 指纹（十六进制）
            - issuer: 证书颁发机构
            - cert_valid: 证书是否匹配域名
        """
        try:
            if use_proxy and self.proxy:
                # 通过代理连接
                parsed = urlparse(self.proxy)
                proxy_host = parsed.hostname
                proxy_port = parsed.port or 8080

                # 连接到代理
                sock = socket.create_connection((proxy_host, proxy_port), timeout=5)

                # 发送 CONNECT 请求
                connect_req = f"CONNECT {ip}:443 HTTP/1.1\r\nHost: {ip}:443\r\n\r\n"
                sock.sendall(connect_req.encode())

                # 读取代理响应
                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    response += chunk

                if b"200" not in response:
                    sock.close()
                    return None

                # TLS 握手
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED  # 需要获取证书，但不检查主机名
                ssl_sock = ctx.wrap_socket(sock, server_hostname=domain)
            else:
                # 直连
                sock = socket.create_connection((ip, 443), timeout=3)
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED  # 需要获取证书，但不检查主机名
                ssl_sock = ctx.wrap_socket(sock, server_hostname=domain)

            # 获取证书
            cert_der = ssl_sock.getpeercert(binary_form=True)
            cert = ssl_sock.getpeercert()

            if not cert or not cert_der:
                ssl_sock.close()
                return None

            # 计算指纹
            fingerprint = hashlib.sha256(cert_der).hexdigest()

            # 获取颁发者（安全处理）
            issuer_org = 'Unknown'
            if 'issuer' in cert and cert['issuer']:
                try:
                    issuer = dict(x[0] for x in cert['issuer'])
                    issuer_org = issuer.get('organizationName', 'Unknown')
                except (ValueError, TypeError, KeyError):
                    pass

            # 验证证书是否匹配域名
            cert_valid = False
            if 'subject' in cert and cert['subject']:
                try:
                    subject = dict(x[0] for x in cert['subject'])
                    cn = subject.get('commonName', '')
                except (ValueError, TypeError, KeyError):
                    cn = ''
            else:
                cn = ''

            if cn == domain or cn == f"*.{'.'.join(domain.split('.')[1:])}":
                cert_valid = True
            elif 'subjectAltName' in cert:
                sans = [x[1] for x in cert['subjectAltName'] if x[0] == 'DNS']
                if domain in sans or any(san.startswith('*.') and domain.endswith(san[1:]) for san in sans):
                    cert_valid = True

            ssl_sock.close()

            return (fingerprint, issuer_org, cert_valid)

        except Exception as e:
            logger.debug(f"[HostOpt] 获取证书失败 {ip}: {e}")
            return None

    def _validate_ip_with_certificate(
        self, ip: str, domain: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """验证 IP 的证书（使用代理连接作为基准）。

        Args:
            ip: 要验证的 IP
            domain: 域名

        Returns:
            (valid, issuer, error_msg)
            - valid: 是否通过验证
            - issuer: 证书颁发者
            - error_msg: 错误信息（如果有）
        """
        if not self.proxy:
            # 没有代理时，无法验证（无基准）
            # 只检查直连证书的有效性
            result = self._get_certificate_finger_print(ip, domain, False)
            if result:
                fingerprint, issuer, cert_valid = result
                if cert_valid and issuer in TRUSTED_ISSUERS:
                    return (True, issuer, None)
                elif not cert_valid:
                    return (False, issuer, "证书不匹配域名")
                else:
                    return (False, issuer, f"颁发者 {issuer} 不在白名单")
            else:
                return (False, None, "无法获取证书")

        # 有代理：获取代理连接的证书指纹作为基准
        proxy_result = self._get_certificate_finger_print(ip, domain, True)
        if not proxy_result:
            return (False, None, "代理连接失败")

        proxy_fingerprint, proxy_issuer, proxy_cert_valid = proxy_result

        if not proxy_cert_valid:
            return (False, proxy_issuer, "代理连接证书不匹配域名")

        if proxy_issuer not in TRUSTED_ISSUERS:
            logger.debug(f"[HostOpt] 证书颁发者 {proxy_issuer} 不在白名单（通过代理验证）")
            # 通过代理验证的证书，即使不在白名单也可以接受
            # 因为代理本身已经验证了证书的有效性

        # 尝试获取直连证书指纹（用于比较）
        direct_result = self._get_certificate_finger_print(ip, domain, False)
        if not direct_result:
            # 直连失败（通常是 GFW 阻断），但代理可用
            # 这是预期行为，代理连接的证书已验证通过
            return (True, proxy_issuer, None)

        direct_fingerprint, direct_issuer, direct_cert_valid = direct_result

        # 比较指纹
        if proxy_fingerprint != direct_fingerprint:
            return (False, direct_issuer, f"证书指纹不匹配（代理: {proxy_issuer}, 直连: {direct_issuer}）")

        if not direct_cert_valid:
            return (False, direct_issuer, "直连证书不匹配域名")

        if direct_issuer not in TRUSTED_ISSUERS:
            return (False, direct_issuer, f"颁发者不在白名单")

        return (True, direct_issuer, None)

    def _install_patch(self) -> None:
        """monkey-patch socket.getaddrinfo（支持动态更新）。

        动态映射优先级：
        1. _DYNAMIC_IP_MAPPING（运行时更新，用于故障转移）
        2. self.mappings（优选结果，静态缓存）
        3. 原始 DNS（未优选域名）
        """
        if self._patched or not self.mappings:
            return

        mappings = self.mappings
        original = self._original_getaddrinfo

        def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            # 1. 优先检查动态映射（故障转移时的实时更新）
            with _MAPPING_LOCK:
                if host in _DYNAMIC_IP_MAPPING:
                    ip = _DYNAMIC_IP_MAPPING[host]
                    logger.debug(f"[HostOpt] DNS 命中（动态）: {host} → {ip}")
                    return [
                        (
                            socket.AF_INET,
                            socket.SOCK_STREAM,
                            6,
                            "",
                            (ip, port if isinstance(port, int) else 0),
                        )
                    ]

            # 2. 检查静态优选结果
            if host in mappings:
                ip = mappings[host]["ip"]
                logger.debug(f"[HostOpt] DNS 命中（静态）: {host} → {ip}")
                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        6,
                        "",
                        (ip, port if isinstance(port, int) else 0),
                    )
                ]

            # 3. 未优选域名，使用原始 DNS
            return original(host, port, family, type, proto, flags)

        socket.getaddrinfo = patched_getaddrinfo
        self._patched = True

        # 初始化动态映射（从静态映射复制）
        with _MAPPING_LOCK:
            for domain, info in mappings.items():
                if domain not in _DYNAMIC_IP_MAPPING:
                    _DYNAMIC_IP_MAPPING[domain] = info["ip"]

        logger.info("[HostOpt] socket.getaddrinfo 已 patch（支持动态更新）")

    def uninstall_patch(self) -> None:
        """恢复原始 getaddrinfo，清理动态映射。"""
        if self._patched:
            socket.getaddrinfo = self._original_getaddrinfo
            self._patched = False

            # 清理动态映射
            with _MAPPING_LOCK:
                _DYNAMIC_IP_MAPPING.clear()

            logger.info("[HostOpt] socket.getaddrinfo 已恢复，动态映射已清理")

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
        """加载优选缓存（支持新旧格式）。"""
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

            # 支持新旧格式
            version = data.get("version", "1.0")
            if version == "2.0" and "domains" in data:
                # 新格式：提取最佳 IP 和完整池
                self.mappings = {}
                self.detailed_results = {}
                for domain, domain_data in data["domains"].items():
                    self.mappings[domain] = {
                        "ip": domain_data["best_ip"],
                        "use_proxy": domain_data["best_use_proxy"],
                        "rtt": domain_data["best_rtt"],
                        "speed": domain_data["best_speed"],
                    }
                    self.detailed_results[domain] = domain_data.get("ips", [])
            else:
                # 旧格式：仅有最佳 IP
                self.mappings = data.get("mappings", {})
                self.detailed_results = {}

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
        """保存优选缓存（包含完整 IP 池）。"""
        try:
            # 构建完整数据结构
            domains_data = {}
            for domain, mapping in self.mappings.items():
                category = get_domain_category(domain)
                detailed = self.detailed_results.get(domain, [])

                domains_data[domain] = {
                    "category": category,
                    "best_ip": mapping["ip"],
                    "best_use_proxy": mapping.get("use_proxy", False),
                    "best_rtt": mapping.get("rtt", 0),
                    "best_speed": mapping.get("speed", 0),
                    "ips": detailed,  # 完整 IP 池
                }

            data = {
                "version": "2.0",
                "timestamp": int(time.time()),
                "proxy_config": self.proxy,
                "domains": domains_data,
            }

            with open(self.cache_path, 'w') as f:
                json.dump(data, f, indent=2)

            total_ips = sum(len(d["ips"]) for d in domains_data.values())
            logger.debug(f"[HostOpt] 优选缓存已保存: {len(domains_data)} 个域名, {total_ips} 个 IP")
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
    access_token: Optional[str] = None,
    file_hash: Optional[str] = None,
    cas_endpoint: Optional[str] = None,
) -> Tuple[requests.Session, Optional[HostOptimizer]]:
    """一步创建带 HOST 优选的 Session。

    便捷函数，封装了完整的优选+Session创建流程。

    Args:
        proxy: 代理 URL（如 http://127.0.0.1:7890）
        optimize_hosts: 是否启用 HOST 优选
        cache_dir: 缓存目录
        refresh_hosts: 强制刷新 HOST 优选缓存
        dns_servers: 自定义 DoH 服务器列表
        access_token: CAS 认证 token（用于真实带宽测速）
        file_hash: 文件 MerkleHash（用于 CAS reconstruction 端点延迟测速）
        cas_endpoint: CAS 服务地址（如 https://cas-server.xethub.hf.co）

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
            access_token=access_token,
            file_hash=file_hash,
            cas_endpoint=cas_endpoint,
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

