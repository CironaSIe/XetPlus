#!/usr/bin/env python3
"""测试 chunk 字节范围计算逻辑"""

def calculate_byte_range(chunk_offsets, start_chunk_idx, end_chunk_idx, data_len):
    """
    计算 chunk range [start, end) 对应的字节范围

    Args:
        chunk_offsets: [(chunk_id, byte_offset), ...]
        start_chunk_idx: 起始 chunk ID（包含）
        end_chunk_idx: 结束 chunk ID（不包含）
        data_len: xorb 数据总长度

    Returns:
        (start_byte, end_byte)
    """
    chunk_offset_dict = dict(chunk_offsets)

    # 找到 start_chunk_idx 的字节偏移
    start_byte = chunk_offset_dict.get(start_chunk_idx)
    if start_byte is None:
        raise ValueError(f"start chunk {start_chunk_idx} 不在 chunk_offsets 中")

    # 找到 end_chunk_idx 的字节偏移
    end_byte = chunk_offset_dict.get(end_chunk_idx)
    if end_byte is None:
        # end_chunk_idx 不在此 xorb，需要找 chunk[end-1] 的结束位置
        sorted_offsets = sorted(chunk_offsets, key=lambda x: x[0])
        for i, (chunk_idx, start_pos) in enumerate(sorted_offsets):
            if chunk_idx == end_chunk_idx - 1:
                # 找到了最后包含的 chunk
                if i + 1 < len(sorted_offsets):
                    end_byte = sorted_offsets[i + 1][1]
                else:
                    end_byte = data_len
                break
        else:
            raise ValueError(f"end-1 chunk {end_chunk_idx-1} 不在 chunk_offsets 中")

    return start_byte, end_byte


# 测试案例
print("=" * 60)
print("测试 chunk 字节范围计算逻辑")
print("=" * 60)

# 案例 1：xorb 包含连续的 chunk 10-14
chunk_offsets_1 = [(10, 0), (11, 1000), (12, 2500), (13, 4000), (14, 5500)]
data_len_1 = 7000

print("\n案例 1: xorb 包含 chunk 10-14")
print(f"chunk_offsets: {chunk_offsets_1}")
print(f"data_len: {data_len_1}")

test_cases_1 = [
    (10, 12, "chunk 10-11"),
    (11, 13, "chunk 11-12"),
    (12, 15, "chunk 12-14, end 不存在"),
    (10, 15, "chunk 10-14, end 不存在"),
]

for start, end, desc in test_cases_1:
    try:
        start_byte, end_byte = calculate_byte_range(chunk_offsets_1, start, end, data_len_1)
        length = end_byte - start_byte
        print(f"  Range [{start}, {end}): [{start_byte}, {end_byte}) = {length} bytes  # {desc}")
    except ValueError as e:
        print(f"  Range [{start}, {end}): ERROR - {e}")

# 案例 2：xorb 包含稀疏的 chunk（跳跃）
chunk_offsets_2 = [(50, 0), (51, 100), (52, 250), (99, 2000), (100, 2500)]
data_len_2 = 3000

print("\n案例 2: xorb 包含稀疏 chunk 50,51,52,99,100")
print(f"chunk_offsets: {chunk_offsets_2}")
print(f"data_len: {data_len_2}")

test_cases_2 = [
    (50, 52, "chunk 50-51"),
    (51, 53, "chunk 51-52"),
    (52, 53, "chunk 52, end 不存在"),
    (99, 101, "chunk 99-100, end 不存在"),
    (50, 101, "chunk 50,51,52,99,100, end 不存在"),
]

for start, end, desc in test_cases_2:
    try:
        start_byte, end_byte = calculate_byte_range(chunk_offsets_2, start, end, data_len_2)
        length = end_byte - start_byte
        print(f"  Range [{start}, {end}): [{start_byte}, {end_byte}) = {length} bytes  # {desc}")
    except ValueError as e:
        print(f"  Range [{start}, {end}): ERROR - {e}")

print("\n" + "=" * 60)
print("✅ 测试完成")
