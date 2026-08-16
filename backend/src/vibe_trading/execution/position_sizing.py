"""
Position Sizing Engine (Phase 5 — 確定性量化數學引擎)

神經符號混合架構的 Python 定量層:
AI Agent 給出結構點位 (Entry/SL/TP) 與信心度, 本模組以純 Python
嚴謹計算倉位大小 — Half-Kelly 資金比 + ATR 波動率調倉 + 風控硬門禁。

規格書: docs/specs/vbt-architecture-strategy-improvement-spec.md §5
"""


def calculate_half_kelly(
    win_rate: float,
    reward_risk_ratio: float,
    fraction: float = 0.5,
) -> float:
    """計算分數凱利資金比例: f* = fraction * (b*p - q) / b.

    Args:
        win_rate: 勝率 p (0.0~1.0)
        reward_risk_ratio: 盈虧比 b = |TP-Entry| / |Entry-SL|
        fraction: 分數凱利係數 (預設 0.5 = Half-Kelly)

    Returns:
        f* (0.0 起, 無正期望值時為 0.0)
    """
    if reward_risk_ratio <= 0.0 or win_rate <= 0.0 or win_rate >= 1.0:
        return 0.0
    q = 1.0 - win_rate
    f_star = (reward_risk_ratio * win_rate - q) / reward_risk_ratio
    return max(0.0, f_star * fraction)


def calculate_actual_risk_reward(
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
) -> float:
    """嚴謹計算真實盈虧比 b = |TP - Entry| / |Entry - SL|.

    防呆: 任一價格無效/風險距離為 0 → 回 0.0 (無正期望可計算).
    """
    if entry_price <= 0 or stop_loss_price <= 0 or take_profit_price <= 0:
        return 0.0
    risk_dist = abs(entry_price - stop_loss_price)
    reward_dist = abs(take_profit_price - entry_price)
    if risk_dist <= 1e-9:
        return 0.0
    return reward_dist / risk_dist


def calibrate_win_rate(confidence: float) -> float:
    """勝率動態校準: 以 0.50 為基準保守映射, 防 LLM 過度自信.

    p = 0.50 + (confidence - 0.50) * 0.40, 截斷至 [0.35, 0.75].
    """
    p = 0.50 + (confidence - 0.50) * 0.40
    return min(max(p, 0.35), 0.75)


def calculate_atr_position_size(
    account_equity: float,
    confidence: float,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    atr_30m: float,
    risk_multiplier: float = 1.5,
    max_single_notional: float = 500.0,
    max_leverage: float = 5.0,
) -> float:
    """結合真實盈虧比、校準勝率、Half-Kelly 與 ATR 計算下單數量 (幣本位).

    Args:
        account_equity: 帳戶淨值 (USDT)
        confidence: AI 信心度 (0.0~1.0)
        entry_price: 建議進場價
        stop_loss_price: 結構止損價
        take_profit_price: 第一目標止盈價
        atr_30m: 30m ATR 波動率
        risk_multiplier: ATR 風險乘數 (止損距離 = ATR × multiplier)
        max_single_notional: 單筆名義價值上限 (USDT, 進取型 500 = 5% of 10k)
        max_leverage: 槓桿上限 (5x)

    Returns:
        position_qty (幣本位); 無正期望/無效輸入 → 0.0
    """
    if account_equity <= 0 or entry_price <= 0:
        return 0.0
    if stop_loss_price <= 0 or take_profit_price <= 0:
        return 0.0

    # 1. 真實盈虧比
    b = calculate_actual_risk_reward(entry_price, stop_loss_price, take_profit_price)
    if b <= 0.0:
        return 0.0

    # 2. 校準勝率
    p = calibrate_win_rate(confidence)

    # 3. Half-Kelly
    kelly_f = calculate_half_kelly(win_rate=p, reward_risk_ratio=b, fraction=0.5)
    if kelly_f <= 0.0:
        return 0.0

    # 4. ATR 波動率金額風險敞口 (ATR 下限防過小)
    dollar_risk = account_equity * kelly_f
    effective_atr = max(atr_30m, entry_price * 0.005)
    qty = dollar_risk / (effective_atr * risk_multiplier)

    # 5. 風控硬門禁截斷 (單筆 ≤ 500U, 槓桿 ≤ 5x)
    max_notional_cap = min(max_single_notional, account_equity * max_leverage)
    max_qty_cap = max_notional_cap / entry_price
    if max_qty_cap <= 0:
        return 0.0
    return float(min(qty, max_qty_cap))


def apply_risk_guardrails(
    qty: float,
    entry_price: float,
    account_equity: float,
    max_single_notional: float = 500.0,
    max_leverage: float = 5.0,
) -> float:
    """風控硬上限截斷 (獨立套用, 供既有下單路徑共用).

    同時受單筆名義價值上限與槓桿上限約束, 超限則截斷至上限對應數量.
    """
    if qty <= 0 or entry_price <= 0 or account_equity <= 0:
        return 0.0
    max_notional_cap = min(max_single_notional, account_equity * max_leverage)
    max_qty_cap = max_notional_cap / entry_price
    return float(min(qty, max_qty_cap))
