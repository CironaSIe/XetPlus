"""IP 池管理器 - 故障转移支持。

负责：
1. 从优选缓存加载完整 IP 池
2. 提供 get_next_ip() 获取下一个可用 IP
3. 标记失败的 IP（mark_failed）
4. IP 池耗尽时触发重新优选
"""
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class IPPoolManager:
    """IP 池管理器 - 支持故障转移和自动重新优选。

    功能：
    - 从缓存加载完整 IP 池（v2.0 格式）
    - 跟踪当前使用的 IP
    - 标记失败的 IP
    - 提供下一个可用 IP
    - IP 池耗尽时触发重新优选
    """

    def __init__(self, cache_file: Path):
        """初始化 IP 池管理器。

        Args:
            cache_file: host_optimize.json 缓存文件路径
        """
        self.cache_file = cache_file
        self.pools: Dict[str, List[Dict]] = {}  # {domain: [ip_info, ...]}
        self.current_ips: Dict[str, str] = {}  # {domain: current_ip}
        self.failed_ips: Dict[str, Set[str]] = defaultdict(set)  # {domain: {failed_ip, ...}}
        self.proxy_config: str = ""

        self._load()

    def _load(self) -> bool:
        """从缓存文件加载 IP 池。

        Returns:
            True: 加载成功
            False: 加载失败（文件不存在或格式错误）
        """
        if not self.cache_file.exists():
            logger.warning(f"[IPPoolManager] 缓存文件不存在: {self.cache_file}")
            return False

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            version = data.get("version", "1.0")

            if version == "2.0" and "domains" in data:
                # v2.0 格式：包含完整 IP 池
                self.proxy_config = data.get("proxy_config", "")

                for domain, domain_data in data["domains"].items():
                    ips = domain_data.get("ips", [])
                    if ips:
                        self.pools[domain] = ips
                        # 初始 IP 为 best_ip
                        best_ip = domain_data.get("best_ip")
                        if best_ip:
                            self.current_ips[domain] = best_ip

                logger.info(
                    f"[IPPoolManager] 加载 v2.0 缓存: {len(self.pools)} 个域名, "
                    f"共 {sum(len(ips) for ips in self.pools.values())} 个 IP"
                )
                return True

            elif version == "1.0":
                # v1.0 格式：只有 best_ip，无 IP 池
                logger.warning(
                    "[IPPoolManager] 缓存为 v1.0 格式（无 IP 池），"
                    "无法支持故障转移"
                )
                return False

            else:
                logger.warning(f"[IPPoolManager] 未知缓存版本: {version}")
                return False

        except Exception as e:
            logger.error(f"[IPPoolManager] 加载缓存失败: {e}")
            return False

    def get_current_ip(self, domain: str) -> Optional[Tuple[str, bool]]:
        """获取当前使用的 IP。

        Args:
            domain: 域名

        Returns:
            (ip, use_proxy): 当前 IP 和是否需要代理
            None: 无可用 IP
        """
        if domain not in self.current_ips:
            # 尝试获取下一个 IP
            return self.get_next_ip(domain)

        current_ip = self.current_ips[domain]
        pool = self.pools.get(domain, [])

        # 查找当前 IP 的信息
        for ip_info in pool:
            if ip_info["ip"] == current_ip:
                return (current_ip, ip_info.get("use_proxy", False))

        # 当前 IP 不在池中，获取下一个
        return self.get_next_ip(domain)

    def get_next_ip(self, domain: str) -> Optional[Tuple[str, bool]]:
        """获取下一个可用 IP。

        过滤已失败的 IP，根据域名类型选择最优 IP。

        Args:
            domain: 域名

        Returns:
            (ip, use_proxy): 下一个 IP 和是否需要代理
            None: IP 池耗尽
        """
        pool = self.pools.get(domain, [])
        if not pool:
            logger.error(f"[IPPoolManager] 域名 {domain} 无 IP 池")
            return None

        failed = self.failed_ips[domain]

        # 过滤已失败的 IP 和证书无效的 IP
        available = [
            ip_info for ip_info in pool
            if ip_info["ip"] not in failed
            and ip_info.get("cert_valid", False)
            and ip_info.get("status") != "cert_invalid"
        ]

        if not available:
            logger.error(
                f"[IPPoolManager] 域名 {domain} 的 IP 池已耗尽 "
                f"(总共 {len(pool)} 个, 失败 {len(failed)} 个)"
            )
            return None

        # 选择策略：速度优先 → RTT
        # 按速度降序、RTT 升序排序
        available.sort(key=lambda x: (-x.get("speed", 0), x.get("rtt", 999)))

        best = available[0]
        new_ip = best["ip"]
        use_proxy = best.get("use_proxy", False)

        # 更新当前 IP
        self.current_ips[domain] = new_ip

        logger.info(
            f"[IPPoolManager] {domain} → {new_ip} "
            f"({'代理' if use_proxy else '直连'}, "
            f"剩余 {len(available)} 个可用 IP)"
        )

        return (new_ip, use_proxy)

    def mark_failed(self, domain: str, ip: str, reason: str = "") -> bool:
        """标记 IP 失败。

        Args:
            domain: 域名
            ip: 失败的 IP
            reason: 失败原因

        Returns:
            True: 标记成功
            False: IP 不在池中
        """
        if domain not in self.pools:
            logger.warning(f"[IPPoolManager] 域名 {domain} 无 IP 池，无法标记失败")
            return False

        # 标记为失败
        self.failed_ips[domain].add(ip)

        # 更新池中的失败信息
        pool = self.pools[domain]
        for ip_info in pool:
            if ip_info["ip"] == ip:
                ip_info["failed_count"] = ip_info.get("failed_count", 0) + 1
                ip_info["last_failure"] = time.time()
                if reason:
                    ip_info["last_failure_reason"] = reason
                break

        reason_str = f": {reason}" if reason else ""
        logger.warning(
            f"[IPPoolManager] 标记 {domain} 的 IP {ip} 为失败{reason_str}"
        )

        # 如果这是当前 IP，清除它
        if self.current_ips.get(domain) == ip:
            self.current_ips.pop(domain, None)

        return True

    def trigger_reoptimization(self, domain: str) -> bool:
        """触发重新优选。

        清空失败标记，重新运行优选流程。

        Args:
            domain: 需要重新优选的域名

        Returns:
            True: 成功触发
            False: 失败（无优选器）
        """
        logger.warning(f"[IPPoolManager] IP 池耗尽，触发 {domain} 的重新优选")

        # 清空失败标记（给 IP 第二次机会）
        if domain in self.failed_ips:
            failed_count = len(self.failed_ips[domain])
            self.failed_ips[domain].clear()
            logger.info(f"[IPPoolManager] 清空 {domain} 的失败标记 ({failed_count} 个)")

        # 注意：实际的重新优选需要调用 HostOptimizer.optimize()
        # 这里只是准备状态，实际调用在下载器中完成
        return True

    def get_pool_stats(self, domain: str) -> Dict:
        """获取 IP 池统计信息。

        Args:
            domain: 域名

        Returns:
            统计信息字典
        """
        pool = self.pools.get(domain, [])
        failed = self.failed_ips.get(domain, set())

        total = len(pool)
        failed_count = len(failed)
        available = total - failed_count

        return {
            "total": total,
            "failed": failed_count,
            "available": available,
            "current_ip": self.current_ips.get(domain),
        }
