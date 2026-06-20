# Phase 2 开发计划 - Storage Layer (存储层)

## 目标

实现统一的文件写入接口和断点管理，支持顺序/并行写入模式，解决旧版的 Windows 文件锁和断点恢复问题。

---

## 核心设计

### 1. Writer 接口（策略模式）

```python
class FileWriter(ABC):
    """统一的文件写入接口。"""
    
    @abstractmethod
    def write_at(self, offset: int, data: bytes) -> None:
        """在指定偏移写入数据。"""
    
    @abstractmethod
    def flush(self) -> None:
        """刷新缓冲区。"""
    
    @abstractmethod
    def close(self) -> None:
        """关闭文件。"""
```

**两种实现**：
- `SequentialWriter` - 顺序写入（HDD 友好）
- `GlobalWriter` - 全局写入（已知总大小，预分配）

### 2. Checkpoint 管理

```python
@dataclass
class DownloadCheckpoint:
    """下载断点信息。"""
    file_path: str
    file_size: int
    xet_hash: str
    completed_terms: List[int]  # 已完成的 term 索引
    bytes_written: int
    last_update: float
```

**功能**：
- 保存断点到 `.xet-checkpoint.json`
- 恢复时验证文件完整性
- 支持增量更新

---

## 任务清单

### Task 2.1: 实现 Writer 接口（3 天）

#### Step 1: 基础接口定义（0.5 天）

**文件**: `xet/storage/writer.py`

```python
from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path

class FileWriter(ABC):
    """文件写入抽象接口。"""
    
    def __init__(self, path: Path, mode: str = 'wb'):
        self.path = path
        self.mode = mode
    
    @abstractmethod
    def write_at(self, offset: int, data: bytes) -> None:
        """在指定偏移写入数据。"""
        pass
    
    @abstractmethod
    def flush(self) -> None:
        """刷新缓冲区到磁盘。"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭文件句柄。"""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
```

#### Step 2: SequentialWriter 实现（1 天）

**特点**：
- 按偏移顺序写入
- 不支持随机访问
- HDD 友好（减少磁头移动）

```python
class SequentialWriter(FileWriter):
    """顺序写入器。
    
    适用场景：
    - 下载顺序与文件偏移顺序一致
    - HDD 存储（避免随机 seek）
    - 流式写入
    """
    
    def __init__(self, path: Path, mode: str = 'wb'):
        super().__init__(path, mode)
        self._fp = None
        self._current_offset = 0
    
    def write_at(self, offset: int, data: bytes) -> None:
        if offset != self._current_offset:
            raise ValueError(
                f"SequentialWriter 只支持顺序写入: "
                f"期望 offset={self._current_offset}, 实际 {offset}"
            )
        
        if self._fp is None:
            self._fp = open(self.path, self.mode)
        
        self._fp.write(data)
        self._current_offset += len(data)
```

#### Step 3: GlobalWriter 实现（1.5 天）

**特点**：
- 支持随机写入
- 预分配文件大小（避免碎片）
- 使用 `.part` 临时文件（Windows 兼容）

```python
class GlobalWriter(FileWriter):
    """全局写入器（支持随机访问）。
    
    适用场景：
    - 并行下载多个片段
    - SSD 存储
    - 需要断点续传
    
    实现细节：
    - 先写入 {path}.part 临时文件
    - 完成后重命名为目标文件（原子操作）
    - 预分配文件大小（减少碎片）
    """
    
    def __init__(self, path: Path, total_size: int):
        super().__init__(path, 'r+b')
        self.total_size = total_size
        self.part_path = path.with_suffix(path.suffix + '.part')
        self._fp = None
        self._init_file()
    
    def _init_file(self):
        """初始化临时文件并预分配大小。"""
        # 创建并预分配
        with open(self.part_path, 'wb') as f:
            f.seek(self.total_size - 1)
            f.write(b'\0')
        
        # 以读写模式打开
        self._fp = open(self.part_path, 'r+b')
    
    def write_at(self, offset: int, data: bytes) -> None:
        if offset + len(data) > self.total_size:
            raise ValueError(
                f"写入越界: offset={offset}, len={len(data)}, "
                f"total_size={self.total_size}"
            )
        
        self._fp.seek(offset)
        self._fp.write(data)
    
    def finalize(self) -> None:
        """完成写入，重命名为目标文件。"""
        self.close()
        self.part_path.rename(self.path)
```

**验收标准**：
- [ ] 两种 Writer 实现完成
- [ ] 支持 context manager (`with` 语句)
- [ ] 边界检查（越界、顺序错误）
- [ ] Windows `.part` 文件机制

---

### Task 2.2: 实现 Checkpoint 管理（2 天）

#### Step 1: Checkpoint 数据结构（0.5 天）

**文件**: `xet/storage/checkpoint.py`

```python
from dataclasses import dataclass, asdict
from typing import List, Optional
from pathlib import Path
import json
import time

@dataclass
class DownloadCheckpoint:
    """下载断点信息。"""
    file_path: str
    file_size: int
    xet_hash: str
    sha256: str
    completed_terms: List[int]
    bytes_written: int
    last_update: float
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> 'DownloadCheckpoint':
        return cls(**d)
    
    def save(self, checkpoint_path: Path) -> None:
        """保存断点到文件。"""
        with open(checkpoint_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, checkpoint_path: Path) -> Optional['DownloadCheckpoint']:
        """从文件加载断点。"""
        if not checkpoint_path.exists():
            return None
        
        try:
            with open(checkpoint_path) as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception:
            return None
```

