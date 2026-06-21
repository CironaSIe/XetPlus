# Xorb 解压实现 - 当前状态和剩余工作

## ✅ 已完成

1. **复制核心文件**
   - ✅ `xet/storage/xorb_deserializer.py` - 完整的 xorb 反序列化
   - ✅ `xet/storage/merkle_hash.py` - Blake3 哈希计算
   - ✅ `xet/storage/xorb_adapter.py` - 适配层（暂未使用）

2. **安装依赖**
   - ✅ blake3>=0.3.0 已安装

3. **修复 ChunkAssembler**
   - ✅ 从错误的 term.op 模式改为正确的 term.range 模式
   - ✅ 实现基于 chunk_offsets 的数据提取逻辑
   - ⚠️ 部分实现全局 chunk 索引转换

## ❌ 发现的问题

### P0 - 阻塞下载完成

**问题**: Multipart Xorb 处理错误

**现象**:
```
ERROR: [ChunkAssembler] Chunk 104 未在 xorb f52ace46e9559367... 中找到
```

**根本原因**:
1. 一个 xorb 可能有多个不连续的 segments：
   - Xorb `f52ace46e9559367` 有 2 个 segments:
     - Segment 0: chunks [0, 41), bytes [0, 1668043]
     - Segment 1: chunks [104, 155), bytes [3519499, 5190774]

2. **DownloadScheduler 只下载第一个 segment**:
   ```python
   # download_scheduler.py line 199
   # 对于 multipart，只取第一个 fetch_info
   fi = fetch_infos[0]  # ❌ 错误！应该下载所有 segments
   ```

3. **ChunkAssembler 期望所有 segments 的数据**，但实际只有 segment 0

**解决方案**: 修改 DownloadScheduler，像 ~/xet.py 那样分别下载每个 segment

### 详细对比

#### ~/xet.py 的正确实现：
```python
# 分别下载每个 segment
all_pieces = []
for fi in sorted_infos:
    part_bytes = self.cas_client.get_xorb_data_with_retry(
        fi.url, fi.url_range, xorb_hash, file_hash
    )
    all_pieces.append((fi.chunk_range.start, part_bytes))

# 分别反序列化每个 segment
combined_offsets = []
combined_data = bytearray()
for base_chunk_start, raw_bytes in all_pieces:
    piece = XorbDeserializer.deserialize(raw_bytes)
    base_data_offset = len(combined_data)
    for local_idx, local_offset in piece.chunk_offsets:
        global_chunk_idx = base_chunk_start + local_idx
        global_data_offset = base_data_offset + local_offset
        combined_offsets.append((global_chunk_idx, global_data_offset))
    combined_data.extend(piece.data)

xorb_data = XorbBlockData(combined_offsets, bytes(combined_data))
```

#### XET+ 当前的错误实现：
```python
# ❌ 只下载第一个 segment
fi = fetch_infos[0]
data = self.cas_client.get_xorb_data_with_retry(fi.url, fi.url_range, ...)

# ❌ 尝试一次性反序列化（但数据不完整）
xorb_data = XorbDeserializer.deserialize(data)
```

---

## 🔧 需要修复的代码

### 1. DownloadScheduler._extract_xorb_tasks

**位置**: `xet/pipeline/download_scheduler.py:194`

**当前代码**:
```python
def _extract_xorb_tasks(self, recon: QueryReconstructionResponse) -> List[XorbDownloadTask]:
    tasks = []
    seen_xorbs = set()

    for xorb_hash, fetch_infos in recon.fetch_info.items():
        if xorb_hash in seen_xorbs:
            continue
        seen_xorbs.add(xorb_hash)

        # ❌ 对于 multipart，只取第一个 fetch_info
        fi = fetch_infos[0]
        tasks.append(XorbDownloadTask(
            xorb_hash=xorb_hash,
            url=fi.url,
            url_range=fi.url_range,
        ))

    return tasks
```

**需要改为**:
```python
def _extract_xorb_tasks(self, recon: QueryReconstructionResponse) -> List[XorbDownloadTask]:
    """提取所有 xorb segments 作为独立任务。
    
    一个 xorb 可能有多个 segments（不连续的 chunk 范围），
    需要分别下载每个 segment。
    """
    tasks = []
    task_id = 0

    for xorb_hash, fetch_infos in recon.fetch_info.items():
        # ✅ 为每个 segment 创建一个下载任务
        for fi in fetch_infos:
            tasks.append(XorbDownloadTask(
                xorb_hash=xorb_hash,
                url=fi.url,
                url_range=fi.url_range,
            ))
            task_id += 1

    return tasks
```

### 2. DownloadScheduler.download_all_xorbs 返回格式

**问题**: 当前返回 `{xorb_hash: bytes}`，但一个 xorb 有多个 segments 时会覆盖

**需要改为**: 返回 `{xorb_hash: List[(chunk_range_start, bytes)]}`

或者在 DownloadScheduler 内部合并 segments，返回合并后的数据。

### 3. ChunkAssembler._decompress_all_xorbs_to_xorb_data

**当前问题**: 假设 xorb_data_map 中每个 xorb 只有一份数据

**需要**: 接收每个 xorb 的多个 segments，分别反序列化后合并

---

## 📝 修复步骤（预计 30-60 分钟）

1. **修改 DownloadScheduler._extract_xorb_tasks**
   - 为每个 segment 创建独立任务
   - 估计时间: 5 分钟

2. **修改 DownloadScheduler.download_all_xorbs**
   - 收集同一个 xorb 的所有 segments
   - 按 chunk_range.start 排序
   - 传递 List[(chunk_range_start, bytes)] 给 ChunkAssembler
   - 估计时间: 15 分钟

3. **修改 ChunkAssembler._decompress_all_xorbs_to_xorb_data**
   - 接收 xorb segments 列表
   - 分别反序列化每个 segment
   - 合并 chunk_offsets 和 data（参考 ~/xet.py）
   - 估计时间: 20 分钟

4. **测试验证**
   - 完整下载 100MB 文件
   - 验证 SHA256
   - 估计时间: 10 分钟

---

## 🎯 其他发现

1. **Blake3 库正常工作** ✅
2. **Xorb 反序列化正常工作** ✅ (单个 segment 测试通过)
3. **网络下载正常** ✅ (进度条显示下载速度正常)
4. **认证流程完全正常** ✅

**唯一的问题就是 multipart segments 处理！**

---

## 💡 建议

**最快的修复路径**:
1. 直接参考 ~/xet.py/xet/reconstructor.py 的 `_download_single_xorb` 方法
2. 在 DownloadScheduler 中实现相同的逻辑
3. 预计 30 分钟内可以完成并测试成功

**关键代码参考**: ~/xet.py/xet/reconstructor.py:221-260

---

**时间**: 2026-06-21 00:35
**状态**: 95% 完成，只差 multipart segments 处理
**预计完成时间**: 30-60 分钟
