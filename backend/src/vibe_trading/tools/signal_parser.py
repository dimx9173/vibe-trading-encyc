"""
Shared decision-text parser for VBT.

Single source of truth used by both:
  - SignalProcessor._extract_signal_type (for QualityTracker DB records)
  - TradingCoordinator._run_portfolio_manager (for execution)

The two previously-duplicated implementations diverged for the `WEAK_BUY`
underscore variant: keyword parsing missed the space form and fell through
to `BUY`; regex `\bbuy\b` couldn't match `weak_buy` (underscore blocks
the word boundary), falling through to `UNKNOWN`. Centralizing here
guarantees both call sites agree.
"""
from __future__ import annotations

import re
from typing import Optional


_NORMALIZE_RE = re.compile(r"[_\-]+")


def normalize(text: str) -> str:
    """Uppercase + collapse underscores/hyphens to spaces. Used before substring checks."""
    return _NORMALIZE_RE.sub(" ", text.upper())


# Substring checks (post-normalize) ordered strong → weak → plain.
_STRONG_BUY = "STRONG BUY"
_WEAK_BUY = "WEAK BUY"
_BUY = "BUY"
_STRONG_SELL = "STRONG SELL"
_WEAK_SELL = "WEAK SELL"
_SELL = "SELL"
_HOLD = "HOLD"


def parse_decision(text: Optional[str]) -> str:
    """Map PM decision_text to a canonical label.

    Returns one of:
        "STRONG BUY", "WEAK BUY", "BUY",
        "STRONG SELL", "WEAK SELL", "SELL",
        "HOLD", "UNKNOWN"

    Empty / None text → "UNKNOWN" (sentinel; signal_processor maps this to
    TradingSignal.UNKNOWN so the dead-code guard in _extract_signal_type
    becomes live again).
    """
    if not text:
        return "UNKNOWN"
    n = normalize(text)
    if _STRONG_BUY in n or "强买" in n or "强買" in n:
        return _STRONG_BUY
    if _WEAK_BUY in n or "弱买" in n or "弱買" in n:
        return _WEAK_BUY
    if _BUY in n or "买" in n or "買" in n or "做多" in n or "开多" in n or "開多" in n or "建議買入" in n or "推荐买入" in n:
        return _BUY
    if _STRONG_SELL in n or "强卖" in n or "強賣" in n:
        return _STRONG_SELL
    if _WEAK_SELL in n or "弱卖" in n or "弱賣" in n:
        return _WEAK_SELL
    if _SELL in n or "卖" in n or "賣" in n or "做空" in n or "开空" in n or "開空" in n or "平仓" in n or "建議賣出" in n or "推荐卖出" in n:
        return _SELL
    if "观望" in n or "觀望" in n or "保持" in n or "不确定" in n or "不確定" in n or _HOLD in n:
        return _HOLD
    return "UNKNOWN"


def to_signal_enum(decision: str) -> str:
    """Map canonical label → DB signal enum (BUY/SELL/HOLD/UNKNOWN).

    Strong/Weak variants collapse to plain direction.
    UNKNOWN passes through as-is (restores signal_processor UNKNOWN semantics).
    """
    if decision in (_STRONG_BUY, _WEAK_BUY, _BUY):
        return "BUY"
    if decision in (_STRONG_SELL, _WEAK_SELL, _SELL):
        return "SELL"
    return decision  # HOLD or UNKNOWN


def detect_strength(text: Optional[str]) -> str:
    """Detect signal strength from decision text.

    Returns one of: "strong" | "moderate" | "weak" | "uncertain"

    Hierarchy:
      1. Explicit WEAK_*/STRONG_* markers (e.g. "WEAK_BUY", "STRONG_SELL")
      2. Hedge words ("might", "possibly", "slightly", etc.) downgrade plain BUY/SELL
         to WEAK, and strong hedges ("strongly", "clearly") upgrade to STRONG.
      3. Plain BUY/SELL → MODERATE
      4. Otherwise → UNCERTAIN
    """
    if not text:
        return "uncertain"
    n = normalize(text)
    if _STRONG_BUY in n or _STRONG_SELL in n or "强买" in n or "强賣" in n or "强卖" in n:
        return "strong"
    if _WEAK_BUY in n or _WEAK_SELL in n or "弱买" in n or "弱賣" in n or "弱卖" in n:
        return "weak"

    # Hedge words for plain BUY/SELL (only meaningful when neither strong/weak marker)
    strong_hedges = ("strongly", "strong", "highly", "definitely", "clearly", "强烈", "明确")
    weak_hedges = ("weakly", "slightly", "may ", "might", "possibly", "probably",
                   "倾向于", "谨慎", "也该", "也许")

    has_buy = _BUY in n or "买" in n or "買" in n or "做多" in n or "开多" in n
    has_sell = _SELL in n or "卖" in n or "賣" in n or "做空" in n or "开空" in n

    n_lower = n.lower()
    if any(h.lower() in n_lower for h in strong_hedges) and (has_buy or has_sell):
        return "strong"
    if any(h.lower() in n_lower for h in weak_hedges) and (has_buy or has_sell):
        return "weak"
    if has_buy or has_sell:
        return "moderate"
    return "uncertain"
