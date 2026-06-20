"""XET Storage Layer - 文件写入和断点管理。

提供统一的文件写入接口和断点续传功能。
"""

from .writer import (
    FileWriter,
    SequentialWriter,
    GlobalWriter,
    create_writer,
)

from .checkpoint import (
    DownloadCheckpoint,
    CheckpointManager,
    create_checkpoint,
)

__all__ = [
    # Writer
    'FileWriter',
    'SequentialWriter',
    'GlobalWriter',
    'create_writer',

    # Checkpoint
    'DownloadCheckpoint',
    'CheckpointManager',
    'create_checkpoint',
]
