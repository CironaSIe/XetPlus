#!/usr/bin/env python3
"""验证完整修复：测试不连续 chunk ranges 的缓存。

使用离线 debug 材料测试修复逻辑。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from xet.pipeline.chunk_disk_cache import ChunkDiskCache, ChunkRange
from xet.pipeline.chunk_cache_adapter import ChunkCacheAdapter
import json
import tempfile
import shutil


class MockFetchInfo:
    """模拟 FetchInfo 对象。"""
    def __init__(self, chunk_range):
        self.chunk_range = chunk_range


def test_non_contiguous_ranges():
    """测试不连续的 chunk ranges 缓存。"""

    print("=" * 70)
    print("🧪 测试不连续 Chunk Ranges 缓存")
    print("=" * 70)
    print()

    # 创建临时缓存目录
    cache_dir = Path(tempfile.mkdtemp())

    try:
        # 初始化缓存
        chunk_cache = ChunkDiskCache(
            cache_root=cache_dir,
            capacity_bytes=100 * 1024 * 1024  # 100MB
        )
        adapter = ChunkCacheAdapter(chunk_cache=chunk_cache)

        # 加载测试数据
        with open('debug_materials/xorb_analysis.json') as f:
            data = json.load(f)

        # 测试不连续的 xorbs
        test_cases = [
            ('f52ace46e9559367a345b3c5a6ad6261391dae66197857915fa7d6a1ca27c812',
             'f52ace46', [(0, 41), (104, 155)]),
            ('edc32dd7fbd51b16d0c668e87faf4e627bee1a31343defbe21c98261e219301e',
             'edc32dd7', [(0, 69), (474, 484), (507, 540)]),
            ('33d17623391c6d2b3ef7d4aaae020d4f45245612daf4ce5bc875736bc02f53c5',
             '33d17623', [(118, 409), (419, 436)]),
        ]

        passed = 0
        failed = 0

        for xorb_hash, short_hash, ranges in test_cases:
            print(f"测试 {short_hash}...")
            print(f"  Chunk ranges: {ranges}")

            # 获取 xorb 数据
            xorb_info = data[xorb_hash]
            chunk_byte_indices = xorb_info['chunk_byte_indices']

            # 读取解压数据
            xorb_file = Path(f'debug_materials/xorbs/{xorb_hash}.bin')
            with open(xorb_file, 'rb') as f:
                decompressed_data = f.read()

            # 创建 mock fetch_infos
            fetch_infos = [
                MockFetchInfo(ChunkRange(start, end))
                for start, end in ranges
            ]

            # 测试写入
            print(f"  写入缓存...")
            adapter.put_xorb_decompressed(
                xorb_hash,
                fetch_infos,
                chunk_byte_indices,
                decompressed_data
            )

            # 测试读取
            print(f"  读取缓存...")
            result = adapter.get_xorb_decompressed(xorb_hash, fetch_infos)

            if result is None:
                print(f"  ❌ 读取失败：缓存未命中")
                failed += 1
                continue

            cached_data, cached_indices = result

            # 验证数据
            if cached_data == decompressed_data:
                print(f"  ✅ 数据匹配")
            else:
                print(f"  ❌ 数据不匹配: {len(cached_data)} vs {len(decompressed_data)} bytes")
                failed += 1
                continue

            # 验证索引
            if cached_indices == chunk_byte_indices:
                print(f"  ✅ 索引匹配")
            else:
                print(f"  ❌ 索引不匹配")
                print(f"    期望: {len(chunk_byte_indices)} 个")
                print(f"    实际: {len(cached_indices)} 个")
                if len(cached_indices) == len(chunk_byte_indices):
                    # 长度相同但内容不同，显示差异
                    for i, (exp, act) in enumerate(zip(chunk_byte_indices, cached_indices)):
                        if exp != act:
                            print(f"    索引 {i}: 期望 {exp}, 实际 {act}")
                            if i >= 5:
                                print(f"    ... (还有 {len(chunk_byte_indices) - i - 1} 个差异)")
                                break
                failed += 1
                continue

            print(f"  ✅ 测试通过")
            passed += 1
            print()

        # 总结
        print("=" * 70)
        print("📊 测试结果")
        print("=" * 70)
        print()
        print(f"总测试: {len(test_cases)}")
        print(f"  ✅ 通过: {passed}")
        print(f"  ❌ 失败: {failed}")
        print()

        if failed == 0:
            print("✅ 所有测试通过！不连续 chunk ranges 缓存正常工作。")
            return 0
        else:
            print("❌ 有测试失败！")
            return 1

    finally:
        # 清理临时目录
        shutil.rmtree(cache_dir)


if __name__ == '__main__':
    exit(test_non_contiguous_ranges())
