"""反事實回測模組"""
from __future__ import annotations

from typing import List, Optional

from .models import CounterfactualResult, TradeRecord


def run_counterfactual(
    trades: List[TradeRecord],
    ideal_trades: Optional[List[TradeRecord]] = None,
) -> CounterfactualResult:
    """運行反事實回測

    比較實際交易與「理想行為」交易的績效差異。

    Args:
        trades: 實際交易記錄
        ideal_trades: 理想行為交易記錄（如未提供，則基於規則生成）

    Returns:
        CounterfactualResult
    """
    if ideal_trades is None:
        # 簡化：生成「理想」交易（移除行為偏差）
        ideal_trades = _generate_ideal_trades(trades)

    # 計算實際指標
    actual_pnl = sum(t.pnl for t in trades if t.is_closed)
    actual_initial = 10000.0  # 假設初始資金
    actual_pnl_pct = actual_pnl / actual_initial

    closed_actual = [t for t in trades if t.is_closed]
    actual_wins = len([t for t in closed_actual if t.pnl > 0])
    actual_win_rate = actual_wins / len(closed_actual) if closed_actual else 0

    # 計算理想指標
    ideal_pnl = sum(t.pnl for t in ideal_trades if t.is_closed)
    ideal_pnl_pct = ideal_pnl / actual_initial

    closed_ideal = [t for t in ideal_trades if t.is_closed]
    ideal_wins = len([t for t in closed_ideal if t.pnl > 0])
    ideal_win_rate = ideal_wins / len(closed_ideal) if closed_ideal else 0

    # 簡化 Sharpe 計算
    actual_sharpe = _calculate_sharpe(closed_actual)
    ideal_sharpe = _calculate_sharpe(closed_ideal)

    improvement = ideal_pnl - actual_pnl
    improvement_pct = improvement / actual_initial

    # 生成 equity curve（簡化）
    equity_actual = _build_equity_curve(closed_actual, actual_initial)
    equity_ideal = _build_equity_curve(closed_ideal, actual_initial)

    return CounterfactualResult(
        actual_pnl=actual_pnl,
        actual_pnl_pct=actual_pnl_pct,
        ideal_pnl=ideal_pnl,
        ideal_pnl_pct=ideal_pnl_pct,
        improvement=improvement,
        improvement_pct=improvement_pct,
        actual_trades=len(closed_actual),
        ideal_trades=len(closed_ideal),
        actual_win_rate=actual_win_rate,
        ideal_win_rate=ideal_win_rate,
        actual_sharpe=actual_sharpe,
        ideal_sharpe=ideal_sharpe,
        equity_curve_actual=equity_actual,
        equity_curve_ideal=equity_ideal,
    )


def _generate_ideal_trades(trades: List[TradeRecord]) -> List[TradeRecord]:
    """生成理想行為交易（簡化版）

    移除明顯的行為偏差：
    1. 移除追漲交易（pre_move_pct > 3%）
    2. 統一持有時間（取中位數）
    3. 固定倉位大小
    """
    from datetime import timedelta
    import statistics

    if not trades:
        return []

    # 計算中位數持有時間
    hold_times = []
    for t in trades:
        if t.is_closed and t.exit_time:
            hold_times.append((t.exit_time - t.entry_time).total_seconds())

    median_hold = statistics.median(hold_times) if hold_times else 3600

    # 計算中位數倉位
    median_qty = statistics.median([t.quantity for t in trades])

    ideal_trades = []
    for t in trades:
        # 跳過追漲交易
        if t.metadata.get("pre_move_pct", 0) > 3.0:
            continue

        # 調整持有時間和倉位
        ideal_t = TradeRecord(
            trade_id=f"ideal_{t.trade_id}",
            symbol=t.symbol,
            side=t.side,
            entry_time=t.entry_time,
            exit_time=t.entry_time + timedelta(seconds=median_hold) if t.is_closed else None,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            quantity=median_qty,
            pnl=t.pnl,  # 簡化：保持原 PnL
            pnl_pct=t.pnl_pct,
            fee=t.fee,
            is_closed=t.is_closed,
            metadata={**t.metadata, "ideal": True},
        )
        ideal_trades.append(ideal_t)

    return ideal_trades


def _calculate_sharpe(trades: List[TradeRecord], risk_free_rate: float = 0.0) -> float:
    """計算簡化 Sharpe Ratio"""
    if len(trades) < 2:
        return 0.0

    returns = [t.pnl_pct / 100.0 for t in trades]
    avg_return = sum(returns) / len(returns)
    variance = sum((r - avg_return) ** 2 for r in returns) / len(returns)
    std_dev = variance ** 0.5

    if std_dev == 0:
        return 0.0

    # 年化（假設日均交易）
    annualized = (avg_return / std_dev) * (252 ** 0.5)
    return annualized


def _build_equity_curve(trades: List[TradeRecord], initial: float) -> List[float]:
    """構建 equity curve"""
    sorted_trades = sorted(trades, key=lambda t: t.entry_time)
    equity = [initial]
    current = initial

    for t in sorted_trades:
        current += t.pnl
        equity.append(current)

    return equity
