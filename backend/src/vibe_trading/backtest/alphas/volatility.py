"""波動率因子（Volatility Factors）

衡量市場波動性和風險的因子。
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from .base import AlphaMetadata


@dataclass
class RealizedVolatility:
    """實現波動率因子

    過去 N 期收益的標準差，衡量實際波動性。

    Formula: \sigma = \sqrt{\frac{1}{N}\sum_{i=1}^{N}(r_i - \bar{r})^2}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="realized_volatility",
        formula=r"\sigma = \sqrt{\frac{1}{N}\sum_{i=1}^{N}(r_i - \bar{r})^2}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=21,
        description="Realized volatility over 20 periods",
        tags=["volatility", "risk"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        returns = data["close"].pct_change()
        return returns.rolling(20).std()


@dataclass
class VolatilityRatio:
    """波動率比率因子

    短期波動率與長期波動率的比率，衡量波動率的變化趨勢。
    比率 > 1 表示波動率上升，< 1 表示波動率下降。

    Formula: \sigma_{short} / \sigma_{long}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="volatility_ratio",
        formula=r"\frac{\sigma_{short}}{\sigma_{long}}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=61,
        description="Ratio of short-term (5-period) to long-term (60-period) volatility",
        tags=["volatility", "regime"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        returns = data["close"].pct_change()
        vol_short = returns.rolling(5).std()
        vol_long = returns.rolling(60).std()
        return vol_short / vol_long.replace(0, 1e-8)


@dataclass
class ParkinsonVolatility:
    """Parkinson 波動率估計

    基於最高價和最低價的波動率估計，比收盤價波動率更有效。
    假設價格服從幾何布朗運動。

    Formula: \sigma_P = \sqrt{\frac{1}{4N\ln(2)}\sum_{i=1}^{N}(\ln(H_i/L_i))^2}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="parkinson_volatility",
        formula=r"\sigma_P = \sqrt{\frac{1}{4N\ln(2)}\sum_{i=1}^{N}(\ln(H_i/L_i))^2}",
        universe="crypto_perp",
        column_dependencies=["high", "low"],
        warmup_periods=21,
        description="Parkinson volatility estimator (20-period)",
        tags=["volatility", "range", "efficient"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        log_hl = np.log(data["high"] / data["low"])
        squared = log_hl ** 2
        factor = 1.0 / (4.0 * 20 * np.log(2))
        return np.sqrt(factor * squared.rolling(20).sum())


@dataclass
class GarmanKlassVolatility:
    """Garman-Klass 波動率估計

    結合開盤價、收盤價、最高價、最低價的波動率估計。
    比 Parkinson 更有效，特別是在有漂移的情況下。

    Formula: \sigma_{GK} = \sqrt{\frac{1}{N}\sum[0.5(\ln(H/L))^2 - (2\ln(2)-1)(\ln(C/O))^2]}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="garman_klass_volatility",
        formula=r"\sigma_{GK} = \sqrt{\frac{1}{N}\sum[0.5(\ln(H/L))^2 - (2\ln(2)-1)(\ln(C/O))^2]}",
        universe="crypto_perp",
        column_dependencies=["open", "high", "low", "close"],
        warmup_periods=21,
        description="Garman-Klass volatility estimator (20-period)",
        tags=["volatility", "efficient", "ohlc"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        log_hl = np.log(data["high"] / data["low"])
        log_co = np.log(data["close"] / data["open"])

        term1 = 0.5 * log_hl ** 2
        term2 = (2 * np.log(2) - 1) * log_co ** 2

        gk = term1 - term2
        return np.sqrt(gk.rolling(20).mean())


@dataclass
class ATR:
    """平均真實波幅（ATR）

    衡量價格波動幅度的技術指標，考慮跳空缺口。
    常用於止損設置和倉位管理。

    Formula: ATR = MA(TR, N), TR = max(H-L, |H-C_{t-1}|, |L-C_{t-1}|)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="atr",
        formula=r"ATR = MA(TR, N), TR = \max(H-L, |H-C_{t-1}|, |L-C_{t-1}|)",
        universe="crypto_perp",
        column_dependencies=["high", "low", "close"],
        warmup_periods=15,
        description="Average True Range over 14 periods",
        tags=["volatility", "technical", "tr"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        high = data["high"]
        low = data["low"]
        close = data["close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(14).mean()


@dataclass
class VolatilitySkew:
    """波動率偏度

    收益分佈的偏度，衡量波動率的對稱性。
    負偏度表示下行風險更大（常見於加密市場）。

    Formula: Skew = \frac{E[(r-\mu)^3]}{\sigma^3}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="volatility_skew",
        formula=r"Skew = \frac{E[(r-\mu)^3]}{\sigma^3}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=21,
        description="Return distribution skewness over 20 periods",
        tags=["volatility", "distribution", "risk"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        returns = data["close"].pct_change()
        return returns.rolling(20).skew()
