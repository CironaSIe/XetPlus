# Phase 4 开发计划 - Pipeline Layer (流水线层)

## 目标

实现文件重建的完整流水线：从 reconstruction 响应到最终文件输出，支持并行下载、断点续传、进度跟踪。

---

## 架构概览

```
FileReconstructor (核心协调器)
├── DownloadScheduler (调度器)
│   ├── 解析 reconstruction → 生成 xorb 下载任务
│   ├── 并行下载管理 (使用 ACC + URLRefreshCoordinator)
│   └── 任务队列 + 线程池
├── ChunkAssembler (组装器)
│   ├── 解压 xorb (merkle-hash-rust)
│   ├── 应用 term operations (copy/reference)
│   └── 流式写入目标文件
├── CheckpointManager (检查点管理器)
│   ├── 保存/恢复下载进度
│   ├── 记录已完成的 xorb
│   └── 支持中断后恢复
└── ProgressTracker (进度跟踪器)
    ├── 实时统计 (下载速度、ETA、完成百分比)
    ├── 回调机制 (供 CLI 更新 UI)
    └── 线程安全计数器
```

---

## 核心组件设计

### 1. FileReconstructor (文件重建协调器)

**职责**: 
- 整合所有子组件
- 执行完整的文件重建流程
- 错误处理和资源清理

```python
class FileReconstructor:
    """文件重建协调器 - Phase 4 核心组件。"""
    
    def __init__(
        self,
        cas_client: CASClient,
        output_path: Path,
        temp_dir: Path,
        checkpoint_path: Optional[Path] = None,
        max_workers: int = 4,
        progress_callback: Optional[Callable] = None,
    ):
        self.cas_client = cas_client
        self.output_path = output_path
        self.temp_dir = temp_dir
        self.checkpoint_manager = CheckpointManager(checkpoint_path)
        self.progress_tracker = ProgressTracker(progress_callback)
        self.scheduler = DownloadScheduler(
            cas_client=cas_client,
            max_workers=max_workers,
            progress_tracker=self.progress_tracker,
            checkpoint_manager=self.checkpoint_manager,
        )
        self.assembler = ChunkAssembler(temp_dir=temp_dir)
    
    def reconstruct_file(
        self,
        file_hash: str,
        expected_size: int,
        resume: bool = True,
    ) -> Path:
        """重建文件 (端到端流程)。
        
        Args:
            file_hash: 文件的 MerkleHash
            expected_size: 预期文件大小 (用于进度计算)
            resume: 是否尝试从 checkpoint 恢复
        
        Returns:
            输出文件路径
        
        Raises:
            ReconstructionError: 重建失败
        """
        # 1. 获取 reconstruction 信息
        recon = self.cas_client.get_reconstruction(file_hash)
        
        # 2. 检查 checkpoint (可选)
        checkpoint = None
        if resume and self.checkpoint_manager:
            checkpoint = self.checkpoint_manager.load(file_hash)
        
        # 3. 下载所有 xorb
        xorb_data_map = self.scheduler.download_all_xorbs(
            recon=recon,
            file_hash=file_hash,
            checkpoint=checkpoint,
        )
        
        # 4. 组装文件
        self.assembler.assemble_file(
            recon=recon,
            xorb_data_map=xorb_data_map,
            output_path=self.output_path,
            progress_tracker=self.progress_tracker,
        )
        
        # 5. 清理 checkpoint
        if self.checkpoint_manager:
            self.checkpoint_manager.clear(file_hash)
        
        return self.output_path
```

---

### 2. DownloadScheduler (下载调度器)

**职责**:
- 解析 reconstruction 生成下载任务
- 并行下载管理 (使用线程池)
- 集成 ACC 和 URLRefreshCoordinator
- Checkpoint 增量下载

