"""因子篩選評分 (Phase 3) — IC/IR/Sharpe, 用現有 metrics.

PIT 紀律: 因子值用 t 期資料, forward return 用 t+1 開盤 (可成交價, 無 lookahead).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from vibe_trading.factors.vm import evaluate_series
from vibe_trading.factors.stats import pearson, rankdata


def make_screener(klines: List[Any]) -> Dict[str, Any]:
    """建構評分器: 從 K 線建因子序列 + forward returns (無 lookahead).

    forward return[t] = open[t+1] / close[t] - 1 (下一 bar 開盤可成交)
    最後 bar 無 forward return → 0 (佔位, 評分時剔除).

    Returns: {"series": dict, "fwd": np.ndarray, "closes": np.ndarray}
    """
    closes = np.array([k.close for k in klines], dtype=float)
    opens = np.array([k.open for k in klines], dtype=float)

    from vibe_trading.factors.microstructure import compute_all
    micro = compute_all(klines)

    log_ret = np.zeros(len(closes))
    log_ret[1:] = np.diff(np.log(np.maximum(closes, 1e-12)))

    series: Dict[str, np.ndarray] = {
        "close": closes,
        "open": opens,
        "vol": np.array([k.volume for k in klines], dtype=float),
        "ret": log_ret,
        **{f"micro_{k}": np.full(len(closes), v) for k, v in micro.items()},
    }

    fwd = np.zeros(len(closes))
    fwd[:-1] = opens[1:] / np.maximum(closes[:-1], 1e-12) - 1.0

    return {"series": series, "fwd": fwd, "closes": closes}


def score_formula(
    ast: Any,
    series: Dict[str, np.ndarray],
    fwd: np.ndarray,
    min_samples: int = 20,
) -> Optional[Dict]:
    """單公式評分: IC / IR / Sharpe / 樣本數.

    Returns:
        {"ic": float, "ir": float, "sharpe": float, "samples": int} 或 None (無效).
    """
    factor = evaluate_series(ast, series)
    if factor is None or factor.size < min_samples:
        return None

    # 剔除最後 bar (無 forward return) 與 NaN
    mask = np.isfinite(factor) & np.isfinite(fwd)
    if mask.sum() < min_samples:
        return None
    f = factor[mask][:-1]  # 剔除最後 bar
    r = fwd[mask][:-1]
    if len(f) < min_samples:
        return None

    # IC: Spearman 秩相關 (無 scipy — 用 Pearson 於 rank 轉換)
    f_rank = rankdata(f)
    r_rank = rankdata(r)
    ic = pearson(f_rank, r_rank)
    if ic is None or not np.isfinite(ic):
        return None

    # IR: 單期 IC 的穩健近似 — 用 IC 與因子變異的比值 (無多期 IC 序列時)
    # 註: 嚴格 IR = mean(IC_series)/std(IC_series) 需多期滾動 IC; 此處用簡化代理
    f_std = float(np.std(f_rank))
    ir = float(ic / (f_std + 1e-12)) if f_std > 1e-12 else 0.0

    # 多空 Sharpe (簡化: 因子標準化 × 收益)
    f_std = float(np.std(f))
    if f_std < 1e-12:
        return None
    scaled = (f - float(np.mean(f))) / f_std
    strat_ret = scaled * r
    sharpe = float(np.mean(strat_ret) / (np.std(strat_ret) + 1e-12) * np.sqrt(365.0))

    return {"ic": float(ic), "ir": ir, "sharpe": sharpe, "samples": len(f)}


def passes_gate(score: Optional[Dict], ic_threshold: float = 0.05) -> bool:
    """達標判定: |IC| ≥ threshold 且 Sharpe > 0 (具預測方向)."""
    if score is None:
        return False
    return abs(score["ic"]) >= ic_threshold and score["sharpe"] > 0
