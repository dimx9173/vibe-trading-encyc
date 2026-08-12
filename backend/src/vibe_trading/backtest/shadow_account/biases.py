"""行為偏差打分模組"""
from __future__ import annotations

from datetime import timedelta
from typing import List

from .models import BehavioralProfile, BiasScore, BiasType, TradeRecord


def calculate_disposition_effect(trades: List[TradeRecord]) -> BiasScore:
    """處置效應：盈利倉位過早止盈，虧損倉位過晚止損

    計算：虧損倉位平均持有時間 / 盈利倉位平均持有時間
    分數：>2.0 為嚴重，1.5-2.0 為中等，<1.5 為輕微
    """
    winning_trades = [t for t in trades if t.is_closed and t.pnl > 0]
    losing_trades = [t for t in trades if t.is_closed and t.pnl < 0]

    if not winning_trades or not losing_trades:
        return BiasScore(
            bias_type=BiasType.DISPOSITION,
            score=0.0,
            description="數據不足，無法計算處置效應",
        )
    avg_win_hold = sum(
        (t.exit_time - t.entry_time).total_seconds()
        for t in winning_trades
        if t.exit_time is not None
    ) / len(winning_trades)

    avg_loss_hold = sum(
        (t.exit_time - t.entry_time).total_seconds()
        for t in losing_trades
        if t.exit_time is not None
    ) / len(losing_trades)
    ratio = avg_loss_hold / avg_win_hold if avg_win_hold > 0 else 0

    # 歸一化到 0-1
    score = min(ratio / 3.0, 1.0)

    evidence = [
        f"盈利倉位平均持有：{avg_win_hold/3600:.1f} 小時",
        f"虧損倉位平均持有：{avg_loss_hold/3600:.1f} 小時",
        f"比率：{ratio:.2f}x",
    ]

    recommendation = (
        "建議使用技術止損（如 ATR 倍數）而非固定百分比，"
        "並設定最大持有時間限制。"
    )

    return BiasScore(
        bias_type=BiasType.DISPOSITION,
        score=score,
        description="處置效應：虧損倉位持有時間過長",
        evidence=evidence,
        recommendation=recommendation,
    )


def calculate_overtrading(trades: List[TradeRecord], recommended_daily: int = 8) -> BiasScore:
    """過度交易：實際交易頻率遠超策略建議

    計算：日均交易次數 / 建議日均次數
    分數：>3x 為嚴重，2-3x 為中等，<2x 為輕微
    """
    if not trades:
        return BiasScore(
            bias_type=BiasType.OVERTRADING,
            score=0.0,
            description="無交易記錄",
        )

    # 計算交易時間跨度
    times = [t.entry_time for t in trades]
    days = max((max(times) - min(times)).days, 1)
    daily_trades = len(trades) / days

    ratio = daily_trades / recommended_daily
    score = min(ratio / 4.0, 1.0)

    evidence = [
        f"總交易次數：{len(trades)}",
        f"交易天數：{days}",
        f"日均交易：{daily_trades:.1f} 筆",
        f"建議日均：{recommended_daily} 筆",
        f"比率：{ratio:.2f}x",
    ]

    recommendation = (
        "建議設定每日交易次數上限，並在連續交易 3 次後強制休息 1 小時。"
    )

    return BiasScore(
        bias_type=BiasType.OVERTRADING,
        score=score,
        description="過度交易：交易頻率過高",
        evidence=evidence,
        recommendation=recommendation,
    )


def calculate_chasing(trades: List[TradeRecord], threshold_pct: float = 3.0) -> BiasScore:
    """追漲殺跌：買單發生在價格已大幅移動之後

    計算：買入時價格已漲 >threshold% 的比例
    分數：>70% 為嚴重，50-70% 為中等，<50% 為輕微
    """
    buy_trades = [t for t in trades if t.side == "BUY"]

    if not buy_trades:
        return BiasScore(
            bias_type=BiasType.CHASING,
            score=0.0,
            description="無買入記錄",
        )

    chasing_count = 0
    for trade in buy_trades:
        # 簡化：假設 entry_price 相對「合理進場價」的偏移
        # 實際需要 K 線數據，這裡用 metadata 中的 pre_move_pct
        pre_move = trade.metadata.get("pre_move_pct", 0)
        if abs(pre_move) > threshold_pct:
            chasing_count += 1

    ratio = chasing_count / len(buy_trades)
    score = ratio

    evidence = [
        f"總買入次數：{len(buy_trades)}",
        f"追漲次數：{chasing_count}",
        f"追漲比例：{ratio:.1%}",
    ]

    recommendation = (
        "建議使用限價單而非市價單，設定最大追漲幅度（如 1%），"
        "錯過就放棄而非追高。"
    )

    return BiasScore(
        bias_type=BiasType.CHASING,
        score=score,
        description="追漲殺跌：買單發生在價格已大幅移動後",
        evidence=evidence,
        recommendation=recommendation,
    )