#### Step 2: CheckpointManager（1.5 天）

```python
class CheckpointManager:
    """断点管理器。"""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.checkpoint_path = file_path.with_suffix(
            file_path.suffix + '.xet-checkpoint.json'
        )
    
    def save_checkpoint(
        self,
        checkpoint: DownloadCheckpoint
    ) -> None:
        """保存断点（原子操作）。"""
        # 先写入临时文件
        tmp_path = self.checkpoint_path.with_suffix('.tmp')
        checkpoint.save(tmp_path)
        
        # 原子重命名
        tmp_path.rename(self.checkpoint_path)
    
    def load_checkpoint(self) -> Optional[DownloadCheckpoint]:
        """加载断点。"""
        return DownloadCheckpoint.load(self.checkpoint_path)
    
    def verify_partial_file(
        self,
        checkpoint: DownloadCheckpoint
    ) -> bool:
        """验证部分下载的文件是否有效。"""
        part_path = self.file_path.with_suffix(
            self.file_path.suffix + '.part'
        )
        
        if not part_path.exists():
            return False
        
        # 检查文件大小
        actual_size = part_path.stat().st_size
        if actual_size != checkpoint.file_size:
            return False
        
        # TODO: 可选的校验已下载部分的哈希
        return True
    
    def clear(self) -> None:
        """清除断点文件。"""
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink()
```

**验收标准**：
- [ ] 断点保存/加载
- [ ] 原子写入（避免损坏）
- [ ] 部分文件验证
- [ ] 清理机制

---

### Task 2.3: 编写单元测试（2 天）

**文件**: `tests/unit/test_writer.py`

测试用例：
```python
# SequentialWriter 测试
def test_sequential_writer_basic()
def test_sequential_writer_out_of_order()  # 应该抛异常
def test_sequential_writer_context_manager()

# GlobalWriter 测试
def test_global_writer_random_access()
def test_global_writer_part_file()
def test_global_writer_finalize()
def test_global_writer_bounds_check()

# Checkpoint 测试
def test_checkpoint_save_load()
def test_checkpoint_atomic_write()
def test_checkpoint_verify_partial_file()
def test_checkpoint_corrupted_json()
```

**目标覆盖率**: 85%+

---

### Task 2.4: 集成测试（1 天）

**文件**: `tests/integration/test_storage_integration.py`

场景测试：
1. **完整下载流程** - GlobalWriter + Checkpoint
2. **断点续传** - 中断后恢复
3. **并发写入** - 多线程写入不同偏移
4. **错误恢复** - 写入失败后的状态

---

## 时间估算

| 任务 | 预计时间 |
|------|---------|
| Task 2.1 Step 1 | 4 小时 |
| Task 2.1 Step 2 | 8 小时 |
| Task 2.1 Step 3 | 12 小时 |
| Task 2.2 Step 1 | 4 小时 |
| Task 2.2 Step 2 | 12 小时 |
| Task 2.3 | 16 小时 |
| Task 2.4 | 8 小时 |
| **总计** | **64 小时** |

按每天工作 6 小时计算 = **11 个工作日**

---

## 设计决策

### 为什么用 `.part` 文件？

**问题**: Windows 文件锁导致下载中断后无法恢复

**解决方案**:
```
下载中:  target.bin.part  (写入中)
完成后:  target.bin       (重命名)
```

**优势**:
- 避免覆盖已存在的文件
- 下载中断时不留下损坏的目标文件
- 重命名是原子操作

### 为什么预分配文件大小？

**优势**:
- 减少文件碎片（尤其 HDD）
- 提前检测磁盘空间不足
- 支持随机写入

**实现**:
```python
# Linux/Unix: fallocate (快)
# Windows: SetFileValidData (快)
# 通用: seek + write (慢但兼容)
```

---

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| Windows 预分配慢 | 中 | 中 | 使用系统 API 加速 |
| 断点文件损坏 | 低 | 高 | 原子写入 + 校验 |
| 并发写入冲突 | 低 | 中 | Writer 内部加锁 |

---

## 验收标准（Phase 2 完成）

- [ ] `xet/storage/writer.py` 完成，两种 Writer 实现
- [ ] `xet/storage/checkpoint.py` 完成，断点管理
- [ ] 单元测试覆盖率 85%+
- [ ] 集成测试通过（断点续传场景）
- [ ] 所有测试通过（`pytest` 无失败）
- [ ] 文档完整

---

## 下一步（Phase 3）

完成 Phase 2 后，开始 Network Layer 开发：
- `network/cas_client.py` - CAS API 客户端
- `network/retry.py` - 重试装饰器
- `network/http_utils.py` - HTTP 工具函数

---

## 立即行动

**开始 Task 2.1 Step 1**: 定义 Writer 接口

```bash
cd ~/xetplus
vim xet/storage/writer.py
```
