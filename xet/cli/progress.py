"""进度条封装模块。"""
import sys
from typing import Optional, Callable
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TextColumn,
)
from rich.console import Console


class ProgressDisplay:
    """进度条显示基类。"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def update(self, stats: dict):
        """更新进度。

        Args:
            stats: 进度统计，包含：
                - total_bytes: 总字节数
                - downloaded_bytes: 已下载字节数
                - assembled_bytes: 已组装字节数
                - progress_pct: 进度百分比
                - speed_bps: 下载速度（字节/秒）
                - eta_seconds: 预计剩余时间（秒）
        """
        raise NotImplementedError


class RichProgress(ProgressDisplay):
    """Rich 样式进度条。"""

    def __init__(self, description: str = "Downloading"):
        self.description = description
        self.progress = None
        self.task = None
        self.console = Console()

    def __enter__(self):
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=self.console,
        )
        self.progress.__enter__()
        self.task = self.progress.add_task(self.description, total=100)
        return self

    def __exit__(self, *args):
        if self.progress:
            self.progress.__exit__(*args)

    def update(self, stats: dict):
        """更新进度。"""
        if self.progress and self.task is not None:
            # 获取进度信息
            total_xorbs = stats.get("total_xorbs", 0)
            completed_xorbs = stats.get("completed_xorbs", 0)
            active_xorbs = stats.get("active_xorbs", 0)
            total_segments = stats.get("total_segments", 0)
            completed_segments = stats.get("completed_segments", 0)

            # 构建描述字符串
            desc_parts = [self.description]

            if total_xorbs > 0:
                xorb_info = f"Xorb: {completed_xorbs}/{total_xorbs}"
                if active_xorbs > 0:
                    xorb_info += f"(+{active_xorbs})"
                desc_parts.append(xorb_info)

            if total_segments > 0 and total_segments > total_xorbs:
                desc_parts.append(f"Seg: {completed_segments}/{total_segments}")

            description = " | ".join(desc_parts)

            self.progress.update(
                self.task,
                description=description,
                completed=stats.get("progress_pct", 0),
                total=100,
            )


class SimpleProgress(ProgressDisplay):
    """简单文本进度条。"""

    def __init__(self):
        self.last_pct = -1

    def update(self, stats: dict):
        """更新进度。"""
        pct = stats.get("progress_pct", 0)
        assembled = stats.get("assembled_bytes", 0)
        total = stats.get("total_bytes", 0)
        speed = stats.get("speed_bps", 0)
        eta = stats.get("eta_seconds", 0)

        # 获取新增的进度信息
        total_xorbs = stats.get("total_xorbs", 0)
        completed_xorbs = stats.get("completed_xorbs", 0)
        active_xorbs = stats.get("active_xorbs", 0)
        total_segments = stats.get("total_segments", 0)
        completed_segments = stats.get("completed_segments", 0)
        total_terms = stats.get("total_terms", 0)
        processed_terms = stats.get("processed_terms", 0)

        # 只在百分比变化时更新（减少闪烁）
        if int(pct) > self.last_pct:
            bar_width = 30  # 稍微缩小进度条以腾出空间
            filled = int(pct / 100 * bar_width)
            bar = "=" * filled + ">" + " " * (bar_width - filled - 1)

            # 构建进度字符串
            progress_str = (
                f"\rDownloading: {pct:>5.1f}% [{bar}] "
                f"{self._format_bytes(assembled)}/{self._format_bytes(total)}  "
                f"{self._format_bytes(speed)}/s  "
                f"ETA: {self._format_time(eta)}"
            )

            # 添加 xorb 进度
            if total_xorbs > 0:
                xorb_str = f"  Xorb: {completed_xorbs}/{total_xorbs}"
                if active_xorbs > 0:
                    xorb_str += f"(+{active_xorbs})"
                progress_str += xorb_str

            # 添加 segment 进度（可选，避免太长）
            if total_segments > 0 and total_segments > total_xorbs:
                progress_str += f"  Seg: {completed_segments}/{total_segments}"

            # 添加 term 进度（可选）
            if total_terms > 0 and total_terms > 100:  # 只在 term 数量较多时显示
                progress_str += f"  Term: {processed_terms}/{total_terms}"

            sys.stdout.write(progress_str)
            sys.stdout.flush()
            self.last_pct = int(pct)

    def __exit__(self, *args):
        # 换行，避免下一行输出覆盖进度条
        sys.stdout.write("\n")
        sys.stdout.flush()

    @staticmethod
    def _format_bytes(bytes_val: float) -> str:
        """格式化字节数。"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """格式化时间。"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m"
        else:
            return f"{seconds/3600:.1f}h"


class QuietProgress(ProgressDisplay):
    """静默模式（只在完成时输出）。"""

    def __init__(self):
        self.completed = False

    def update(self, stats: dict):
        """更新进度（静默）。"""
        pct = stats.get("progress_pct", 0)
        if pct >= 100 and not self.completed:
            assembled = stats.get("assembled_bytes", 0)
            print(f"Downloaded: {self._format_bytes(assembled)}")
            self.completed = True

    @staticmethod
    def _format_bytes(bytes_val: float) -> str:
        """格式化字节数。"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"


def create_progress(style: str = "rich", description: str = "Downloading") -> ProgressDisplay:
    """创建进度条。

    Args:
        style: 进度条样式 (rich|simple|quiet)
        description: 进度条描述

    Returns:
        ProgressDisplay 实例
    """
    if style == "rich":
        return RichProgress(description=description)
    elif style == "simple":
        return SimpleProgress()
    elif style == "quiet":
        return QuietProgress()
    else:
        raise ValueError(f"未知的进度条样式: {style}")
