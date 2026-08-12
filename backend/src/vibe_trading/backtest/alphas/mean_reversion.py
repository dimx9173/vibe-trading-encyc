"""均值回歸因子（Mean Reversion Factors）

基於價格偏離均值的程度，捕捉均值回歸效應。
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from .base import AlphaMetadata


@dataclass
class RSIZScore:
    """RSI Z-Score 因子

    RSI 相對於其歷史分佈的標準化偏離。
    極端值表示超買或超賣。

    Formula: Z = (RSI - mean(RSI)) / std(RSI)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="rsi_zscore",
        formula=r"Z = \frac{RSI - \mu_{RSI}}{\sigma_{RSI}}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=35,
        description="RSI z-score over 14-period RSI and 20-period normalization",
        tags=["mean-reversion", "oscillator", "standardized"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        delta = close.diff()

        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss.replace(0, 1e-8)
        rsi = 100 - (100 / (1 + rs))
        rsi = pd.Series(rsi, index=data.index)

        rsi_mean = rsi.rolling(20).mean()
        rsi_std = rsi.rolling(20).std()

        zscore = (rsi - rsi_mean) / rsi_std.replace(0, 1e-8)

        return pd.Series(zscore, index=data.index)


@dataclass
class BollingerBandWidth:
    """布林帶寬度因子

    布林帶寬度相對於其歷史的標準化。
    窄帶表示低波動，可能即將突破。

    Formula: BBW = (Upper - Lower) / Middle
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="bollinger_band_width",
        formula=r"BBW = \frac{Upper - Lower}{Middle}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=21,
        description="Bollinger Band width normalized by middle band",
        tags=["mean-reversion", "volatility", "bands"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]

        middle = close.rolling(20).mean()
        std = close.rolling(20).std()

        upper = middle + 2 * std
        lower = middle - 2 * std

        bbw = (upper - lower) / middle.replace(0, 1e-8)

        return pd.Series(bbw, index=data.index)


@dataclass
class PriceToMA:
    """價格偏離均線因子

    價格相對於移動平均線的偏離百分比。
    衡量價格偏離均衡水平的程度。

    Formula: (P - MA) / MA
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="price_to_ma",
        formula=r"\frac{P - MA}{MA}",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=51,
        description="Price deviation from 50-period moving average",
        tags=["mean-reversion", "deviation", "trend"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        ma = close.rolling(50).mean()

        deviation = (close - ma) / ma.replace(0, 1e-8)

        return pd.Series(deviation, index=data.index)


@dataclass
class MACDHistogram:
    """MACD 柱狀圖因子

    MACD 線與信號線的差值，衡量動量變化。
    柱狀圖由正轉負或由負轉正表示趨勢反轉。

    Formula: MACD - Signal
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="macd_histogram",
        formula=r"MACD - Signal",
        universe="crypto_perp",
        column_dependencies=["close"],
        warmup_periods=35,
        description="MACD histogram (MACD line minus signal line)",
        tags=["mean-reversion", "momentum", "oscillator"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]

        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()

        macd = ema_12 - ema_26
        signal = macd.ewm(span=9, adjust=False).mean()

        histogram = macd - signal

        return pd.Series(histogram, index=data.index)


@dataclass
class StochasticOscillator:
    """隨機振盪指標因子

    當前價格在過去 N 期高低範圍中的相對位置。
    接近 100 表示超買，接近 0 表示超賣。

    Formula: %K = (C - L_N) / (H_N - L_N) * 100
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="stochastic_oscillator",
        formula=r"\%K = \frac{C - L_N}{H_N - L_N} \times 100",
        universe="crypto_perp",
        column_dependencies=["close", "high", "low"],
        warmup_periods=15,
        description="Stochastic oscillator %K over 14 periods [0, 100]",
        tags=["mean-reversion", "oscillator", "range"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        high = data["high"]
        low = data["low"]

        lowest_low = low.rolling(14).min()
        highest_high = high.rolling(14).max()

        k = (close - lowest_low) / (highest_high - lowest_low).replace(0, 1e-8) * 100

        return pd.Series(k, index=data.index)


@dataclass
class CCI:
    """商品通道指標（CCI）

    衡量價格偏離統計平均值的程度。
    極端值表示超買或超賣。

    Formula: CCI = (TP - SMA(TP)) / (0.015 * Mean Deviation)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="cci",
        formula=r"CCI = \frac{TP - SMA(TP)}{0.015 \times Mean Deviation}",
        universe="crypto_perp",
        column_dependencies=["high", "low", "close"],
        warmup_periods=21,
        description="Commodity Channel Index over 20 periods",
        tags=["mean-reversion", "oscillator", "deviation"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        typical_price = (data["high"] + data["low"] + data["close"]) / 3

        tp_sma = typical_price.rolling(20).mean()

        def mean_deviation(x):
            return np.mean(np.abs(x - x.mean()))

        md = typical_price.rolling(20).apply(mean_deviation, raw=True)

        cci = (typical_price - tp_sma) / (0.015 * md.replace(0, 1e-8))

        return pd.Series(cci, index=data.index)
