"""Alpha Zoo - 因子庫

提供 20+ 個預置因子，分為四大類：
- momentum: 動能因子（趨勢追蹤）
- volatility: 波動率因子（風險衡量）
- volume: 成交量因子（資金流向）
- mean_reversion: 均值回歸因子（反轉信號）
"""
from .base import Alpha, AlphaMetadata
from .metrics import (
    calculate_ic,
    calculate_ir,
    calculate_ic_series,
    calculate_ic_summary,
)

# 動能因子
from .momentum import (
    Momentum12_1,
    MomentumWeighted,
    RateOfChange,
    PriceDistance,
    TrendStrength,
)

# 波動率因子
from .volatility import (
    RealizedVolatility,
    VolatilityRatio,
    ParkinsonVolatility,
    GarmanKlassVolatility,
    ATR,
    VolatilitySkew,
)

# 成交量因子
from .volume import (
    VolumeRatio,
    OBV,
    VWAP,
    VolumePriceTrend,
    MoneyFlowIndex,
    VolumeVolatility,
)

# 均值回歸因子
from .mean_reversion import (
    RSIZScore,
    BollingerBandWidth,
    PriceToMA,
    MACDHistogram,
    StochasticOscillator,
    CCI,
)

__all__ = [
    # 基礎
    "Alpha",
    "AlphaMetadata",
    # 指標計算
    "calculate_ic",
    "calculate_ir",
    "calculate_ic_series",
    "calculate_ic_summary",
    # 動能因子
    "Momentum12_1",
    "MomentumWeighted",
    "RateOfChange",
    "PriceDistance",
    "TrendStrength",
    # 波動率因子
    "RealizedVolatility",
    "VolatilityRatio",
    "ParkinsonVolatility",
    "GarmanKlassVolatility",
    "ATR",
    "VolatilitySkew",
    # 成交量因子
    "VolumeRatio",
    "OBV",
    "VWAP",
    "VolumePriceTrend",
    "MoneyFlowIndex",
    "VolumeVolatility",
    # 均值回歸因子
    "RSIZScore",
    "BollingerBandWidth",
    "PriceToMA",
    "MACDHistogram",
    "StochasticOscillator",
    "CCI",
]


def get_all_alphas() -> list[type[Alpha]]:
    """獲取所有可用因子類別"""
    return [
        # 動能
        Momentum12_1,
        MomentumWeighted,
        RateOfChange,
        PriceDistance,
        TrendStrength,
        # 波動率
        RealizedVolatility,
        VolatilityRatio,
        ParkinsonVolatility,
        GarmanKlassVolatility,
        ATR,
        VolatilitySkew,
        # 成交量
        VolumeRatio,
        OBV,
        VWAP,
        VolumePriceTrend,
        MoneyFlowIndex,
        VolumeVolatility,
        # 均值回歸
        RSIZScore,
        BollingerBandWidth,
        PriceToMA,
        MACDHistogram,
        StochasticOscillator,
        CCI,
    ]


def get_alphas_by_category(category: str) -> list[type[Alpha]]:
    """按類別獲取因子

    Args:
        category: 因子類別（momentum/volatility/volume/mean_reversion）

    Returns:
        該類別的所有因子類別
    """
    categories = {
        "momentum": [
            Momentum12_1,
            MomentumWeighted,
            RateOfChange,
            PriceDistance,
            TrendStrength,
        ],
        "volatility": [
            RealizedVolatility,
            VolatilityRatio,
            ParkinsonVolatility,
            GarmanKlassVolatility,
            ATR,
            VolatilitySkew,
        ],
        "volume": [
            VolumeRatio,
            OBV,
            VWAP,
            VolumePriceTrend,
            MoneyFlowIndex,
            VolumeVolatility,
        ],
        "mean_reversion": [
            RSIZScore,
            BollingerBandWidth,
            PriceToMA,
            MACDHistogram,
            StochasticOscillator,
            CCI,
        ],
    }
    return categories.get(category, [])
