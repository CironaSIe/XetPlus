#!/usr/bin/env python3
"""调试 chunk_assembler 的字节范围计算逻辑"""
import sys
sys.path.insert(0, '/data/data/com.termux/files/home/xetplus')

import json

# 加载测试数据
with open('debug_materials/xorb_analysis.json') as f:
    data = json.load(f)

# 测试第一个 xorb (包含不连续的全局 chunk ranges)
xorb_hash = 'f52ace46e9559367a345b3c5a6ad6261391dae66197857915fa7d6a1ca27c812'
xorb_info = data[xorb_hash]

print(f"Xorb: {xorb_hash[:16]}...")
print(f"Fetch infos: {xorb_info['fetch_infos']}")
print(f"Total chunks: {xorb_info['num_chunks']}")
print()

# 使用预先解压的数据（xorbs/*.bin 已经是解压后的数据）
xorb_file = f'debug_materials/xorbs/{xorb_hash}.bin'
with open(xorb_file, 'rb') as f:
    decompressed_data = f.read()

# 使用 xorb_analysis.json 中的 chunk_byte_indices
# 这个列表是字节偏移量：[offset_0, offset_1, ..., offset_n, file_end]
byte_indices = xorb_info['chunk_byte_indices']

print(f"数据信息:")
print(f"  chunk_byte_indices 数量: {len(byte_indices)}")
print(f"  data 大小: {len(decompressed_data)} bytes")
print()

# 构建 chunk_offsets（内部索引 → 字节偏移）
chunk_offsets = [(i, byte_indices[i]) for i in range(len(byte_indices) - 1)]
chunk_offsets_dict = dict(chunk_offsets)
print(f"chunk_offsets_dict 的键:")
print(f"  min: {min(chunk_offsets_dict.keys())}")
print(f"  max: {max(chunk_offsets_dict.keys())}")
print(f"  count: {len(chunk_offsets_dict)}")
print(f"  keys 示例: {sorted(chunk_offsets_dict.keys())[:10]}...{sorted(chunk_offsets_dict.keys())[-5:]}")
print()

# 构建全局 ID → 内部索引映射
fetch_infos = xorb_info['fetch_infos']
global_to_internal = {}
internal_idx = 0
for fi in fetch_infos:
    start = fi['chunk_range']['start']
    end = fi['chunk_range']['end']
    for global_id in range(start, end):
        global_to_internal[global_id] = internal_idx
        internal_idx += 1

print(f"全局 ID → 内部索引映射:")
print(f"  全局 chunk 0 → 内部 {global_to_internal[0]}")
print(f"  全局 chunk 40 → 内部 {global_to_internal[40]}")
print(f"  全局 chunk 104 → 内部 {global_to_internal[104]}")
print(f"  全局 chunk 154 → 内部 {global_to_internal[154]}")
print()

# 测试几个 term range
test_cases = [
    (0, 41, "前41个chunk，全局0-40"),
    (104, 155, "后51个chunk，全局104-154"),
    (0, 155, "全部92个chunk（跨两个segment）"),
]

print("测试 term ranges:")
for start_global, end_global, desc in test_cases:
    print(f"\n  [{start_global}, {end_global}) - {desc}")

    # 转换为内部索引
    if start_global not in global_to_internal:
        print(f"    ❌ start_global {start_global} 不在映射中")
        continue
    if end_global - 1 not in global_to_internal:
        print(f"    ❌ end_global-1 {end_global-1} 不在映射中")
        continue

    start_internal = global_to_internal[start_global]
    end_internal = global_to_internal[end_global - 1] + 1

    print(f"    内部索引: [{start_internal}, {end_internal})")

    # 查找字节偏移
    if start_internal not in chunk_offsets_dict:
        print(f"    ❌ start_internal {start_internal} 不在 chunk_offsets_dict 中")
        continue

    start_byte = chunk_offsets_dict[start_internal]

    if end_internal in chunk_offsets_dict:
        end_byte = chunk_offsets_dict[end_internal]
        print(f"    ✅ end_internal {end_internal} 在 chunk_offsets_dict 中")
    else:
        max_internal = max(chunk_offsets_dict.keys())
        if end_internal == max_internal + 1:
            end_byte = len(decompressed_data)
            print(f"    ✅ end_internal {end_internal} = max+1, 使用文件末尾")
        else:
            print(f"    ❌ end_internal {end_internal} 不在 chunk_offsets_dict 中")
            print(f"       max_internal = {max_internal}")
            print(f"       max_internal + 1 = {max_internal + 1}")
            continue

    print(f"    字节范围: [{start_byte}, {end_byte}) = {end_byte - start_byte} bytes")