```python
class DownloadScheduler:
    """Xorb 下载调度器。"""
    
    def __init__(
        self,
        cas_client: CASClient,
        max_workers: int = 4,
        progress_tracker: Optional[ProgressTracker] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ):
        self.cas_client = cas_client
        self.max_workers = max_workers
        self.progress_tracker = progress_tracker
        self.checkpoint_manager = checkpoint_manager
        self._stop_event = threading.Event()
    
    def download_all_xorbs(
        self,
        recon: QueryReconstructionResponse,
        file_hash: str,
        checkpoint: Optional[ReconstructionCheckpoint] = None,
    ) -> Dict[str, bytes]:
        """并行下载所有 xorb。
        
        Args:
            recon: reconstruction 响应
            file_hash: 文件 hash (用于 checkpoint 保存)
            checkpoint: 已有的 checkpoint (可选)
        
        Returns:
            {xorb_hash: xorb_compressed_data} 映射
        """
        # 1. 提取所有唯一 xorb
        xorb_tasks = self._extract_xorb_tasks(recon)
        
        # 2. 过滤已下载的 xorb (从 checkpoint)
        if checkpoint:
            xorb_tasks = [
                task for task in xorb_tasks
                if task.xorb_hash not in checkpoint.completed_xorbs
            ]
        
        # 3. 并行下载
        xorb_data_map = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._download_single_xorb,
                    task,
                    file_hash,
                ): task
                for task in xorb_tasks
            }
            
            for future in as_completed(futures):
                task = futures[future]
                try:
                    xorb_hash, data = future.result()
                    xorb_data_map[xorb_hash] = data
                    
                    # 更新 checkpoint
                    if self.checkpoint_manager:
                        self.checkpoint_manager.mark_completed(
                            file_hash, xorb_hash
                        )
                
                except Exception as e:
                    logger.error(f"下载 xorb 失败: {task.xorb_hash[:16]}..., {e}")
                    # 检查是否中断
                    if self._stop_event.is_set():
                        raise KeyboardInterrupt("用户中断")
                    raise
        
        return xorb_data_map
    
    def _download_single_xorb(
        self,
        task: XorbDownloadTask,
        file_hash: str,
    ) -> Tuple[str, bytes]:
        """下载单个 xorb (使用 get_xorb_data_with_retry)。"""
        data = self.cas_client.get_xorb_data_with_retry(
            url=task.url,
            url_range=task.url_range,
            xorb_hash=task.xorb_hash,
            file_hash=file_hash,
            use_streaming=True,  # 启用低速检测
        )
        
        # 更新进度
        if self.progress_tracker:
            self.progress_tracker.increment_bytes(len(data))
        
        return task.xorb_hash, data
    
    def _extract_xorb_tasks(
        self, recon: QueryReconstructionResponse
    ) -> List[XorbDownloadTask]:
        """从 reconstruction 提取所有唯一 xorb 下载任务。"""
        tasks = []
        seen_xorbs = set()
        
        for xorb_hash, fetch_infos in recon.fetch_info.items():
            if xorb_hash in seen_xorbs:
                continue
            seen_xorbs.add(xorb_hash)
            
            # 使用第一个 fetch_info (multipart 情况下只取第一个)
            fi = fetch_infos[0]
            tasks.append(
                XorbDownloadTask(
                    xorb_hash=xorb_hash,
                    url=fi.url,
                    url_range=fi.url_range,
                )
            )
        
        return tasks
```

---

### 3. ChunkAssembler (数据组装器)

**职责**:
- 解压 xorb (调用 merkle-hash-rust)
- 应用 term operations
- 流式写入目标文件

```python
class ChunkAssembler:
    """文件数据组装器。"""
    
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def assemble_file(
        self,
        recon: QueryReconstructionResponse,
        xorb_data_map: Dict[str, bytes],
        output_path: Path,
        progress_tracker: Optional[ProgressTracker] = None,
    ) -> None:
        """组装最终文件。
        
        Args:
            recon: reconstruction 响应
            xorb_data_map: {xorb_hash: compressed_data}
            output_path: 输出文件路径
            progress_tracker: 进度跟踪器
        """
        # 1. 解压所有 xorb → chunks
        chunk_cache = self._decompress_all_xorbs(xorb_data_map)
        
        # 2. 流式写入文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'wb') as f:
            # 跳过 offset_into_first_range
            offset = recon.offset_into_first_range
            
            for term in recon.terms:
                if term.op == "copy":
                    # Copy 操作：从 chunk 读取
                    chunk_data = self._get_chunk_data(
                        chunk_hash=term.chunk_hash,
                        chunk_cache=chunk_cache,
                    )
                    
                    # 应用 offset 和 length
                    start = term.offset
                    end = start + term.unpacked_length
                    segment = chunk_data[start:end]
                    
                    f.write(segment)
                
                elif term.op == "reference":
                    # Reference 操作：从已写入的文件内容复制
                    f.flush()
                    f.seek(term.reference_offset)
                    data = f.read(term.unpacked_length)
                    f.seek(0, 2)  # 回到末尾
                    f.write(data)
                
                # 更新进度
                if progress_tracker:
                    progress_tracker.increment_assembled(term.unpacked_length)
        
        logger.info(f"文件组装完成: {output_path}")
    
    def _decompress_all_xorbs(
        self, xorb_data_map: Dict[str, bytes]
    ) -> Dict[str, bytes]:
        """解压所有 xorb，返回 {chunk_hash: decompressed_data}。"""
        from xet.storage.merkle_hash import decompress_xorb
        
        chunk_cache = {}
        
        for xorb_hash, compressed_data in xorb_data_map.items():
            # 调用 Rust 解压
            chunks = decompress_xorb(compressed_data)
            
            for chunk_hash, chunk_data in chunks.items():
                chunk_cache[chunk_hash] = chunk_data
        
        return chunk_cache
    
    def _get_chunk_data(
        self, chunk_hash: str, chunk_cache: Dict[str, bytes]
    ) -> bytes:
        """获取 chunk 数据 (从缓存)。"""
        if chunk_hash not in chunk_cache:
            raise ValueError(f"Chunk 缺失: {chunk_hash[:16]}...")
        
        return chunk_cache[chunk_hash]
```

