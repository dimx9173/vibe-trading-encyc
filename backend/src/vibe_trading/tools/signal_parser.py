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
# 結構：(pattern, lookahead_window) — window 是否定詞後允許的字符數
# 中文否定詞通常緊接動作詞（否决...BUY建议 中間隔「量化评分卡的」~8 字），用大窗口；
# 英文 no/not 用極小窗口，避免「no upside. BUY」誤傷（no 後隔 7 字才是 BUY）。
_NEGATIONS = (
    # 中文（大窗口，~10 字）
    ("否决", 10), ("否決", 10), ("否定", 10), ("不建議", 6), ("不建议", 6),
    ("不要", 6), ("拒绝", 6), ("拒絕", 6), ("反对", 6), ("反對", 6),
    ("排除", 6), ("不用", 6), ("不能", 6), ("不会", 6), ("不會", 6),
    ("不应", 6), ("不應", 6), ("不买", 2), ("不買", 2), ("不卖", 2), ("不賣", 2),
    ("不做多", 4), ("不做空", 4), ("不追多", 4), ("不追空", 4),
    ("不", 1),  # 單獨「不」緊鄰動作詞：不做/不買/不賣（window=1 只擋緊鄰，避免誤傷）
    ("避免", 8), ("防止", 8), ("不考虑", 6), ("不考慮", 6), ("暂不", 6), ("暫不", 6),
    # 英文（極小窗口，只擋緊鄰動作詞："no BUY" 擋、"no upside. BUY" 不擋）
    (r"\bnot\s+", 2), (r"\bno\s+", 2), (r"\bavoid\s+", 2), (r"\bnever\s+", 2),
    (r"\bdon'?t\s+", 2), (r"\bwithout\s+", 2), (r"\bdecline\s+", 2), (r"\breject\s+", 2),
)

# 明確決策欄位標籤 — 若文字含這些標籤，優先只解析標籤後的值（例：「最終決策：HOLD」）
# 注意：value group 可能貪婪跨過空白吃到後面的 BUY/SELL，_parse_field 用
# 「最早出現的關鍵字」解決（例："Final Decision: HOLD and we avoid BUYing" → HOLD）
_DECISION_FIELD_RE = re.compile(
    r"(?:最終決策|最终决策|決策概要|决策概要|Decision|決策|决策|Final Decision)\s*[::：]\s*([^。\n|，,；;]{0,30})",
    re.IGNORECASE,
)

# 動作關鍵字（用於 _parse_field 找「最早出現」）
_SIGNAL_KEYWORDS = (
    ("STRONG BUY", 10), ("WEAK BUY", 9), ("STRONG SELL", 11), ("WEAK SELL", 10),
    ("BUY", 3), ("SELL", 4), ("HOLD", 4),
    ("做多", 2), ("做空", 2), ("买", 1), ("買", 1), ("卖", 1), ("賣", 1),
    ("观望", 2), ("觀望", 2), ("保持", 2),
)


def _strip_negated(text: str) -> tuple[str, bool]:
    """將被否定詞修飾的 BUY/SELL 關鍵字替換成佔位，避免全文掃描誤判。

    例：『否决量化评分卡的BUY建议』→ 『否决量化评分卡的___建议』

    注意：不能 re.escape — 英文否定詞帶 \b word-boundary（如 r"\\bnot\\s+"），
    escape 會破壞正則語義。中文否定詞（否决/不要/不用...）本身無正則元字元，
    直接當 pattern 安全。

    Returns:
        (masked_text, had_negation) — had_negation 表示至少遮罩掉一個動作關鍵字
        （用於：全部動作都被否定 → 回 HOLD 不動作）
    """
    out = text
    had_negation = False
    for neg, window in _NEGATIONS:
        pattern = re.compile(
            neg + r".{0," + str(window) + r"}?"
            + r"(STRONG\s*BUY|WEAK\s*BUY|BUY|STRONG\s*SELL|WEAK\s*SELL|SELL|做多|做空|开多|開多|开空|開空|开仓|開倉|平仓|平倉|买|買|卖|賣)",
            re.IGNORECASE,
        )

        def _mask(m):
            nonlocal had_negation
            had_negation = True
            return m.group(0)[: len(neg)] + "█" * (len(m.group(0)) - len(neg))

        out = pattern.sub(_mask, out)
    return out, had_negation


def _parse_field(text: str) -> Optional[str]:
    """若文字含明確決策欄位（最終決策/決策概要/Decision），回傳欄位值；否則 None。

    用「最早出現的動作關鍵字」解析，避免 value group 貪婪跨過空白吃到後面的
    BUY/SELL（例："Final Decision: HOLD and we avoid BUYing" → HOLD）。
    """
    for m in _DECISION_FIELD_RE.finditer(text):
        val = normalize(m.group(1))
        best: Optional[tuple[int, str]] = None
        for kw, _score in _SIGNAL_KEYWORDS:
            idx = val.find(kw)
            if idx >= 0 and (best is None or idx < best[0]):
                best = (idx, kw)
        if best is None:
            # 欄位後無動作關鍵字（例：「決策：待定」）→ 不當作有效欄位
            continue
        if best[1] in ("STRONG BUY", "WEAK BUY", "BUY", "做多", "买", "買"):
            return best[1]
        if best[1] in ("STRONG SELL", "WEAK SELL", "SELL", "做空", "卖", "賣"):
            return best[1]
        if best[1] in ("HOLD", "观望", "觀望", "保持"):
            return "HOLD"
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

    return _scan_full(text)


def _scan_full(text: str) -> str:
    """全文掃描（含否定遮罩），不做欄位短路 — 供一致性檢查比對。"""
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
    # 所有動作關鍵字都被否定（例：不要做多 / 不建議买入）→ 不動作 = HOLD
    if had_negation:
        return _HOLD
    return "UNKNOWN"


def to_signal_enum(decision: str) -> str:
    """Map canonical label → DB signal enum (BUY/SELL/HOLD/UNKNOWN).

    Strong/Weak variants collapse to plain direction.
    輸入可能是底線版（STRONG_BUY）或空格版（STRONG BUY）— 先標準化。
    UNKNOWN passes through as-is.
    """
    n = normalize(decision)
    if n in (_STRONG_BUY, _WEAK_BUY, _BUY):
        return "BUY"
    if n in (_STRONG_SELL, _WEAK_SELL, _SELL):
        return "SELL"
    if n in ("HOLD",):
        return "HOLD"
    return decision  # UNKNOWN or passthrough


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
