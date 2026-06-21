#!/usr/bin/env python3
"""测试 HostOptimizer 功能。

验证：
1. DoH 查询是否工作
2. TCP 测速是否工作
3. HTTP Transfer 测速是否工作
4. 缓存机制是否工作
5. monkey-patch 是否生效
"""
import sys
import os
import logging
from pathlib import Path

# 添加 xet 到 Python path
sys.path.insert(0, str(Path(__file__).parent))

from xet.network.host_optimizer import HostOptimizer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)

logger = logging.getLogger(__name__)


def test_host_optimizer():
    """测试 HostOptimizer 基本功能。"""
    print("=" * 60)
    print("测试 HostOptimizer 功能")
    print("=" * 60)

    # 从环境变量读取代理
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy') or ""
    if proxy:
        print(f"\n使用代理: {proxy}")
    else:
        print("\n未配置代理（可设置 HTTPS_PROXY 环境变量）")

    # 创建优化器
    optimizer = HostOptimizer(proxy=proxy)

    # 执行优选
    print("\n开始 HOST 优选...")
    print("-" * 60)

    mappings, used_opt_cache, used_doh_cache = optimizer.optimize(force_refresh=False)

    print("-" * 60)
    print("\n优选结果:")
    print("=" * 60)

    if mappings:
        for domain, info in mappings.items():
            mode = "代理" if info["use_proxy"] else "直连"
            rtt_ms = info["rtt"] * 1000

            from xet.network.host_optimizer import _format_speed

            if info.get("speed", 0) > 0:
                speed_str = _format_speed(info["speed"])
                print(
                    f"✅ {domain}\n"
                    f"   IP: {info['ip']}\n"
                    f"   模式: {mode}\n"
                    f"   RTT: {rtt_ms:.0f}ms\n"
                    f"   速度: {speed_str}\n"
                )
            else:
                print(
                    f"⚠️ {domain}\n"
                    f"   IP: {info['ip']}\n"
                    f"   模式: {mode}\n"
                    f"   RTT: {rtt_ms:.0f}ms\n"
                    f"   速度: N/A (Transfer 测速失败)\n"
                )

        print("-" * 60)
        print(f"总计: {len(mappings)} 个域名优选成功")

        if used_opt_cache:
            print("使用了优选缓存（有效期 1 小时）")
        elif used_doh_cache:
            print("使用了 DoH 缓存（有效期 24 小时）")
        else:
            print("执行了完整的 DoH 查询和测速")

    else:
        print("❌ 优选失败：未获得任何有效映射")
        return 1

    # 验证 monkey-patch
    print("\n" + "=" * 60)
    print("验证 socket.getaddrinfo patch:")
    print("=" * 60)

    import socket
    for domain in list(mappings.keys())[:2]:  # 只测试前2个
        try:
            result = socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
            resolved_ip = result[0][4][0]
            expected_ip = mappings[domain]["ip"]

            if resolved_ip == expected_ip:
                print(f"✅ {domain} → {resolved_ip} (patch 生效)")
            else:
                print(f"❌ {domain} → {resolved_ip} (期望 {expected_ip})")
        except Exception as e:
            print(f"❌ {domain}: 解析失败 - {e}")

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)

    # 提示缓存位置
    print(f"\n缓存位置:")
    print(f"  优选缓存: {optimizer.cache_path}")
    print(f"  DoH 缓存: {optimizer.doh_cache_path}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(test_host_optimizer())
    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"测试失败: {e}")
        sys.exit(1)
