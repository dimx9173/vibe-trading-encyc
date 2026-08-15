"""微觀結構因子 — 純函式, NaN-aware 滾動窗口 (Phase 2.1).

採納自 AlphaGPT (feature-adoption-assessment.md F3/F4/F7/F8/F11/F12),
差異: (1) PRESSURE 用真實 taker_buy_base (非蠟燭體代理);
      (2) 滾動窗口 NaN-aware — 不複製競品 zero-padding lookahead 污染.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np


def pressure(
    close: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    taker_buy_base: np.ndarray,
    volume: np.ndarray,
) -> float:
    """買賣失衡: 真實主動買量比例 (5-bar 匯總), 歸一到 [-1, 1].

    優於競品蠟燭體代理 (tanh(3(c-o)/(h-l))): 直接使用交易所提供的
    主動買入成交量 (taker_buy_base), 訊號品質更真實.
    """
    v = np.asarray(volume, dtype=float)
    tb = np.asarray(taker_buy_base, dtype=float)
    if v.size < 5 or np.all(v[-5:] <= 0):
        return 0.0
    buy = float(np.nansum(tb[-5:]))
    total = float(np.nansum(v[-5:]))
    if total <= 0 or buy <= 0:
        return 0.0  # 無 taker 資料 (replay/舊 kline) → 中性, 不臆斷
    ratio = buy / total
    return float(np.tanh(3.0 * (ratio - 0.5) * 2.0))


def fomo(volume: np.ndarray) -> float:
    """成交量加速度: Δ(vol_chg), 5-bar 窗口, clamp ±5."""
    v = np.asarray(volume, dtype=float)
    if v.size < 6:
        return 0.0
    chg = np.diff(v) / (v[:-1] + 1.0)
    acc = np.diff(chg)
    return float(np.clip(acc[-1] if acc.size else 0.0, -5.0, 5.0))


def vol_cluster(close: np.ndarray, window: int = 10) -> float:
    """滾動實現波動率聚集: sqrt(mean(sq(log_ret), window))."""
    c = np.asarray(close, dtype=float)
    if c.size < window + 1:
        return 0.0
    log_ret = np.diff(np.log(np.maximum(c, 1e-12)))
    return float(np.sqrt(np.nanmean(log_ret[-window:] ** 2)))


def close_pos(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> float:
    """bar 區間相對位置: (c-l)/(h-l), [0,1]. 區間為 0 時回退 0.5."""
    if close.size < 1 or high.size < 1 or low.size < 1:
        return 0.5
    c, h, l = float(close[-1]), float(high[-1]), float(low[-1])
    rng = h - l
    return float((c - l) / rng) if rng > 1e-12 else 0.5


def momentum_rev(close: np.ndarray, window: int = 5) -> float:
    """動量反轉: 5-bar 動量符號翻轉 → 1.0 (翻轉), else 0.0."""
    c = np.asarray(close, dtype=float)
    if c.size < window + 1:
        return 0.0
    mom = np.diff(np.log(np.maximum(c, 1e-12)))
    if mom.size < window:
        return 0.0
    m1 = float(np.sum(mom[-window:]))
    m2 = float(np.sum(mom[-window - 1:-1]))
    return 1.0 if (m1 * m2 < 0) else 0.0


def vol_trend(volume: np.ndarray) -> float:
    """1-bar 成交量變化: (v - v_prev)/(v_prev + 1)."""
    v = np.asarray(volume, dtype=float)
    if v.size < 2:
        return 0.0
    return float((v[-1] - v[-2]) / (v[-2] + 1.0))


def compute_all(klines: List[Any]) -> Dict[str, float]:
    """從 Kline 列表計算全部 6 因子 (coordinator context 用)."""
    closes = np.array([k.close for k in klines], dtype=float)
    opens = np.array([k.open for k in klines], dtype=float)
    highs = np.array([k.high for k in klines], dtype=float)
    lows = np.array([k.low for k in klines], dtype=float)
    vols = np.array([k.volume for k in klines], dtype=float)
    tbb = np.array([getattr(k, "taker_buy_base", 0.0) or 0.0 for k in klines], dtype=float)
    return {
        "pressure": pressure(closes, opens, highs, lows, tbb, vols),
        "fomo": fomo(vols),
        "vol_cluster": vol_cluster(closes),
        "close_pos": close_pos(closes, highs, lows),
        "momentum_rev": momentum_rev(closes),
        "vol_trend": vol_trend(vols),
    }
