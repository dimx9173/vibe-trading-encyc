"""動態標的宇宙篩選 (Phase 4.2, 採納評估 A4).

Binance 永續 24h tickers → quote volume 排名 → 過濾穩定幣/槓桿代幣.
取代硬編碼 symbols.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 穩定幣 (報價幣) — symbol endswith 檢查
_STABLES = ("USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "EUR", "GBP", "BRL", "TRY", "AUD")
# 槓桿/倍數代幣後綴
_LEVERAGE_SUFFIX = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")


def _is_tradable(symbol: str) -> bool:
    """是否以穩定幣報價 (可交易)."""
    return any(symbol.endswith(s) and len(symbol) > len(s) for s in _STABLES)


def _is_leveraged(symbol: str) -> bool:
    """是否為槓桿代幣 (排除)."""
    base = symbol
    for s in _STABLES:
        if symbol.endswith(s):
            base = symbol[: -len(s)]
            break
    return any(base.endswith(suffix) for suffix in _LEVERAGE_SUFFIX)


def rank_universe(
    tickers: List[Dict[str, Any]],
    top_n: int = 30,
    min_quote_volume: float = 1_000_000.0,
    max_quote_volume: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """排名: quote volume 降序, 過濾穩定幣/槓桿/低流動性.

    Args:
        tickers: [{symbol, quote_volume, ...}]
        top_n: 回傳數量
        min_quote_volume: 最低 24h 報價量 (USDT)
        max_quote_volume: 可選上限 (排除超大市值)

    Returns: 過濾後 top-N tickers (降序).
    """
    candidates: List[Dict[str, Any]] = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol or not _is_tradable(symbol) or _is_leveraged(symbol):
            continue
        try:
            qv = float(t.get("quote_volume") or t.get("quoteVolume") or 0.0)
        except (TypeError, ValueError):
            continue
        if qv < min_quote_volume:
            continue
        if max_quote_volume and qv > max_quote_volume:
            continue
        candidates.append(t)

    candidates.sort(key=lambda x: -float(x.get("quote_volume") or x.get("quoteVolume") or 0.0))
    return candidates[:top_n]


def format_universe(tickers: List[Dict[str, Any]]) -> str:
    """格式化標的清單 (CLI 輸出)."""
    if not tickers:
        return "無符合條件的標的"
    lines = ["📊 動態標的宇宙 (quote volume 排名):"]
    for i, t in enumerate(tickers, 1):
        qv = float(t.get("quote_volume") or t.get("quoteVolume") or 0.0)
        chg = float(t.get("price_change_percent") or t.get("priceChangePercent") or 0.0)
        lines.append(
            f"{i:>2}. {t.get('symbol', '?'):<15} "
            f"vol={qv / 1e6:>8.1f}M "
            f"chg={chg:>+6.2f}%"
        )
    return "\n".join(lines)
