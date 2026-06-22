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

    def __init__(self, description: str = "Downloading", show_filename: bool = True):
        self.description = description
        self.show_filename = show_filename
        self.progress = None
        self.task = None
        self.console = Console()
        self._filename_shown = False

    def __enter__(self):
        # 如果需要显示文件名，先单独打印一行
        if self.show_filename and not self._filename_shown:
            self.console.print(f"[bold blue]📥 {self.description}[/bold blue]")
            self._filename_shown = True

        # 进度条：图标 + Xorb/Segment 信息 | 进度条 | 百分比 | 已下载/总大小 | 速度 | ETA
        self.progress = Progress(
            TextColumn("[cyan]{task.description}"),  # Xorb/Segment 信息
            BarColumn(bar_width=None, style="cyan", complete_style="green"),
            "[progress.percentage]{task.percentage:>6.2f}%",  # 两位小数
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=self.console,
            transient=False,  # 完成后保留进度条
            expand=True,  # 自动适应终端宽度
        )
        self.progress.__enter__()
        # 初始描述为空，等待第一次 update
        self.task = self.progress.add_task("", total=100)
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
            total_segments = stats.get("total_segments", 0)
            completed_segments = stats.get("completed_segments", 0)

            # 构建简洁的描述：图标 + 位置信息
            desc_parts = []

            # 始终显示 Xorb 进度
            if total_xorbs > 0:
                desc_parts.append(f"📦 {completed_xorbs}/{total_xorbs}")

            # 只要 segment 总数大于 0，就显示段进度（不带"段"字）
            if total_segments > 0:
                desc_parts.append(f"🔗 {completed_segments}/{total_segments}")

            # 如果没有任何信息，使用默认图标
            if not desc_parts:
                description = "⬇️  下载中"
            else:
                description = " | ".join(desc_parts)

            # Rich 需要字节数来正确格式化速度和已下载量
            assembled_bytes = stats.get("assembled_bytes", 0)
            total_bytes = stats.get("total_bytes", 0)

            # 如果 total_bytes 为 0（未知），传递 None 给 Rich
            total = total_bytes if total_bytes > 0 else None

            self.progress.update(
                self.task,
                description=description,
                completed=assembled_bytes,
                total=total,
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

        # 只在百分比变化时更新（减少闪烁）
        if int(pct) > self.last_pct:
            bar_width = 40
            filled = int(pct / 100 * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)

            # 构建进度字符串 - 使用更紧凑的格式
            progress_parts = [
                f"\r📥 {pct:>5.1f}% [{bar}]",
                f"{self._format_bytes(assembled)}/{self._format_bytes(total)}",
                f"⚡ {self._format_bytes(speed)}/s",
                f"⏱ {self._format_time(eta)}",
            ]

            # 添加 xorb 进度（紧凑格式）
            if total_xorbs > 0:
                xorb_str = f"📦 {completed_xorbs}/{total_xorbs}"
                if active_xorbs > 0:
                    xorb_str += f"(+{active_xorbs})"
                progress_parts.append(xorb_str)

            # 添加 segment 进度（仅当分段下载时）
            if total_segments > 0 and total_segments > total_xorbs:
                progress_parts.append(f"🧩 {completed_segments}/{total_segments}")

            progress_str = " │ ".join(progress_parts)
            sys.stdout.write(progress_str + " " * 10)  # 额外空格清除旧内容
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
