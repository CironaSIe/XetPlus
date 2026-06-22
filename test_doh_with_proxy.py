#!/usr/bin/env python3
"""通过代理查询 DoH 并测试所有 IP"""

import socket
import ssl
import json
import requests
import concurrent.futures
from typing import Dict, List, Set
from collections import defaultdict

# 合法的证书颁发机构（白名单）
TRUSTED_ISSUERS = {
    "Amazon",              # AWS Certificate Manager
    "Let's Encrypt",       # 免费证书
    "DigiCert Inc",        # 商业 CA
    "Google Trust Services",
    "Cloudflare, Inc.",
}

# 测试域名
TEST_DOMAINS = [
    "huggingface.co",
    "cas-server.xethub.hf.co",
    "cas.xethub.hf.co",
    "transfer.xethub.hf.co",
]

# DoH 服务器
DOH_SERVERS = [
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
    "https://1.1.1.1/dns-query",
]


def query_doh_via_proxy(domain: str, doh_server: str, proxy: str) -> List[str]:
    """通过代理查询 DoH"""
    ips = []
    try:
        if "dns.google" in doh_server:
            # Google DoH (JSON API)
            url = f"{doh_server}?name={domain}&type=A"
            resp = requests.get(url, proxies={"https": proxy}, timeout=10)
            data = resp.json()
            if data.get("Answer"):
                ips = [ans["data"] for ans in data["Answer"] if ans.get("type") == 1]
        else:
            # Cloudflare DoH (RFC 8484)
            import dns.message
            import dns.query
            # 这里简化处理，直接用 Google 格式
            pass
    except Exception as e:
        print(f"  ❌ {doh_server}: {e}")

    return ips


def test_ip_with_cert_check(ip: str, domain: str, use_proxy: bool, proxy: str = "") -> Dict:
    """测试 IP 并验证证书颁发机构"""
    result = {
        "ip": ip,
        "domain": domain,
        "use_proxy": use_proxy,
        "tcp": False,
        "tls": False,
        "cert_valid": False,
        "cert_cn": "",
        "issuer_org": "",
        "trusted_issuer": False,
        "error": "",
    }

    try:
        if use_proxy and proxy:
            # 通过代理连接
            proxy_host, proxy_port = proxy.replace("http://", "").split(":")
            proxy_port = int(proxy_port)

            # 连接代理
            sock = socket.create_connection((proxy_host, proxy_port), timeout=5)
            result["tcp"] = True

            # CONNECT 到目标 IP
            connect_req = f"CONNECT {ip}:443 HTTP/1.1\r\nHost: {ip}:443\r\n\r\n"
            sock.sendall(connect_req.encode())

            # 读取代理响应
            response = b""
            while b"\r\n\r\n" not in response:
                response += sock.recv(1024)

            if b"200" not in response:
                result["error"] = "Proxy CONNECT failed"
                sock.close()
                return result

            # TLS 握手
            ctx = ssl.create_default_context()
            ssl_sock = ctx.wrap_socket(sock, server_hostname=domain)
        else:
            # 直连
            sock = socket.create_connection((ip, 443), timeout=3)
            result["tcp"] = True

            ctx = ssl.create_default_context()
            ssl_sock = ctx.wrap_socket(sock, server_hostname=domain)

        result["tls"] = True

        # 获取证书
        cert = ssl_sock.getpeercert()
        issuer = dict(x[0] for x in cert['issuer'])
        subject = dict(x[0] for x in cert['subject'])

        result["cert_cn"] = subject.get('commonName', '')
        result["issuer_org"] = issuer.get('organizationName', '')

        # 验证颁发机构
        result["trusted_issuer"] = result["issuer_org"] in TRUSTED_ISSUERS

        # 验证证书匹配域名
        cn = result["cert_cn"]
        if cn == domain or cn == f"*.{'.'.join(domain.split('.')[1:])}":
            result["cert_valid"] = True
        elif 'subjectAltName' in cert:
            sans = [x[1] for x in cert['subjectAltName'] if x[0] == 'DNS']
            if domain in sans or any(san.startswith('*.') and domain.endswith(san[1:]) for san in sans):
                result["cert_valid"] = True

        ssl_sock.close()

    except ssl.SSLError as e:
        result["error"] = f"TLS: {str(e)[:40]}"
    except socket.timeout:
        result["error"] = "Timeout"
    except ConnectionResetError:
        result["error"] = "Connection reset"
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:40]}"

    return result


def main():
    proxy = "http://127.0.0.1:12334"

    print("=" * 100)
    print("通过代理查询 DoH 并测试所有 IP")
    print("=" * 100)

    # 1. 通过代理查询 DoH
    print(f"\n【步骤1】通过代理查询 DoH")
    print("-" * 100)

    domain_ips: Dict[str, Set[str]] = defaultdict(set)

    for domain in TEST_DOMAINS:
        print(f"\n{domain}:")
        for doh in DOH_SERVERS:
            ips = query_doh_via_proxy(domain, doh, proxy)
            if ips:
                print(f"  ✅ {doh.split('/')[2][:20]}: {len(ips)} 个 IP")
                domain_ips[domain].update(ips)
            else:
                print(f"  ❌ {doh.split('/')[2][:20]}: 查询失败")

    # 2. 去重后测试
    print(f"\n\n【步骤2】测试去重后的 IP（直连 + 代理）")
    print("-" * 100)

    for domain, ips in domain_ips.items():
        ips_list = sorted(list(ips))
        print(f"\n{domain}: {len(ips_list)} 个唯一 IP")

        if not ips_list:
            continue

        # 并发测试（直连 + 代理）
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # 直连测试
            futures_direct = [
                executor.submit(test_ip_with_cert_check, ip, domain, False, "")
                for ip in ips_list[:5]  # 只测试前5个
            ]
            # 代理测试
            futures_proxy = [
                executor.submit(test_ip_with_cert_check, ip, domain, True, proxy)
                for ip in ips_list[:5]
            ]

            for future in concurrent.futures.as_completed(futures_direct + futures_proxy):
                results.append(future.result())

        # 排序：优先直连成功 + 证书可信
        results.sort(key=lambda x: (
            not x["cert_valid"],
            not x["trusted_issuer"],
            x["use_proxy"],
            not x["tls"],
            x["ip"]
        ))

        # 统计
        direct_ok = sum(1 for r in results if not r["use_proxy"] and r["cert_valid"] and r["trusted_issuer"])
        proxy_ok = sum(1 for r in results if r["use_proxy"] and r["cert_valid"] and r["trusted_issuer"])

        print(f"  直连可用: {direct_ok}, 代理可用: {proxy_ok}")
        print()

        # 显示结果
        for r in results[:10]:
            mode = "代理" if r["use_proxy"] else "直连"

            if r["cert_valid"] and r["trusted_issuer"]:
                status = f"✅ {mode}"
                detail = f"颁发者: {r['issuer_org']}"
            elif r["cert_valid"]:
                status = f"⚠️  {mode}"
                detail = f"颁发者: {r['issuer_org']} (不在白名单)"
            elif r["tls"]:
                status = f"❌ {mode}"
                detail = f"证书无效: CN={r['cert_cn']}"
            else:
                status = f"❌ {mode}"
                detail = r["error"]

            print(f"    {r['ip']:<20} {status:<10} {detail}")


if __name__ == "__main__":
    main()
