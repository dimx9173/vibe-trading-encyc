"""無 scipy 的統計函式 (rankdata + pearson) — 純 NumPy.

scipy 未安裝 (驗證過) — screener 的 IC 計算需要 Spearman 秩相關,
用 rank 轉換 + Pearson 實現 (與 scipy.stats.spearmanr 等價).
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def rankdata(values: np.ndarray) -> np.ndarray:
    """平均秩 (average ranks, 同 scipy.stats.rankdata 預設)."""
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty_like(arr)
    ranks[order] = np.arange(len(arr), dtype=float)
    # 平均同值秩
    sorted_vals = arr[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Pearson 相關係數 (NaN-safe)."""
    if len(x) != len(y) or len(x) < 2:
        return None
    xm = x - np.mean(x)
    ym = y - np.mean(y)
    denom = np.sqrt(np.sum(xm ** 2) * np.sum(ym ** 2))
    if denom < 1e-12:
        return None
    return float(np.sum(xm * ym) / denom)


def spearmanr(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    """Spearman 秩相關係數 (scipy.stats.spearmanr 等價)."""
    if len(x) != len(y) or len(x) < 2:
        return None
    return pearson(rankdata(x), rankdata(y))
