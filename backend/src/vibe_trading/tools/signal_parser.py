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

# 否定詞 — 出現在 BUY/SELL 前時，該命中視為無效（例：「否决BUY建议」不算 BUY）
_NEGATIONS = (
    "否决", "否決", "否定", "不建議", "不建议", "不要", "拒绝", "拒絕",
    "反对", "反對", "排除", "不买", "不買", "不卖", "不賣",
    "not ", "no ", "avoid", "never ",
)

# 明確決策欄位標籤 — 若文字含這些標籤，優先只解析標籤後的值（例：「最終決策：HOLD」）
_DECISION_FIELD_RE = re.compile(
    r"(?:最終決策|最终决策|決策概要|决策概要|Decision|決策|决策|Final Decision)\s*[::：]\s*([^。\n|，,；;]{0,30})",
    re.IGNORECASE,
)


def _strip_negated(text: str) -> tuple[str, bool]:
    """將被否定詞修飾的 BUY/SELL 關鍵字替換成佔位，避免全文掃描誤判。

    例：『否决量化评分卡的BUY建议』→ 『否决量化评分卡的___建议』

    Returns:
        (masked_text, had_negation) — had_negation 表示至少遮罩掉一個動作關鍵字
        （用於：全部動作都被否定 → 回 HOLD 不動作）
    """
    out = text
    had_negation = False
    for neg in _NEGATIONS:
        pattern = re.compile(
            re.escape(neg) + r".{0,12}?" + r"(STRONG\s*BUY|WEAK\s*BUY|BUY|STRONG\s*SELL|WEAK\s*SELL|SELL|做多|做空|买|買|卖|賣)",
            re.IGNORECASE,
        )

        def _mask(m):
            nonlocal had_negation
            had_negation = True
            return m.group(0)[: len(neg)] + "█" * (len(m.group(0)) - len(neg))

        out = pattern.sub(_mask, out)
    return out, had_negation


def _parse_field(text: str) -> Optional[str]:
    """若文字含明確決策欄位（最終決策/決策概要/Decision），回傳欄位值；否則 None。"""
    for m in _DECISION_FIELD_RE.finditer(text):
        val = normalize(m.group(1))
        if _STRONG_BUY in val:
            return _STRONG_BUY
        if _WEAK_BUY in val:
            return _WEAK_BUY
        if _STRONG_SELL in val:
            return _STRONG_SELL
        if _WEAK_SELL in val:
            return _WEAK_SELL
        if _BUY in val:
            return _BUY
        if _SELL in val:
            return _SELL
        if _HOLD in val or "观望" in val or "觀望" in val or "保持" in val:
            return _HOLD
    return None


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

    Priority:
      1. Explicit decision field (「最終決策：HOLD」「Decision: WEAK_BUY」)
      2. Full-text scan with negation masking (「否决...BUY建议」→ not BUY)
      3. Empty / None → "UNKNOWN"
    """
    if not text:
        return "UNKNOWN"

    # 1. 優先解析明確決策欄位
    field = _parse_field(text)
    if field:
        return field

    # 2. 全文掃描（先遮罩被否定的 BUY/SELL 關鍵字）
    masked, had_negation = _strip_negated(text)
    n = normalize(masked)
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
    if "观望" in n or "觀望" in n or "保持" in n or "观察" in n or "觀察" in n or "不确定" in n or "不確定" in n or _HOLD in n:
        return _HOLD
    # 3. 所有動作關鍵字都被否定（例：不要做多 / 不建議买入）→ 不動作 = HOLD
    if had_negation:
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