def calculate_anchoring(trades: List[TradeRecord]) -> BiasScore:
    """定效應：止損/止盈設在買入價固定%而非技術位

    計算：使用固定%止損的比例
    分數：>80% 為嚴重，60-80% 為中等，<60% 為輕微
    """
    closed_trades = [t for t in trades if t.is_closed]

    if not closed_trades:
        return BiasScore(
            bias_type=BiasType.ANCHORING,
            score=0.0,
            description="無已平倉記錄",
        )

    # 簡化：檢查止損是否接近固定%（如 5%）
    # 實際需要分析止損設置邏輯
    anchored_count = 0
    for trade in closed_trades:
        if trade.pnl < 0:
            loss_pct = abs(trade.pnl_pct)
            # 如果虧損接近常見固定%（4-6%），可能是錨定
            if 4.0 <= loss_pct <= 6.0:
                anchored_count += 1

    ratio = anchored_count / max(len([t for t in closed_trades if t.pnl < 0]), 1)
    score = ratio

    evidence = [
        f"虧損交易數：{len([t for t in closed_trades if t.pnl < 0])}",
        f"使用固定%止損：{anchored_count}",
        f"定比例：{ratio:.1%}",
    ]

    recommendation = (
        "建議使用 ATR 或支撐/阻力位設定止損，而非固定百分比。"
    )

    return BiasScore(
        bias_type=BiasType.ANCHORING,
        score=score,
        description="錨定效應：止損設在固定百分比",
        evidence=evidence,
        recommendation=recommendation,
    )


def calculate_gambler_fallacy(trades: List[TradeRecord]) -> BiasScore:
    """賭徒謬誤：連續虧損後放大倉位

    計算：連續虧損 3+ 次後倉位放大的比例
    分數：>60% 為嚴重，40-60% 為中等，<40% 為輕微
    """
    if len(trades) < 4:
        return BiasScore(
            bias_type=BiasType.GAMBLER,
            score=0.0,
            description="交易記錄不足",
        )

    # 按時間排序
    sorted_trades = sorted(trades, key=lambda t: t.entry_time)

    consecutive_losses = 0
    gambler_count = 0
    opportunity_count = 0

    for i, trade in enumerate(sorted_trades):
        if trade.pnl < 0:
            consecutive_losses += 1
        else:
            if consecutive_losses >= 3:
                # 檢查這筆是否放大倉位
                if i > 0 and trade.quantity > sorted_trades[i-1].quantity * 1.5:
                    gambler_count += 1
                opportunity_count += 1
            consecutive_losses = 0

    ratio = gambler_count / max(opportunity_count, 1)
    score = ratio

    evidence = [
        f"連續虧損 3+ 次後交易：{opportunity_count}",
        f"其中放大倉位：{gambler_count}",
        f"賭徒謬誤比例：{ratio:.1%}",
    ]

    recommendation = (
        "建議固定倉位大小，或根據策略信號而非情緒調整倉位。"
        "連續虧損後應減少倉位而非放大。"
    )

    return BiasScore(
        bias_type=BiasType.GAMBLER,
        score=score,
        description="賭徒謬誤：連續虧損後放大倉位",
        evidence=evidence,
        recommendation=recommendation,
    )


def calculate_all_biases(
    trades: List[TradeRecord],
    recommended_daily_trades: int = 8,
    chasing_threshold_pct: float = 3.0,
) -> List[BiasScore]:
    """計算所有行為偏差

    Args:
        trades: 交易記錄列表
        recommended_daily_trades: 建議日均交易次數
        chasing_threshold_pct: 追漲閾值百分比

    Returns:
        BiasScore 列表
    """
    return [
        calculate_disposition_effect(trades),
        calculate_overtrading(trades, recommended_daily_trades),
        calculate_chasing(trades, chasing_threshold_pct),
        calculate_anchoring(trades),
        calculate_gambler_fallacy(trades),
    ]
