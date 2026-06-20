"""低速超时检测 - 防止下载卡死在低速连接上。

传统的 timeout 只检测"无数据"，不检测"低速"。
LowSpeedTimeoutError 携带已接收字节数，支持断点续传。
"""


class LowSpeedTimeoutError(TimeoutError):
    """低速超时异常（携带已接收字节数用于断点续传）。

    当连接速度持续低于阈值（如 <50 KB/s 持续 30s）时抛出。
    携带已接收字节数，调用者可调整 Range 从断点继续。

    Attributes:
        message: 错误描述
        received: 已接收的字节数
    """

    def __init__(self, message: str, received: int = 0):
        """初始化低速超时异常。

        Args:
            message: 错误描述
            received: 已接收的字节数
        """
        super().__init__(message)
        self.received = received
