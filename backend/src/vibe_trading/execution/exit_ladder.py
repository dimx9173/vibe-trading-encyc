"""退出階梯 (Phase 4.2, 採納評估 A5).

trailing: 峰值漲幅 ≥5% 啟動, 峰值回撤 ≥3% 全出
moonbag: TP1 +10% 賣 50%, 剩 50% 繼續跑 trailing
純函式 + dataclass, 無副作用.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ExitState:
    symbol: str
    entry_price: float
    peak_price: float
    trailing_active: bool = False
    moonbag_sold: bool = False
    trailing_activate_pct: float = 0.05   # +5% 啟動
    trailing_exit_dd_pct: float = 0.03    # 峰值回撤 3% 全出
    moonbag_tp_pct: float = 0.10          # +10% 賣 50%


def make_exit_state(symbol: str, entry_price: float) -> ExitState:
    return ExitState(symbol=symbol, entry_price=entry_price, peak_price=entry_price)


def update_exit(
    state: ExitState,
    current_price: float,
    position_quantity: float,
) -> Dict[str, Any]:
    """更新退出狀態, 回傳動作.

    Returns: {"action": "hold"|"sell_all"|"sell_half", "reason": str, "quantity": float}
    """
    if position_quantity <= 0 or current_price <= 0:
        return {"action": "hold", "reason": "no position", "quantity": 0.0}

    state.peak_price = max(state.peak_price, current_price)
    gain = current_price / state.entry_price - 1.0

    # moonbag: +10% 賣 50% (觸發一次)
    if not state.moonbag_sold and gain >= state.moonbag_tp_pct:
        state.moonbag_sold = True
        state.trailing_active = True
        return {"action": "sell_half", "reason": f"moonbag TP +{state.moonbag_tp_pct:.0%}",
                "quantity": position_quantity * 0.5}

    # trailing: 峰值漲幅 ≥5% 啟動
    if not state.trailing_active:
        if gain >= state.trailing_activate_pct:
            state.trailing_active = True
        else:
            return {"action": "hold", "reason": "trailing not active", "quantity": 0.0}

    # trailing 回撤: 峰值回撤 ≥3% 全出
    drawdown = 1.0 - current_price / state.peak_price
    if drawdown >= state.trailing_exit_dd_pct:
        return {"action": "sell_all", "reason": f"trailing exit (dd {drawdown:.1%})",
                "quantity": position_quantity}
    return {"action": "hold", "reason": "trailing active", "quantity": 0.0}


# =============================================================================
# Harvested Alpha — 三級階梯止盈 + 動能枯竭引擎 (規格書 §2.1)
# =============================================================================

from enum import Enum
from typing import Optional, Tuple


class LadderStage(str, Enum):
    """階梯出場狀態機."""
    INITIAL = "INITIAL"
    TP1_HIT_30 = "TP1_HIT_30"               # 平 30%, 止損移至保本
    TP2_HIT_40 = "TP2_HIT_40"               # 平 40%, 止損移至 TP1
    TRAILING_ACTIVE = "TRAILING_ACTIVE"     # 剩餘 30% 移動止損
    EXHAUSTION_EARLY_EXIT = "EXHAUSTION_EARLY_EXIT"  # 放量滯漲平 50%
    CLOSED = "CLOSED"


@dataclass
class ExitLadderConfig:
    """三級階梯配置 (規格書 §2.1)."""
    tp1_r_multiple: float = 1.5          # TP1 @ 1.5R
    tp2_r_multiple: float = 2.5          # TP2 @ 2.5R
    tp1_close_ratio: float = 0.30        # TP1 平 30%
    tp2_close_ratio: float = 0.40        # TP2 平 40%
    trailing_close_ratio: float = 0.30   # 剩餘 30% trailing
    trailing_atr_multiple: float = 1.0   # trailing 回撤 1.0×ATR 全出
    volume_exhaustion_spike: float = 1.8 # 放量 ≥ 1.8×MA(V,20)
    price_stagnation_pct: float = 0.003  # 2-bar 變動 ≤ 0.3%
    exhaustion_close_ratio: float = 0.50 # 動能枯竭平 50%


class ExitLadderEngine:
    """三級階梯止盈 + 動能枯竭 (規格書 §2.1).

    R = 1.5 × ATR; 價格達 entry ± 1.5R → 平 30% + 保本;
    達 entry ± 2.5R → 平 40% + 止損移至 ±1.5R; 剩 30% trailing.
    動能枯竭 (浮盈>1R + 放量滯漲) → 平 50% 浮盈倉.
    """

    def __init__(self, config: Optional[ExitLadderConfig] = None):
        self.config = config or ExitLadderConfig()

    def _directional_gain(self, side: str, entry: float, price: float) -> float:
        """方向化收益 (多: price-entry; 空: entry-price)."""
        if side.upper() == "SHORT":
            return entry - price
        return price - entry

    def evaluate_position(
        self,
        position_side: str,
        entry_price: float,
        current_price: float,
        current_stage: LadderStage,
        highest_price: float,
        lowest_price: float,
        atr: float,
        is_exhausted: bool = False,
    ) -> Tuple[LadderStage, float, Optional[float], str]:
        """評估階梯出場.

        Returns:
            (next_stage, close_ratio_delta, new_stop_loss, action_rationale)
        """
        if entry_price <= 0 or current_price <= 0 or atr <= 0:
            return (current_stage, 0.0, None, "invalid inputs")

        r = self.config.tp1_r_multiple * atr  # R = 1.5 × ATR
        if r <= 0:
            return (current_stage, 0.0, None, "zero risk distance")

        gain = self._directional_gain(position_side, entry_price, current_price)
        tp1_level = r * self.config.tp1_r_multiple / self.config.tp1_r_multiple  # = R * 1 = 1.5ATR... 直接算
        # 標準化: TP1 = 1.5R, TP2 = 2.5R (R = 1.5ATR)
        tp1_distance = self.config.tp1_r_multiple * r
        tp2_distance = self.config.tp2_r_multiple * r

        # 動能枯竭提前平倉 (浮盈 > 1.0R 且放量滯漲)
        if current_stage in (LadderStage.INITIAL, LadderStage.TP1_HIT_30) \
                and gain > r and is_exhausted:
            return (
                LadderStage.EXHAUSTION_EARLY_EXIT,
                self.config.exhaustion_close_ratio,
                None,
                f"動能枯竭: 浮盈 {gain/r:.1f}R + 放量滯漲, 平 {self.config.exhaustion_close_ratio:.0%}",
            )

        # Stage 1: TP1 @ 1.5R
        if current_stage == LadderStage.INITIAL:
            if gain >= tp1_distance:
                return (
                    LadderStage.TP1_HIT_30,
                    self.config.tp1_close_ratio,
                    entry_price,  # 保本
                    f"TP1 @ {self.config.tp1_r_multiple}R: 平 {self.config.tp1_close_ratio:.0%}, 止損移至保本",
                )
            return (current_stage, 0.0, None, "waiting TP1")

        # Stage 2: TP2 @ 2.5R
        if current_stage == LadderStage.TP1_HIT_30:
            if gain >= tp2_distance:
                tp1_price = entry_price + self._directional_gain(
                    position_side, entry_price, entry_price + tp1_distance)
                new_sl = tp1_price  # 止損移至 TP1 價位 (鎖 1.5R)
                return (
                    LadderStage.TP2_HIT_40,
                    self.config.tp2_close_ratio,
                    new_sl,
                    f"TP2 @ {self.config.tp2_r_multiple}R: 平 {self.config.tp2_close_ratio:.0%}, 止損移至 TP1",
                )
            return (current_stage, 0.0, None, "waiting TP2")

        # Stage 3: trailing (剩餘 30%)
        if current_stage in (LadderStage.TP2_HIT_40, LadderStage.TRAILING_ACTIVE):
            peak = highest_price if position_side.upper() == "LONG" else -lowest_price
            # 對空單: peak 應為最低價 (最有利); 用 lowest_price 計算回撤
            if position_side.upper() == "SHORT":
                peak = lowest_price
                drawdown = (current_price - peak) / peak if peak > 0 else 0.0
            else:
                drawdown = (peak - current_price) / peak if peak > 0 else 0.0
            trail_dist = self.config.trailing_atr_multiple * atr
            if drawdown >= trail_dist / current_price:
                return (
                    LadderStage.CLOSED,
                    self.config.trailing_close_ratio,
                    None,
                    f"Trailing 回撤 {drawdown:.2%} ≥ {self.config.trailing_atr_multiple:.0f}ATR, 全出剩餘",
                )
            return (LadderStage.TRAILING_ACTIVE, 0.0, None, "trailing active")

        return (current_stage, 0.0, None, "no action")

    def check_volume_exhaustion(
        self,
        volumes: list,
        prices: list,
        gain_r: float,
        atr: float,
    ) -> bool:
        """動能枯竭偵測: 浮盈>1R + 放量(≥1.8×MA20) + 2-bar 停滯(≤0.3%).

        Args:
            volumes: 成交量序列 (至少 22 根)
            prices: 收盤價序列 (至少 3 根)
            gain_r: 當前浮盈 (R 單位)
            atr: ATR
        Returns:
            是否觸發動能枯竭
        """
        if len(volumes) < 22 or len(prices) < 3:
            return False
        if gain_r <= 1.0 or atr <= 0:
            return False
        vol_ma20 = sum(volumes[-21:-1]) / 20.0
        if vol_ma20 <= 0:
            return False
        vol_spike = volumes[-1] >= self.config.volume_exhaustion_spike * vol_ma20
        change_2bar = abs(prices[-1] - prices[-3]) / prices[-3]
        stagnation = change_2bar <= self.config.price_stagnation_pct
        return vol_spike and stagnation
