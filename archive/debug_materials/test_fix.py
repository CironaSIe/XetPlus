#!/usr/bin/env python3
"""验证 chunk_cache_adapter 修复是否有效。

测试方法：
1. 加载 xorb_analysis.json（包含所有 xorb 的分析数据）
2. 模拟 put_xorb_decompressed() 的逻辑
3. 验证修复后的代码对所有 xorb 都能正确处理
"""
import json
from pathlib import Path
from typing import List, Tuple


class ChunkRange:
    """简化的 ChunkRange 类（用于测试）。"""
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end

    def length(self) -> int:
        return self.end - self.start

    def __repr__(self):
        return f"ChunkRange({self.start}, {self.end})"


def old_logic(chunk_ranges: List[ChunkRange], chunk_byte_indices: List[int]) -> Tuple[bool, int, int]:
    """旧的错误逻辑（假设 chunks 连续）。

    Returns:
        (是否通过, 期望长度, 实际长度)
    """
    merged_range = ChunkRange(
        start=min(cr.start for cr in chunk_ranges),
        end=max(cr.end for cr in chunk_ranges)
    )
    expected_len = merged_range.length() + 1
    actual_len = len(chunk_byte_indices)
    return (expected_len == actual_len, expected_len, actual_len)


def new_logic(chunk_ranges: List[ChunkRange], chunk_byte_indices: List[int]) -> Tuple[bool, int, int]:
    """新的正确逻辑（使用所有 ranges 的长度之和）。

    Returns:
        (是否通过, 期望长度, 实际长度)
    """
    total_chunks = sum(cr.length() for cr in chunk_ranges)
    expected_len = total_chunks + 1
    actual_len = len(chunk_byte_indices)
    return (expected_len == actual_len, expected_len, actual_len)


def main():
    """验证修复。"""

    # 加载分析数据
    analysis_file = Path(__file__).parent / "xorb_analysis.json"
    with open(analysis_file) as f:
        data = json.load(f)

    print("=" * 70)
    print("🧪 验证 chunk_cache_adapter 修复")
    print("=" * 70)
    print()

    old_passed = 0
    old_failed = 0
    new_passed = 0
    new_failed = 0

    failed_cases = []

    for xorb_hash, info in data.items():
        if 'error' in info:
            print(f"⏭️  跳过 {xorb_hash[:16]}... (解压失败)")
            continue

        # 构造 chunk_ranges
        chunk_ranges = [
            ChunkRange(fi['chunk_range']['start'], fi['chunk_range']['end'])
            for fi in info['fetch_infos']
        ]
        chunk_byte_indices = info['chunk_byte_indices']

        # 测试旧逻辑
        old_pass, old_expected, old_actual = old_logic(chunk_ranges, chunk_byte_indices)
        if old_pass:
            old_passed += 1
        else:
            old_failed += 1

        # 测试新逻辑
        new_pass, new_expected, new_actual = new_logic(chunk_ranges, chunk_byte_indices)
        if new_pass:
            new_passed += 1
        else:
            new_failed += 1
            failed_cases.append({
                'hash': xorb_hash,
                'ranges': [(cr.start, cr.end) for cr in chunk_ranges],
                'expected': new_expected,
                'actual': new_actual,
            })

        # 显示结果
        status_old = "✅" if old_pass else "❌"
        status_new = "✅" if new_pass else "❌"

        if not old_pass or not new_pass:
            print(f"{xorb_hash[:16]}...")
            print(f"  Ranges: {[(cr.start, cr.end) for cr in chunk_ranges]}")
            print(f"  旧逻辑: {status_old} 期望 {old_expected}, 实际 {old_actual}")
            print(f"  新逻辑: {status_new} 期望 {new_expected}, 实际 {new_actual}")
            print()

    # 总结
    print("=" * 70)
    print("📊 测试结果")
    print("=" * 70)
    print()
    print(f"旧逻辑（修复前）:")
    print(f"  ✅ 通过: {old_passed}")
    print(f"  ❌ 失败: {old_failed}")
    print(f"  成功率: {old_passed / (old_passed + old_failed) * 100:.1f}%")
    print()
    print(f"新逻辑（修复后）:")
    print(f"  ✅ 通过: {new_passed}")
    print(f"  ❌ 失败: {new_failed}")
    print(f"  成功率: {new_passed / (new_passed + new_failed) * 100:.1f}%")
    print()

    if new_failed > 0:
        print("⚠️  警告: 新逻辑仍有失败案例！")
        print()
        print("失败案例详情:")
        for case in failed_cases:
            print(f"  - {case['hash'][:16]}...")
            print(f"    Ranges: {case['ranges']}")
            print(f"    期望: {case['expected']}, 实际: {case['actual']}")
            print()
        return 1
    else:
        print("✅ 所有测试通过！修复有效。")
        print()
        print(f"改进:")
        print(f"  - 修复前: {old_failed} 个 xorb 被错误跳过")
        print(f"  - 修复后: 0 个 xorb 被错误跳过")
        print(f"  - 缓存命中率提升: +{old_failed / (old_passed + old_failed) * 100:.1f}%")
        return 0


if __name__ == '__main__':
    exit(main())
