"""成交量因子（Volume Factors）

基於成交量和持倉量的因子，衡量市場參與度和資金流向。
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from .base import AlphaMetadata


@dataclass
class VolumeRatio:
    """成交量比率因子

    當前成交量相對於過去 N 期平均成交量的比率。
    衡量交易活躍度的變化。

    Formula: V_t / MA(V, N)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="volume_ratio",
        formula=r"V_t / MA(V, N)",
        universe="crypto_perp",
        column_dependencies=["volume"],
        warmup_periods=21,
        description="Current volume relative to 20-period average",
        tags=["volume", "activity"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        volume = data["volume"]
        ma_volume = volume.rolling(20).mean()
        result = volume / ma_volume.replace(0, 1e-8)
        return pd.Series(result, index=data.index)


@dataclass
class OBV:
    """能量潮（On-Balance Volume）

    累積成交量指標，根據價格變化方向累加或減去成交量。
    衡量資金的淨流向。

    Formula: OBV_t = OBV_{t-1} + sign(C_t - C_{t-1}) * V_t
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="obv",
        formula=r"OBV_t = OBV_{t-1} + sign(C_t - C_{t-1}) * V_t",
        universe="crypto_perp",
        column_dependencies=["close", "volume"],
        warmup_periods=1,
        description="On-Balance Volume (cumulative volume flow)",
        tags=["volume", "flow", "cumulative"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        volume = data["volume"]

        direction = np.sign(close.diff())
        obv_values = (direction * volume).cumsum()

        return pd.Series(obv_values, index=data.index)


@dataclass
class VWAP:
    """成交量加權平均價格（VWAP）

    衡量平均交易價格，常用於機構交易基準。
    價格高於 VWAP 表示買方強勢，低於表示賣方強勢。

    Formula: VWAP = sum(P_i * V_i) / sum(V_i)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="vwap",
        formula=r"VWAP = \frac{\sum(P_i \times V_i)}{\sum(V_i)}",
        universe="crypto_perp",
        column_dependencies=["close", "volume"],
        warmup_periods=21,
        description="Volume-weighted average price (20-period)",
        tags=["volume", "price", "benchmark"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        typical_price = (data["high"] + data["low"] + data["close"]) / 3
        pv = typical_price * data["volume"]

        cum_pv = pv.rolling(20).sum()
        cum_v = data["volume"].rolling(20).sum()

        result = cum_pv / cum_v.replace(0, 1e-8)
        return pd.Series(result, index=data.index)


@dataclass
class VolumePriceTrend:
    """量價趨勢（VPT）

    結合價格變化和成交量的指標，衡量資金流向的趨勢。
    類似 OBV 但考慮價格變化幅度。

    Formula: VPT_t = VPT_{t-1} + V_t * (C_t - C_{t-1}) / C_{t-1}
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="volume_price_trend",
        formula=r"VPT_t = VPT_{t-1} + V_t \times \frac{C_t - C_{t-1}}{C_{t-1}}",
        universe="crypto_perp",
        column_dependencies=["close", "volume"],
        warmup_periods=1,
        description="Volume Price Trend (cumulative price-adjusted volume)",
        tags=["volume", "trend", "flow"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        volume = data["volume"]

        price_change = close.pct_change()
        vpt_values = (volume * price_change).cumsum()

        return pd.Series(vpt_values, index=data.index)


@dataclass
class MoneyFlowIndex:
    """資金流向指標（MFI）

    結合價格和成交量的振盪指標，類似 RSI 但考慮成交量。
    衡量資金流入流出的強度。

    Formula: MFI = 100 - 100 / (1 + MF Ratio)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="money_flow_index",
        formula=r"MFI = 100 - \frac{100}{1 + MF Ratio}",
        universe="crypto_perp",
        column_dependencies=["high", "low", "close", "volume"],
        warmup_periods=15,
        description="Money Flow Index over 14 periods [0, 100]",
        tags=["volume", "oscillator", "flow"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        typical_price = (data["high"] + data["low"] + data["close"]) / 3
        raw_money_flow = typical_price * data["volume"]

        tp_diff = typical_price.diff()
        positive_flow = raw_money_flow.where(tp_diff > 0, 0)
        negative_flow = raw_money_flow.where(tp_diff < 0, 0)

        pos_sum = positive_flow.rolling(14).sum()
        neg_sum = negative_flow.rolling(14).sum()

        mf_ratio = pos_sum / neg_sum.replace(0, 1e-8)
        mfi = 100 - (100 / (1 + mf_ratio))

        return pd.Series(mfi, index=data.index)


@dataclass
class VolumeVolatility:
    """成交量波動率

    成交量的標準差，衡量交易活躍度的穩定性。
    高波動表示市場情緒不穩定。

    Formula: sigma_V = std(V, N) / mean(V, N)
    Universe: crypto_perp
    """

    __alpha_meta__ = AlphaMetadata(
        name="volume_volatility",
        formula=r"\sigma_V = \frac{std(V, N)}{mean(V, N)}",
        universe="crypto_perp",
        column_dependencies=["volume"],
        warmup_periods=21,
        description="Coefficient of variation of volume over 20 periods",
        tags=["volume", "volatility", "stability"],
    )

    def compute(self, data: pd.DataFrame) -> pd.Series:
        volume = data["volume"]
        vol_std = volume.rolling(20).std()
        vol_mean = volume.rolling(20).mean()

        result = vol_std / vol_mean.replace(0, 1e-8)
        return pd.Series(result, index=data.index)
