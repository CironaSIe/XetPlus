"""在线线性回归 - 用于 RTT/带宽预测。

实现指数加权在线线性回归，用于预测网络 RTT 和带宽。

模型形式：
    duration_secs ≈ base_time + size_mb * inv_throughput
    即：duration = intercept + slope * size

参考实现：
- Rust: xet_client/adaptive_concurrency/exp_weighted_olr.rs
- Rust: xet_client/adaptive_concurrency/rtt_prediction.rs
"""
import logging
import math
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class ExpWeightedOnlineLinearRegression:
    """指数加权在线线性回归。

    使用指数衰减权重的在线线性回归，拟合模型：
        y ~ beta0 + beta1 * x

    特点：
    - 在线更新（增量式）
    - 指数衰减（旧数据权重降低）
    - 数值稳定（避免累积误差）

    Attributes:
        lambda_: 指数衰减因子 (per sample)
        sw: 加权和 (sum of weights)
        sx: 加权 x 和 (sum of w * x)
        sy: 加权 y 和 (sum of w * y)
        sxx: 加权 x² 和 (sum of w * x²)
        sxy: 加权 xy 和 (sum of w * x * y)
        syy: 加权 y² 和 (sum of w * y²)
    """

    def __init__(self, half_life: float):
        """初始化在线线性回归模型。

        Args:
            half_life: 半衰期（样本数），旧数据权重衰减到 50% 的样本数
        """
        if half_life <= 0:
            raise ValueError(f"half_life 必须 > 0: {half_life}")

        # 指数衰减因子：lambda = 2^(-1/half_life)
        self.lambda_ = math.pow(2.0, -1.0 / half_life)

        # 加权和统计量
        self.sw = 0.0   # sum of weights
        self.sx = 0.0   # sum of w * x
        self.sy = 0.0   # sum of w * y
        self.sxx = 0.0  # sum of w * x²
        self.sxy = 0.0  # sum of w * x * y
        self.syy = 0.0  # sum of w * y²

        logger.debug(f"[OnlineRegression] 初始化: half_life={half_life:.1f}, lambda={self.lambda_:.4f}")

    def update(self, weight: float, x: float, y: float) -> None:
        """更新模型（添加新观测）。

        Args:
            weight: 样本权重（基础权重，衰减由内部处理）
            x: 自变量值
            y: 因变量值
        """
        # 1. 对所有统计量应用衰减
        self.sw *= self.lambda_
        self.sx *= self.lambda_
        self.sy *= self.lambda_
        self.sxx *= self.lambda_
        self.sxy *= self.lambda_
        self.syy *= self.lambda_

        # 2. 添加新的加权贡献
        wx = weight * x
        wy = weight * y

        self.sw += weight
        self.sx += wx
        self.sy += wy
        self.sxx += wx * x   # w * x²
        self.sxy += wx * y   # w * x * y
        self.syy += wy * y   # w * y²

    def predict(self, x0: float) -> Tuple[Optional[float], Optional[float]]:
        """预测给定 x 值的 y 均值和标准差。

        Args:
            x0: 预测点的 x 值

        Returns:
            (mean, std_dev) 元组：
            - mean: 预测的 y 均值，模型不可识别时返回 None
            - std_dev: 预测的标准差，自由度不足时返回 None
        """
        # 检查正规矩阵是否可逆
        delta = self.sw * self.sxx - self.sx * self.sx
        if abs(delta) < 1e-12:
            # 无法估计 beta0/beta1
            return (None, None)

        # 估计系数 beta0, beta1
        beta0 = (self.sxx * self.sy - self.sx * self.sxy) / delta
        beta1 = (self.sw * self.sxy - self.sx * self.sy) / delta
        mean = beta0 + beta1 * x0

        # 有效自由度：sw - 2（两个参数）
        df = self.sw - 2.0
        if df <= 0.0:
            # 均值可定义，但方差估计不可信
            return (mean, None)

        # 残差平方和（加权）
        rss = self.syy - beta0 * self.sy - beta1 * self.sxy

        # 防止数值问题：sigma² 不能为负
        sigma2 = max(0.0, rss / df)

        # 预测均值的方差：
        # var_mean = sigma² * (Sxx - 2 Sx x0 + Sw x0²) / delta
        quad = self.sxx - 2.0 * self.sx * x0 + self.sw * x0 * x0
        var_mean = sigma2 * quad / delta

        if var_mean < 0.0:
            # 数值噪声，截断到 0
            var_mean = 0.0

        std_dev = math.sqrt(var_mean)
        return (mean, std_dev)

    def coefficients(self) -> Optional[Tuple[float, float]]:
        """获取当前回归系数。

        Returns:
            (beta0, beta1) 元组，模型不可识别时返回 None
        """
        delta = self.sw * self.sxx - self.sx * self.sx
        if abs(delta) < 1e-12:
            return None

        beta0 = (self.sxx * self.sy - self.sx * self.sxy) / delta
        beta1 = (self.sw * self.sxy - self.sx * self.sy) / delta
        return (beta0, beta1)


