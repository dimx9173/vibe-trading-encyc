"""規則提取引擎"""
from __future__ import annotations

from collections import Counter
from typing import List

from .models import ExtractedRule, TradeRecord


def extract_rules(trades: List[TradeRecord], min_confidence: float = 0.3) -> List[ExtractedRule]:
    """從交易記錄中提取行為規則

    Args:
        trades: 交易記錄列表
        min_confidence: 最小置信度閾值

    Returns:
        ExtractedRule 列表
    """
    rules: List[ExtractedRule] = []

    # 規則 1: 連續虧損後行為
    rule = _extract_consecutive_loss_rule(trades)
    if rule and rule.confidence >= min_confidence:
        rules.append(rule)

    # 規則 2: 時間段偏好
    rule = _extract_time_preference_rule(trades)
    if rule and rule.confidence >= min_confidence:
        rules.append(rule)

    # 規則 3: 倉位大小模式
    rule = _extract_position_size_rule(trades)
    if rule and rule.confidence >= min_confidence:
        rules.append(rule)

    # 規則 4: 止損行為
    rule = _extract_stop_loss_rule(trades)
    if rule and rule.confidence >= min_confidence:
        rules.append(rule)

    return rules


def _extract_consecutive_loss_rule(trades: List[TradeRecord]) -> ExtractedRule | None:
    """提取連續虧損後的行為規則"""
    sorted_trades = sorted(trades, key=lambda t: t.entry_time)

    consecutive_losses = 0
    post_loss_actions = []

    for trade in sorted_trades:
        if trade.pnl < 0:
            consecutive_losses += 1
        else:
            if consecutive_losses >= 2:
                post_loss_actions.append(trade.quantity)
            consecutive_losses = 0

    if len(post_loss_actions) < 3:
        return None

    # 檢查是否傾向放大倉位
    avg_qty = sum(post_loss_actions) / len(post_loss_actions)
    overall_avg = sum(t.quantity for t in trades) / len(trades)

    if avg_qty > overall_avg * 1.3:
        confidence = min(len(post_loss_actions) / 10.0, 1.0)
        return ExtractedRule(
            rule_id="consecutive_loss_increase_position",
            description="連續虧損 2 次後傾向放大倉位",
            trigger_condition="連續虧損 >= 2 次",
            suggested_action="固定倉位大小，不因情緒調整",
            confidence=confidence,
            evidence_count=len(post_loss_actions),
        )

    return None


def _extract_time_preference_rule(trades: List[TradeRecord]) -> ExtractedRule | None:
    """提取交易時間偏好規則"""
    hour_counts = Counter(t.entry_time.hour for t in trades)

    if not hour_counts:
        return None

    total = len(trades)
    top_hours = hour_counts.most_common(3)

    # 如果前 3 小時佔 >50%
    top_count = sum(c for _, c in top_hours)
    if top_count / total > 0.5:
        hours_str = ", ".join(f"{h}:00" for h, _ in top_hours)
        confidence = top_count / total
        return ExtractedRule(
            rule_id="time_concentration",
            description=f"交易集中在特定時段（{hours_str}）",
            trigger_condition=f"當前時間在 {hours_str}",
            suggested_action="分散交易時間，避免時段偏差",
            confidence=confidence,
            evidence_count=top_count,
        )

    return None


def _extract_position_size_rule(trades: List[TradeRecord]) -> ExtractedRule | None:
    """提取倉位大小模式規則"""
    quantities = [t.quantity for t in trades]

    if len(quantities) < 5:
        return None

    # 檢查是否使用固定倉位
    unique_qtys = set(quantities)
    if len(unique_qtys) <= 2:
        confidence = 0.8
        return ExtractedRule(
            rule_id="fixed_position_size",
            description="使用固定倉位大小",
            trigger_condition="每次交易",
            suggested_action="考慮根據波動率調整倉位（如凱利公式）",
            confidence=confidence,
            evidence_count=len(trades),
        )

    # 檢查倉位是否隨機
    avg_qty = sum(quantities) / len(quantities)
    std_qty = (sum((q - avg_qty) ** 2 for q in quantities) / len(quantities)) ** 0.5
    cv = std_qty / avg_qty if avg_qty > 0 else 0

    if cv > 0.5:
        confidence = min(cv / 1.0, 1.0)
        return ExtractedRule(
            rule_id="variable_position_size",
            description="倉位大小變化劇烈（CV={:.2f}）".format(cv),
            trigger_condition="每次交易",
            suggested_action="建立倉位大小規則（如固定風險%）",
            confidence=confidence,
            evidence_count=len(trades),
        )

    return None


def _extract_stop_loss_rule(trades: List[TradeRecord]) -> ExtractedRule | None:
    """提取止損行為規則"""
    losing_trades = [t for t in trades if t.is_closed and t.pnl < 0]

    if len(losing_trades) < 5:
        return None

    # 檢查虧損百分比是否集中在某個範圍
    loss_pcts = [abs(t.pnl_pct) for t in losing_trades]
    avg_loss = sum(loss_pcts) / len(loss_pcts)

    # 如果平均虧損接近常見固定%（如 5%）
    if 4.0 <= avg_loss <= 6.0:
        confidence = 0.7
        return ExtractedRule(
            rule_id="fixed_percentage_stop_loss",
            description=f"止損設在固定百分比（~{avg_loss:.1f}%）",
            trigger_condition="持倉虧損時",
            suggested_action="使用 ATR 或技術位設定止損",
            confidence=confidence,
            evidence_count=len(losing_trades),
        )

    return None
