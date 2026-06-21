#!/usr/bin/env python3
"""分析 chunk_cache_adapter 的偏移计算 bug。

问题：
- chunk_byte_indices 是 xorb 内部的偏移（相对于 xorb 数据的起始位置）
- 但 merged_range 假设 chunks 是连续的
- 当 fetch_infos 的 chunk_range 不连续时，会出现长度不匹配

示例：
- fetch_infos: [(0, 69), (474, 484), (507, 540)]
- merged_range: [0, 540) → 期望 540 个 chunk offsets
- 实际 xorb 只包含 112 个 chunks (69 + 10 + 33)
- chunk_byte_indices 长度是 113 (112 chunks + 1)
"""
import json
import sys
from pathlib import Path

def analyze_offset_bug():
    """分析偏移计算 bug。"""

    # 加载 xorb_analysis.json
    with open('xorb_analysis.json') as f:
        data = json.load(f)

    print("=" * 70)
    print("🔍 Chunk Cache Offset Bug 分析")
    print("=" * 70)
    print()

    mismatched_xorbs = []

    for xorb_hash, info in data.items():
        if 'error' in info:
            continue

        fetch_infos = info['fetch_infos']
        ranges = [(fi['chunk_range']['start'], fi['chunk_range']['end'])
                  for fi in fetch_infos]

        # 当前的错误逻辑
        sorted_ranges = sorted(ranges)
        merged_start = min(r[0] for r in ranges)
        merged_end = max(r[1] for r in ranges)
        merged_length = merged_end - merged_start
        expected_by_merged = merged_length  # 错误的期望值

        # 实际的 chunks 数量
        actual_chunks = info['num_chunks']
        actual_indices = len(info['chunk_byte_indices'])

        # 正确的期望值：所有 ranges 的长度之和
        correct_expected = sum(r[1] - r[0] for r in ranges)

        # 检查是否不连续
        is_contiguous = True
        gaps = []
        for i in range(len(sorted_ranges) - 1):
            if sorted_ranges[i][1] != sorted_ranges[i+1][0]:
                is_contiguous = False
                gaps.append((sorted_ranges[i][1], sorted_ranges[i+1][0]))

        if not is_contiguous:
            mismatched_xorbs.append({
                'hash': xorb_hash,
                'ranges': ranges,
                'gaps': gaps,
                'merged_range': (merged_start, merged_end),
                'expected_by_merged': expected_by_merged,
                'correct_expected': correct_expected,
                'actual_chunks': actual_chunks,
                'actual_indices': actual_indices,
            })

    print(f"发现 {len(mismatched_xorbs)} 个不连续的 xorbs:\n")

    for idx, xorb in enumerate(mismatched_xorbs, 1):
        print(f"[{idx}] {xorb['hash'][:16]}...")
        print(f"  Chunk ranges: {xorb['ranges']}")
        print(f"  间隙: {xorb['gaps']}")
        print()
        print(f"  ❌ 错误逻辑 (当前代码):")
        print(f"    merged_range: [{xorb['merged_range'][0]}, {xorb['merged_range'][1]})")
        print(f"    期望 indices: {xorb['expected_by_merged'] + 1}")
        print(f"    实际 indices: {xorb['actual_indices']}")
        print(f"    → 长度不匹配，缓存被跳过 ❌")
        print()
        print(f"  ✅ 正确逻辑:")
        print(f"    每个 range 的 chunks 之和: {xorb['correct_expected']}")
        print(f"    期望 indices: {xorb['correct_expected'] + 1}")
        print(f"    实际 indices: {xorb['actual_indices']}")
        print(f"    → 长度匹配 ✅")
        print()
        print("-" * 70)
        print()

    # 总结修复方案
    print("=" * 70)
    print("💡 修复方案")
    print("=" * 70)
    print()
    print("问题根源:")
    print("  当前代码用 merged_range 来计算期望的 chunk_byte_indices 长度，")
    print("  假设 chunks 是连续的 [start, end)。")
    print()
    print("  但实际上，一个 xorb 可能只包含部分 chunks，")
    print("  chunk_byte_indices 的长度应该等于「所有 fetch_infos 的")
    print("  chunk_range 长度之和 + 1」，而不是 merged_range.length() + 1。")
    print()
    print("修复方案:")
    print("  在 put_xorb_decompressed() 中，改为:")
    print()
    print("    # 正确的期望长度：所有 ranges 的长度之和 + 1")
    print("    total_chunks = sum(cr.length() for cr in chunk_ranges)")
    print("    expected_len = total_chunks + 1")
    print()
    print("  而不是:")
    print("    # 错误：假设 chunks 连续")
    print("    expected_len = merged_range.length() + 1")
    print()
    print("影响:")
    print(f"  - 当前有 {len(mismatched_xorbs)}/10 个 xorbs 因为这个 bug 被跳过缓存")
    print(f"  - 修复后，这些 xorbs 也可以正常缓存")
    print()

if __name__ == '__main__':
    analyze_offset_bug()