# 大小单位：使用 MB 以保持数值稳定
BASE_SIZE_UNIT = 1024.0 * 1024.0  # 1 MB in bytes


class RTTPredictor:
    """RTT 预测器 - 使用在线线性回归预测网络 RTT。

    模型形式：
        duration_secs ≈ base_time_secs + size_bytes * inv_throughput

    即：
        duration_secs ≈ intercept + slope * size_mb

    其中：
        - intercept 是基础时间（网络往返时间）
        - slope 是每 MB 数据的传输时间（1 / 吞吐量）

    特点：
    - 自动考虑并发级别（concurrency scaling）
    - 指数衰减（适应网络状态变化）
    - 数值稳定（使用 MB 为单位）

    Attributes:
        model: 底层线性回归模型
    """

    def __init__(self, decay_half_life_count: float = 100.0):
        """初始化 RTT 预测器。

        Args:
            decay_half_life_count: 衰减半衰期（样本数），默认 100
        """
        self.model = ExpWeightedOnlineLinearRegression(decay_half_life_count)
        logger.debug(f"[RTTPredictor] 初始化: half_life={decay_half_life_count}")

    def update(
        self,
        size_bytes: int,
        duration_secs: float,
        avg_concurrent: float = 1.0,
        weight: float = 1.0,
    ) -> None:
        """更新 RTT 模型（添加新观测）。

        Args:
            size_bytes: 传输大小（字节）
            duration_secs: 传输耗时（秒）
            avg_concurrent: 平均并发数（默认 1.0）
            weight: 样本权重（默认 1.0）
        """
        w = max(0.0, weight)
        x = size_bytes / BASE_SIZE_UNIT  # 转换为 MB
        concurrency_factor = max(1.0, avg_concurrent)

        # 考虑并发级别：并发越高，每个连接的有效大小越大
        x_eff = x * concurrency_factor
        y = max(1e-9, duration_secs)  # 防止 0

        self.model.update(w, x_eff, y)

    def predict(
        self,
        size_bytes: int,
        avg_concurrent: float = 1.0,
    ) -> Tuple[Optional[float], Optional[float]]:
        """预测给定大小和并发级别的 RTT。

        Args:
            size_bytes: 传输大小（字节）
            avg_concurrent: 平均并发数（默认 1.0）

        Returns:
            (mean, std_dev) 元组：
            - mean: 预测的 RTT（秒），无法预测时返回 None
            - std_dev: 预测的标准差（秒），无法计算时返回 None
        """
        x = size_bytes / BASE_SIZE_UNIT
        concurrency_factor = max(1.0, avg_concurrent)
        x_eff = x * concurrency_factor

        mean, std_dev = self.model.predict(x_eff)
        # 确保预测值非负
        if mean is not None:
            mean = max(0.0, mean)
        return (mean, std_dev)

    def predicted_rtt(self, size_bytes: int, avg_concurrent: float = 1.0) -> Optional[float]:
        """预测 RTT（仅返回均值）。

        Args:
            size_bytes: 传输大小（字节）
            avg_concurrent: 平均并发数（默认 1.0）

        Returns:
            预测的 RTT（秒），无法预测时返回 None
        """
        mean, _ = self.predict(size_bytes, avg_concurrent)
        return mean

    def predicted_bandwidth(self) -> Optional[float]:
        """预测带宽（字节/秒）。

        Returns:
            预测的带宽（字节/秒），无法预测时返回 None
        """
        query_bytes = 10 * 1024 * 1024  # 10 MB

        # 计算传输 10 MB 需要的时间（单连接）
        min_rtt = self.predicted_rtt(query_bytes, 1.0)
        if min_rtt is None:
            return None

        # 带宽 = 大小 / 时间
        return query_bytes / max(1e-6, min_rtt)