---

### 4. CheckpointManager (检查点管理器)

**职责**:
- 保存/加载 checkpoint
- 记录已完成的 xorb
- 支持增量恢复

```python
@dataclass
class ReconstructionCheckpoint:
    """重建 checkpoint。"""
    file_hash: str
    completed_xorbs: Set[str]  # 已下载的 xorb hash
    timestamp: int
    version: int = 1


class CheckpointManager:
    """Checkpoint 管理器。"""
    
    def __init__(self, checkpoint_path: Optional[Path] = None):
        self.checkpoint_path = checkpoint_path
        self._lock = threading.Lock()
    
    def load(self, file_hash: str) -> Optional[ReconstructionCheckpoint]:
        """加载 checkpoint。"""
        if not self.checkpoint_path or not self.checkpoint_path.exists():
            return None
        
        with self._lock:
            try:
                with open(self.checkpoint_path, 'r') as f:
                    data = json.load(f)
                
                if data.get('file_hash') != file_hash:
                    return None
                
                return ReconstructionCheckpoint(
                    file_hash=data['file_hash'],
                    completed_xorbs=set(data['completed_xorbs']),
                    timestamp=data['timestamp'],
                    version=data.get('version', 1),
                )
            
            except Exception as e:
                logger.warning(f"加载 checkpoint 失败: {e}")
                return None
    
    def save(self, checkpoint: ReconstructionCheckpoint) -> None:
        """保存 checkpoint。"""
        if not self.checkpoint_path:
            return
        
        with self._lock:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.checkpoint_path, 'w') as f:
                json.dump({
                    'file_hash': checkpoint.file_hash,
                    'completed_xorbs': list(checkpoint.completed_xorbs),
                    'timestamp': checkpoint.timestamp,
                    'version': checkpoint.version,
                }, f, indent=2)
    
    def mark_completed(self, file_hash: str, xorb_hash: str) -> None:
        """标记 xorb 为已完成。"""
        checkpoint = self.load(file_hash)
        
        if not checkpoint:
            checkpoint = ReconstructionCheckpoint(
                file_hash=file_hash,
                completed_xorbs=set(),
                timestamp=int(time.time()),
            )
        
        checkpoint.completed_xorbs.add(xorb_hash)
        checkpoint.timestamp = int(time.time())
        
        self.save(checkpoint)
    
    def clear(self, file_hash: str) -> None:
        """清除 checkpoint。"""
        if not self.checkpoint_path or not self.checkpoint_path.exists():
            return
        
        with self._lock:
            try:
                checkpoint = self.load(file_hash)
                if checkpoint and checkpoint.file_hash == file_hash:
                    self.checkpoint_path.unlink()
            except Exception as e:
                logger.warning(f"清除 checkpoint 失败: {e}")
```

---

### 5. ProgressTracker (进度跟踪器)

**职责**:
- 实时统计下载进度
- 计算速度和 ETA
- 线程安全

```python
class ProgressTracker:
    """下载进度跟踪器。"""
    
    def __init__(
        self,
        total_bytes: int = 0,
        callback: Optional[Callable[[dict], None]] = None,
    ):
        self.total_bytes = total_bytes
        self.callback = callback
        
        self._downloaded_bytes = 0
        self._assembled_bytes = 0
        self._start_time = time.time()
        self._lock = threading.Lock()
    
    def increment_bytes(self, n: int) -> None:
        """增加已下载字节数。"""
        with self._lock:
            self._downloaded_bytes += n
            self._notify()
    
    def increment_assembled(self, n: int) -> None:
        """增加已组装字节数。"""
        with self._lock:
            self._assembled_bytes += n
            self._notify()
    
    def get_stats(self) -> dict:
        """获取当前统计信息。"""
        with self._lock:
            elapsed = time.time() - self._start_time
            speed = self._downloaded_bytes / elapsed if elapsed > 0 else 0
            
            if self.total_bytes > 0:
                progress_pct = (self._assembled_bytes / self.total_bytes) * 100
                remaining_bytes = self.total_bytes - self._assembled_bytes
                eta = remaining_bytes / speed if speed > 0 else 0
            else:
                progress_pct = 0
                eta = 0
            
            return {
                'downloaded_bytes': self._downloaded_bytes,
                'assembled_bytes': self._assembled_bytes,
                'total_bytes': self.total_bytes,
                'progress_pct': progress_pct,
                'speed_bps': speed,
                'eta_seconds': eta,
                'elapsed_seconds': elapsed,
            }
    
    def _notify(self) -> None:
        """通知回调函数。"""
        if self.callback:
            try:
                self.callback(self.get_stats())
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")
```

