"""ChunkAssembler 的辅助方法（预取机制相关）。"""
import logging
from typing import Optional
from concurrent.futures import Future

from xet.protocol.types import QueryReconstructionResponse
from xet.pipeline.xorb_disk_cache import XorbDiskCache
from xet.pipeline.chunk_cache_adapter import ChunkCacheAdapter

logger = logging.getLogger(__name__)


class PrefetchHelpers:
    """预取机制的辅助方法（混入到 ChunkAssembler）。"""

    def _load_from_disk_cache(
        self,
        recon: QueryReconstructionResponse,
        cache_adapter: ChunkCacheAdapter,
    ) -> None:
        """从磁盘缓存加载 xorb（受水位线限制）。

        只加载到 prefetch_high_mb 水位线为止，避免断点续传时
        将所有缓存数据一次性加载到内存导致 OOM。

        Args:
            recon: Reconstruction 响应
            cache_adapter: 缓存适配器
        """
        max_load_bytes = self.prefetch_high_mb * 1024 * 1024
        loaded_count = 0
        for xorb_hash in recon.fetch_info.keys():
            if xorb_hash in self._xorb_cache:
                continue

            # 检查水位线
            current_cache_bytes = sum(
                x.memory_footprint() for x in self._xorb_cache.values()
            )
            if current_cache_bytes >= max_load_bytes:
                logger.debug(
                    f"[Cache] 达到水位线 ({self.prefetch_high_mb}MB)，"
                    f"停止加载磁盘缓存"
                )
                break

            fetch_infos = recon.fetch_info[xorb_hash]

            # 尝试从 chunk 缓存加载（优先）
            cache_hit = cache_adapter.get_xorb_decompressed(xorb_hash, fetch_infos)
            if cache_hit:
                decompressed_data, chunk_byte_indices = cache_hit
                # 构造 StreamingXorbAccessor（预解压模式）
                from xet.storage.xorb_deserializer import StreamingXorbAccessor

                # 从 fetch_infos 获取全局 chunk ID 范围
                # fetch_infos 可能包含多个段，需要合并所有的 chunk 范围
                all_chunk_ids = []
                for fi in fetch_infos:
                    chunk_range = fi.chunk_range
                    for chunk_id in range(chunk_range.start, chunk_range.end):
                        all_chunk_ids.append(chunk_id)

                # 构建 chunk_offsets: [(global_chunk_id, byte_offset), ...]
                chunk_offsets = []
                for i in range(len(chunk_byte_indices) - 1):
                    if i < len(all_chunk_ids):
                        chunk_offsets.append((all_chunk_ids[i], chunk_byte_indices[i]))

                xorb_data = StreamingXorbAccessor(
                    raw_bytes=decompressed_data,
                    chunk_offsets=chunk_offsets
                )
                self._xorb_cache[xorb_hash] = xorb_data
                loaded_count += 1
                continue

            # 回退到 xorb 缓存
            expected_size = sum(
                fi.url_range.end - fi.url_range.start
                for fi in fetch_infos
            )
            compressed_data = cache_adapter.get_xorb_compressed(xorb_hash, expected_size)
            if compressed_data:
                try:
                    xorb_data = self._decompress_single_xorb(
                        xorb_hash, compressed_data, recon
                    )
                    self._xorb_cache[xorb_hash] = xorb_data
                    loaded_count += 1

                    # 升级到 chunk 缓存
                    chunk_byte_indices = xorb_data.get_chunk_byte_indices()
                    cache_adapter.put_xorb_decompressed(
                        xorb_hash, fetch_infos, chunk_byte_indices, xorb_data.decompress_all().data
                    )
                except Exception as e:
                    logger.warning(
                        f"[Cache] 磁盘缓存数据损坏，跳过: {xorb_hash[:16]}... ({e})"
                    )

        if loaded_count > 0:
            cache_mb = sum(x.memory_footprint() for x in self._xorb_cache.values()) / 1024 / 1024
            total_xorbs = len(recon.fetch_info)
            hit_rate = (loaded_count / total_xorbs * 100) if total_xorbs > 0 else 0
            logger.info(
                f"[Cache] 从磁盘加载 {loaded_count}/{total_xorbs} 个 xorb "
                f"({cache_mb:.1f} MB), "
                f"缓存命中率: {hit_rate:.1f}%"
            )

    def _ensure_xorb_ready(
        self,
        xorb_hash: str,
        recon: QueryReconstructionResponse,
        cas_client,
        file_hash: str,
        cache_adapter: Optional[ChunkCacheAdapter],
        progress_tracker=None,
    ) -> None:
        """确保 xorb 已加载到内存缓存中。

        如果不在缓存中，触发下载和解压。

        Args:
            xorb_hash: Xorb 哈希
            recon: Reconstruction 响应
            cas_client: CAS 客户端
            file_hash: 文件哈希
            cache_adapter: 缓存适配器（支持 chunk/xorb 两种缓存）
            progress_tracker: 进度跟踪器（可选）
        """
        # 已在内存缓存中
        if xorb_hash in self._xorb_cache:
            return

        # 正在下载中，等待完成
        if xorb_hash in self._download_futures:
            future = self._download_futures[xorb_hash]
            try:
                compressed_data = future.result()

                # 解压
                xorb_data = self._decompress_single_xorb(
                    xorb_hash, compressed_data, recon
                )
                self._xorb_cache[xorb_hash] = xorb_data

                # 保存到缓存（xorb-level 和 chunk-level）
                if cache_adapter and cache_adapter.enabled:
                    # 保存压缩数据到 xorb 缓存
                    cache_adapter.put_xorb_compressed(xorb_hash, compressed_data)

                    # 保存解压数据到 chunk 缓存
                    fetch_infos = recon.fetch_info[xorb_hash]
                    chunk_byte_indices = xorb_data.get_chunk_byte_indices()
                    cache_adapter.put_xorb_decompressed(
                        xorb_hash, fetch_infos, chunk_byte_indices, xorb_data.decompress_all().data
                    )

                del self._download_futures[xorb_hash]
            except Exception as e:
                logger.error(f"[Download] Xorb {xorb_hash[:16]}... 下载失败: {e}")
                raise
            return

        # 尝试从 chunk 缓存加载（优先）
        if cache_adapter and cache_adapter.enabled:
            fetch_infos = recon.fetch_info[xorb_hash]
            cache_hit = cache_adapter.get_xorb_decompressed(xorb_hash, fetch_infos)
            if cache_hit:
                decompressed_data, chunk_byte_indices = cache_hit
                # 构造 StreamingXorbAccessor（预解压模式）
                from xet.storage.xorb_deserializer import StreamingXorbAccessor

                # 从 fetch_infos 获取全局 chunk ID 范围（与 _load_from_disk_cache 一致）
                all_chunk_ids = []
                for fi in fetch_infos:
                    chunk_range = fi.chunk_range
                    for chunk_id in range(chunk_range.start, chunk_range.end):
                        all_chunk_ids.append(chunk_id)

                # 构建 chunk_offsets: [(global_chunk_id, byte_offset), ...]
                chunk_offsets = []
                for i in range(len(chunk_byte_indices) - 1):
                    if i < len(all_chunk_ids):
                        chunk_offsets.append((all_chunk_ids[i], chunk_byte_indices[i]))

                xorb_data = StreamingXorbAccessor(
                    raw_bytes=decompressed_data,
                    chunk_offsets=chunk_offsets
                )
                self._xorb_cache[xorb_hash] = xorb_data
                logger.debug(f"[Cache] Chunk 缓存命中: {xorb_hash[:16]}...")
                return

        # 尝试从 xorb 缓存加载（回退）
        if cache_adapter and cache_adapter.enabled:
            fetch_infos = recon.fetch_info[xorb_hash]
            expected_size = sum(
                fi.url_range.end - fi.url_range.start
                for fi in fetch_infos
            )
            compressed_data = cache_adapter.get_xorb_compressed(xorb_hash, expected_size)
            if compressed_data:
                # 解压
                xorb_data = self._decompress_single_xorb(
                    xorb_hash, compressed_data, recon
                )
                self._xorb_cache[xorb_hash] = xorb_data

                # 升级到 chunk 缓存
                chunk_byte_indices = xorb_data.get_chunk_byte_indices()
                cache_adapter.put_xorb_decompressed(
                    xorb_hash, fetch_infos, chunk_byte_indices, xorb_data.decompress_all().data
                )
                logger.debug(f"[Cache] Xorb 缓存命中（升级到 chunk）: {xorb_hash[:16]}...")
                return

        # 需要立即下载
        logger.debug(f"[Download] 立即下载 xorb: {xorb_hash[:16]}...")
        fetch_infos = recon.fetch_info[xorb_hash]
        compressed_data = self._download_xorb_sync(
            xorb_hash, fetch_infos, cas_client, file_hash, progress_tracker
        )

        # 解压
        xorb_data = self._decompress_single_xorb(
            xorb_hash, compressed_data, recon
        )
        self._xorb_cache[xorb_hash] = xorb_data

        # 保存到缓存
        if cache_adapter and cache_adapter.enabled:
            cache_adapter.put_xorb_compressed(xorb_hash, compressed_data)

            chunk_byte_indices = xorb_data.get_chunk_byte_indices()
            cache_adapter.put_xorb_decompressed(
                xorb_hash, fetch_infos, chunk_byte_indices, xorb_data.decompress_all().data
            )

    def _prefetch_upcoming_xorbs(
        self,
        current_term_idx: int,
        recon: QueryReconstructionResponse,
        cas_client,
        file_hash: str,
        cache_adapter: Optional[ChunkCacheAdapter],
        high_watermark: int,
        progress_tracker=None,
    ) -> None:
        """预取后续的 xorb（异步下载，自适应大小）。

        Args:
            current_term_idx: 当前 term 索引
            recon: Reconstruction 响应
            cas_client: CAS 客户端
            file_hash: 文件哈希
            cache_adapter: 缓存适配器（可选）
            high_watermark: 高水位线（字节）
            progress_tracker: 进度跟踪器（可选）
        """
        current_cache_bytes = sum(x.memory_footprint() for x in self._xorb_cache.values())

        # 自适应预取：根据完成速率计算目标缓冲区
        completion_rate = self._rate_estimator.get_rate()  # bytes/s
        target_buffer_time = 10.0  # 10 秒缓冲（覆盖网络抖动即可）

        # 硬上限：不超过 max_memory_mb 配置值
        max_buffer_bytes = self.max_memory_mb * 1024 * 1024

        if completion_rate > 0:
            # 目标缓冲区 = 速率 × 时间，但不超过硬上限
            target_buffer_bytes = completion_rate * target_buffer_time
            adaptive_watermark = min(max_buffer_bytes, max(int(target_buffer_bytes), high_watermark))

            logger.debug(
                f"[Prefetch] 自适应预取: 速率={completion_rate / 1024 / 1024:.2f} MB/s, "
                f"目标缓冲={target_buffer_bytes / 1024 / 1024:.1f}MB, "
                f"硬上限={max_buffer_bytes / 1024 / 1024:.0f}MB, "
                f"使用水位={adaptive_watermark / 1024 / 1024:.1f}MB"
            )
        else:
            # 速率未知，使用固定高水位线（不超过硬上限）
            adaptive_watermark = min(high_watermark, max_buffer_bytes)

        # 收集后续需要的 xorb
        upcoming_xorbs = []
        seen = set(self._xorb_cache.keys()) | set(self._download_futures.keys())

        for term in recon.terms[current_term_idx:]:
            if term.hash not in seen:
                upcoming_xorbs.append(term.hash)
                seen.add(term.hash)

            # 估算如果下载这些 xorb，缓存会有多大
            estimated_size = 0
            for xorb_hash in upcoming_xorbs:
                fetch_infos = recon.fetch_info.get(xorb_hash, [])
                estimated_size += sum(
                    (fi.url_range.end - fi.url_range.start) * 2.5  # 压缩比估算
                    for fi in fetch_infos
                )

            # 达到自适应水位线，停止预取
            if current_cache_bytes + estimated_size >= adaptive_watermark:
                break

        # 提交异步下载（限制单次预取数量）
        submitted = 0
        prefetch_limit = getattr(self, 'prefetch_max', 8)  # 默认 8

        for xorb_hash in upcoming_xorbs:
            # 检查并发数限制
            if len(self._download_futures) >= self.max_concurrent_downloads:
                break

            # 检查单次预取数量限制
            if submitted >= prefetch_limit:
                break

            fetch_infos = recon.fetch_info[xorb_hash]
            future = self._download_executor.submit(
                self._download_xorb_sync,
                xorb_hash, fetch_infos, cas_client, file_hash, progress_tracker
            )
            self._download_futures[xorb_hash] = future
            submitted += 1

        if submitted > 0:
            logger.debug(
                f"[Prefetch] 预取 {submitted}/{prefetch_limit} 个 xorb "
                f"(缓存: {current_cache_bytes / 1024 / 1024:.1f}MB, "
                f"进行中: {len(self._download_futures)})"
            )

    def _is_xorb_needed_later(
        self,
        xorb_hash: str,
        current_term_idx: int,
        recon: QueryReconstructionResponse,
    ) -> bool:
        """检查 xorb 是否在后续 term 中还需要。

        Args:
            xorb_hash: Xorb 哈希
            current_term_idx: 当前 term 索引
            recon: Reconstruction 响应

        Returns:
            True 表示后续还需要，False 表示可以释放
        """
        for term in recon.terms[current_term_idx + 1:]:
            if term.hash == xorb_hash:
                return True
        return False

    def _download_xorb_sync(
        self,
        xorb_hash: str,
        fetch_infos: list,
        cas_client,
        file_hash: str,
        progress_tracker=None,
        extract_indices: bool = False,
    ) -> bytes:
        """同步下载 xorb 的所有 segments 并合并。

        Args:
            xorb_hash: Xorb 哈希
            fetch_infos: Fetch info 列表（可能有多个 segments）
            cas_client: CAS 客户端
            file_hash: 文件哈希
            progress_tracker: 进度跟踪器（可选）
            extract_indices: 是否提取 chunk_byte_indices（用于 chunk 缓存）

        Returns:
            合并后的压缩 xorb 数据（如果 extract_indices=True，则返回元组）
        """
        # 按 chunk_range.start 排序
        sorted_infos = sorted(fetch_infos, key=lambda fi: fi.chunk_range.start)

        # 开始下载 xorb
        if progress_tracker:
            progress_tracker.start_xorb_download(xorb_hash)

        # 下载所有 segments
        segments = []
        total_size = 0
        for seg_idx, fi in enumerate(sorted_infos):
            # 使用 get_xorb_data_with_retry：支持 403 URL 过期自动刷新 token + 重建签名 URL
            # （旧的 get_xorb_data 只会傻重试 5 次后崩溃）
            segment_data = cas_client.get_xorb_data_with_retry(
                url=fi.url,
                url_range=fi.url_range,
                xorb_hash=xorb_hash,
                file_hash=file_hash,
            )
            segments.append(segment_data)
            total_size += len(segment_data)

            # 更新进度
            if progress_tracker:
                progress_tracker.increment_downloaded(len(segment_data))  # 更新下载字节数
                progress_tracker.increment_segments(1)  # 更新 segment 计数

        # 合并
        merged_data = b''.join(segments)

        # 完成 xorb 下载
        if progress_tracker:
            progress_tracker.complete_xorb_download(xorb_hash)

        logger.debug(
            f"[Download] Xorb {xorb_hash[:16]}... 下载完成: "
            f"{len(sorted_infos)} segments, {total_size} bytes"
        )

        return merged_data
