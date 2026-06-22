#!/usr/bin/env python3
"""测试所有 DoH IP 的直连可达性"""

import json
import socket
import ssl
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Tuple

def test_ip_direct(ip: str, domain: str, timeout: int = 3) -> Dict:
    """测试直连 IP 的完整状态"""
    result = {
        "ip": ip,
        "tcp": False,
        "tls": False,
        "cert_valid": False,
        "cert_cn": "",
        "error": "",
    }

    try:
        # 1. TCP 连接
        sock = socket.create_connection((ip, 443), timeout=timeout)
        result["tcp"] = True

        # 2. TLS 握手
        ctx = ssl.create_default_context()
        ssl_sock = ctx.wrap_socket(sock, server_hostname=domain)
        result["tls"] = True

        # 3. 证书验证
        cert = ssl_sock.getpeercert()
        cn = dict(x[0] for x in cert['subject'])['commonName']
        result["cert_cn"] = cn

        # 检查证书是否匹配域名
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
    # 读取 DoH 缓存
    doh_cache = Path.home() / ".xet" / "cache" / "host_doh.json"

    if not doh_cache.exists():
        print("❌ DoH 缓存不存在")
        return

    with open(doh_cache) as f:
        data = json.load(f)

    ip_data = data.get("ips", {})

    print("=" * 100)
    print("测试所有 DoH IP 的直连可达性")
    print("=" * 100)

    # 按域名测试
    for domain, ips in ip_data.items():
        print(f"\n【{domain}】- {len(ips)} 个 IP")
        print("-" * 100)

        # 并发测试所有 IP
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(test_ip_direct, ip, domain, 3) for ip in ips]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        # 排序：成功的在前
        results.sort(key=lambda x: (not x["cert_valid"], not x["tls"], not x["tcp"], x["ip"]))

        # 统计
        tcp_ok = sum(1 for r in results if r["tcp"])
        tls_ok = sum(1 for r in results if r["tls"])
        cert_ok = sum(1 for r in results if r["cert_valid"])

        print(f"统计: TCP={tcp_ok}/{len(ips)}, TLS={tls_ok}/{len(ips)}, 证书有效={cert_ok}/{len(ips)}")
        print()

        # 显示前10个结果（包括成功和失败的）
        for i, r in enumerate(results[:10], 1):
            if r["cert_valid"]:
                status = "✅ 完全可用"
                detail = f"CN={r['cert_cn']}"
            elif r["tls"]:
                status = "⚠️  TLS成功"
                detail = f"证书={r['cert_cn']}"
            elif r["tcp"]:
                status = "❌ TLS失败"
                detail = r["error"]
            else:
                status = "❌ TCP失败"
                detail = r["error"]

            print(f"  {i:2}. {r['ip']:<20} {status:<12} {detail}")

        if len(results) > 10:
            print(f"  ... 还有 {len(results)-10} 个 IP（省略）")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
