"""動能因子（Momentum Factors）

針對加密貨幣永續合約市場適配的動能因子。
"""
import pandas as pd
from dataclasses import dataclass
from .base import AlphaMetadata


@dataclass
class Momentum12_1:
    """12-1 動能因子

    經典動能因子：過去 12 期收益減去最近 1 期收益。
    排除最近 1 期以減少短期反轉效應。

    Formula: r_{t-12,t-1} - r_{t-1,t}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="momentum_12_1",
        formula=r"r_{t-12,t-1} - r_{t-1,t}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=13,
        description="12-1 momentum: 12-period return excluding most recent period",
        tags=["momentum", "trend"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        ret_12 = close.pct_change(12)
        ret_1 = close.pct_change(1)
        return ret_12 - ret_1


@dataclass
class MomentumWeighted:
    """指數加權動能因子

    對過去 N 期收益進行指數加權，近期權重更高。
    比簡單動能對近期趨勢更敏感。

    Formula: \\sum_{i=1}^{N} w_i * r_{t-i}, w_i = e^{-\\lambda i}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="momentum_weighted",
        formula=r"\sum_{i=1}^{N} e^{-\lambda i} r_{t-i}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=21,
        description="Exponentially weighted momentum (20-period, lambda=0.1)",
        tags=["momentum", "trend", "weighted"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        returns = data["close"].pct_change()
        weights = [0.9**i for i in range(20)]
        weights = [w / sum(weights) for w in weights]

        result = pd.Series(0.0, index=data.index)
        for i, w in enumerate(weights):
            result += w * returns.shift(i + 1)

        return result


@dataclass
class RateOfChange:
    """變化率因子（ROC）

    衡量價格變化速度，對趨勢轉折點敏感。

    Formula: (P_t - P_{t-N}) / P_{t-N}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="rate_of_change",
        formula=r"\frac{P_t - P_{t-N}}{P_{t-N}}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=11,
        description="Rate of change over 10 periods",
        tags=["momentum", "speed"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        return (close - close.shift(10)) / close.shift(10)


@dataclass
class PriceDistance:
    """價格距離因子

    當前價格相對於 N 期最高/最低價的距離。
    衡量價格在區間中的位置。

    Formula: (P_t - min(P_{t-N:t})) / (max(P_{t-N:t}) - min(P_{t-N:t}))
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="price_distance",
        formula=r"\frac{P_t - \min(P)}{\max(P) - \min(P)}",
        universe="crypto_perp",
        column_dependencies=["close", "high", "low"],
        warmup_periods=21,
        description="Price position within 20-period range [0,1]",
        tags=["momentum", "range"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        high_20 = data["high"].rolling(20).max()
        low_20 = data["low"].rolling(20).min()

        price_range = high_20 - low_20
        price_range = price_range.replace(0, 1e-8)

        return (close - low_20) / price_range


@dataclass
class TrendStrength:
    """趨勢強度因子

    衡量趨勢的持續性和強度。
    基於線性回歸斜率的 t-statistic。

    Formula: t-stat of linear regression slope over N periods
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="trend_strength",
        formula=r"t\text{-stat of } \beta \text{ in } P_t = \alpha + \beta t",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=21,
        description="Trend strength via regression t-statistic (20-period)",
        tags=["momentum", "trend", "regression"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        n = 20

        def calc_tstat(x: pd.Series) -> float:
            if len(x) < n:
                return 0.0
            y = x.values
            x_arr = list(range(len(y)))
            x_mean = sum(x_arr) / len(x_arr)
            y_mean = sum(y) / len(y)

            numerator = sum((x_arr[i] - x_mean) * (y[i] - y_mean) for i in range(len(y)))
            denominator = sum((x_arr[i] - x_mean) ** 2 for i in range(len(y)))

            if denominator == 0:
                return 0.0

            beta = numerator / denominator
            residuals = [y[i] - (y_mean + beta * (x_arr[i] - x_mean)) for i in range(len(y))]
            se = (sum(r**2 for r in residuals) / (len(y) - 2)) ** 0.5 if len(y) > 2 else 1.0

            if se == 0:
                return 0.0

            return beta / se

        return close.rolling(n).apply(calc_tstat, raw=False)
