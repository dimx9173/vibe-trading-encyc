"""StackVM 符號運算元虛擬機 (Phase 2.2, 採納評估 A2).

取 AlphaGPT StackVM 工具層 (純函式運算元), 不取 RL 學習循環 (修正註記 3.3).
公式 AST: [op, arg1, arg2, ...] — 例如 ["GATE", "vol_cluster", "momentum", 0.0]
巢狀支援: ["MUL", ["ADD", "a", "b"], "c"]
設計: arity-checked, NaN-safe, 無效公式 → None (不 raise) — 與競品 vm.py 一致.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

# 運算元 arity 表 (arity 不符 → None)
ARITY: Dict[str, int] = {
    "ADD": 2, "SUB": 2, "MUL": 2, "DIV": 2,
    "NEG": 1, "ABS": 1, "SIGN": 1,
    "GATE": 3, "JUMP": 1, "DECAY": 1, "DELAY1": 1, "MAX3": 1,
}

DIV_EPS = 1e-6
SERIES_LEN = 100  # 標量展開長度 (與 coordinator limit=100 對齊)


def _apply(op: str, args: List[np.ndarray]) -> Optional[np.ndarray]:
    """單一運算元求值. 錯誤 → None (不 raise)."""
    try:
        if op == "ADD":
            return args[0] + args[1]
        if op == "SUB":
            return args[0] - args[1]
        if op == "MUL":
            return args[0] * args[1]
        if op == "DIV":
            return args[0] / (args[1] + DIV_EPS)
        if op == "NEG":
            return -args[0]
        if op == "ABS":
            return np.abs(args[0])
        if op == "SIGN":
            return np.sign(args[0])
        if op == "GATE":
            cond, x, y = args
            return np.where(cond > 0, x, y)
        if op == "JUMP":
            x = args[0]
            mu = float(np.nanmean(x))
            sd = float(np.nanstd(x))
            if sd < 1e-12:
                return np.zeros_like(x)
            return np.where(np.abs((x - mu) / sd) > 3.0, 1.0, 0.0)
        if op == "DECAY":
            x = args[0]
            out = x.copy()
            if x.size > 1:
                out[1:] += 0.8 * x[:-1]
            if x.size > 2:
                out[2:] += 0.6 * x[:-2]
            return out
        if op == "DELAY1":
            x = args[0]
            out = np.zeros_like(x)
            if x.size > 1:
                out[1:] = x[:-1]
            return out
        if op == "MAX3":
            x = args[0]
            out = x.copy()
            if x.size > 1:
                out[1:] = np.maximum(out[1:], x[:-1])
            if x.size > 2:
                out[2:] = np.maximum(out[2:], x[:-2])
            return out
    except Exception:
        return None
    return None


def _resolve(name: Any, series: Dict[str, np.ndarray]) -> Optional[np.ndarray]:
    """解析參數: 數字 → 標量陣列 (對齊 series 長度); 序列名 → 對應陣列; else None."""
    if isinstance(name, (int, float)):
        # 對齊任一 series 的長度 (廣播相容)
        length = next((len(s) for s in series.values()), SERIES_LEN)
        return np.full(length, float(name))
    if isinstance(name, str) and name in series:
        return series[name]
    return None


def evaluate_formula(ast: List[Any], series: Dict[str, np.ndarray]) -> Optional[float]:
    """求值公式 AST, 回傳最後 bar 值 (或 None 若無效).

    Args:
        ast: 公式 AST, 如 ["GATE", "vol_cluster", "momentum", 0.0] 或巢狀
        series: {因子名: np.ndarray} — 來自 microstructure.compute_all 等

    Returns:
        float (最後 bar 值) 或 None (公式無效/arity 不符/未知運算元/未知序列)
    """
    if not series:
        return None

    def _eval(node: Any) -> Optional[np.ndarray]:
        if isinstance(node, list):
            if not node:
                return None
            op = node[0]
            if op not in ARITY:
                return None
            args: List[np.ndarray] = []
            for i in range(1, len(node)):
                arg = _eval(node[i]) if isinstance(node[i], list) else _resolve(node[i], series)
                if arg is None:
                    return None
                args.append(arg)
            if len(args) != ARITY[op]:
                return None
            return _apply(op, args)
        return _resolve(node, series)

    result = _eval(ast)
    if result is None or result.size == 0:
        return None
    last = result[-1]
    if not np.isfinite(last):
        return None  # NaN/Inf 結果 → None (不臆斷)
    return float(last)