---

## 任务清单

### Task 4.1: 实现核心数据结构 (0.5 天)

**文件**: `xet/pipeline/types.py`

```python
@dataclass
class XorbDownloadTask:
    """Xorb 下载任务。"""
    xorb_hash: str
    url: str
    url_range: HttpRange

@dataclass
class ReconstructionCheckpoint:
    """重建 checkpoint。"""
    file_hash: str
    completed_xorbs: Set[str]
    timestamp: int
    version: int = 1
```

**验收标准**:
- [x] 数据类定义完整
- [ ] 类型注解正确
- [ ] Docstring 完整

---

### Task 4.2: 实现 ProgressTracker (1 天)

**文件**: `xet/pipeline/progress_tracker.py`

**验收标准**:
- [ ] 线程安全计数器
- [ ] 速度和 ETA 计算
- [ ] 回调机制
- [ ] 单元测试覆盖 90%+

---

### Task 4.3: 实现 CheckpointManager (1 天)

**文件**: `xet/pipeline/checkpoint_manager.py`

**验收标准**:
- [ ] JSON 序列化/反序列化
- [ ] 线程安全文件 I/O
- [ ] 增量保存
- [ ] 单元测试覆盖 85%+

---

### Task 4.4: 实现 DownloadScheduler (2 天)

**文件**: `xet/pipeline/download_scheduler.py`

**验收标准**:
- [ ] 解析 reconstruction
- [ ] 并行下载 (线程池)
- [ ] 集成 CASClient.get_xorb_data_with_retry
- [ ] Checkpoint 增量恢复
- [ ] 单元测试覆盖 85%+

---

### Task 4.5: 实现 ChunkAssembler (2 天)

**文件**: `xet/pipeline/chunk_assembler.py`

**验收标准**:
- [ ] Xorb 解压 (调用 merkle-hash-rust)
- [ ] Copy/Reference 操作
- [ ] 流式文件写入
- [ ] 单元测试覆盖 85%+

---

### Task 4.6: 实现 FileReconstructor (2 天)

**文件**: `xet/pipeline/file_reconstructor.py`

**验收标准**:
- [ ] 整合所有子组件
- [ ] 端到端流程
- [ ] 错误处理
- [ ] 资源清理
- [ ] 单元测试覆盖 80%+

---

### Task 4.7: 集成测试 (1.5 天)

**文件**: `tests/integration/test_pipeline_integration.py`

使用真实 API 测试：
1. 完整的文件重建流程 (测试目标 1)
2. Checkpoint 恢复
3. 并行下载
4. 进度跟踪

---

## 时间估算

| 任务 | 预计时间 |
|------|---------|
| Task 4.1 | 4 小时 |
| Task 4.2 | 8 小时 |
| Task 4.3 | 8 小时 |
| Task 4.4 | 16 小时 |
| Task 4.5 | 16 小时 |
| Task 4.6 | 16 小时 |
| Task 4.7 | 12 小时 |
| **总计** | **80 小时** |

按每天工作 8 小时计算 = **10 个工作日**

---

## 设计决策

### 为什么使用线程池而不是 asyncio？

**原因**:
1. requests 库是同步的（CASClient 基于 requests）
2. 线程池更简单，易于调试
3. Python GIL 对 I/O 密集型任务影响小

### 为什么需要 Checkpoint？

**场景**: 
- 下载大文件时网络中断
- 用户 Ctrl+C 中断
- 系统崩溃

**价值**: 恢复时不需要重新下载已完成的 xorb

---

## 验收标准（Phase 4 完成）

- [ ] 所有 6 个核心组件实现完毕
- [ ] 单元测试覆盖率 85%+
- [ ] 集成测试通过（真实 API + 测试目标 1）
- [ ] 文档完整
- [ ] 所有测试通过

---

## 下一步（Phase 5）

完成 Phase 4 后，开始 CLI Layer 开发：
- 命令行参数解析
- 进度条显示 (rich/tqdm)
- 错误处理和用户提示
- 日志配置

---

## 立即行动

**开始 Task 4.1**: 实现核心数据结构

```bash
mkdir -p xet/pipeline
touch xet/pipeline/__init__.py
vim xet/pipeline/types.py
```
