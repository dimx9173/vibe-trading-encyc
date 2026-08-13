"""Unified order construction — 唯一訂單建構入口 (VBT B1-B4 執行鏈修復).

背景:
    保險路徑 (trading_coordinator._auto_execute_insurance) 與 PM 路徑
    (agent_tools.create_submit_trade_order_tool) 各自建構訂單參數, 造成:
      B1: qty 未 floor stepSize 0.0001 → REJECTED_BY_EXCHANGE_FILTER
      B2: reference_price=None → REJECTED_BY_RISK "reference price is required"
      B3: position_side=BOTH 撞 hedge mode → REJECTED_BY_RISK
      B4: qty 超 notional cap 100 → REJECTED_BY_RISK

本模組是兩條路徑的唯一訂單建構入口, 保證 A1-A4:
    A1: qty 必為 stepSize 整數倍且 ≥ min_qty、notional ≥ min_notional
    A2: reference_price 必填, 缺則 raise MissingReferencePriceError
    A3: hedge → positionSide=LONG/SHORT, one-way → BOTH
    A4: notional ≤ max_single_order_notional
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from vibe_trading.data_sources.binance_client import OrderSide, PositionSide


class MissingReferencePriceError(ValueError):
    """reference_price 必填, 缺則在送出前 raise (不送無價單給風控/交易所)."""


def floor_to_step(qty: float, step_size: float) -> float:
    """0.0015768 → 0.0015 (floor 到 step 整數倍, 非四捨五入; 浮點安全)."""
    if step_size <= 0:
        raise ValueError(f"step_size must be > 0, got {step_size}")
    steps = math.floor(qty / step_size + 1e-9)
    return round(steps * step_size, 10)


def compute_quantity(
    *,
    notional_cap: float,
    reference_price: Optional[float],
    step_size: float,
    min_qty: float,
    min_notional: float,
) -> float:
    """qty = floor(notional_cap / reference_price 到 step); 校驗 min_qty / min_notional.

    Raises:
        MissingReferencePriceError: reference_price 缺或 ≤ 0
        ValueError: 換算後 qty < min_qty 或 notional < min_notional (不可執行)
    """
    if not reference_price or reference_price <= 0:
        raise MissingReferencePriceError(
            f"reference_price is required for quantity computation, got {reference_price!r}"
        )

    qty = floor_to_step(notional_cap / reference_price, step_size)

    if qty < min_qty:
        raise ValueError(
            f"computed qty {qty} < min_qty {min_qty} "
            f"(notional_cap={notional_cap}, reference_price={reference_price})"
        )
    if qty * reference_price < min_notional:
        raise ValueError(
            f"computed notional {qty * reference_price:.2f} < min_notional {min_notional} "
            f"(qty={qty}, reference_price={reference_price})"
        )
    return qty


def resolve_position_side(side: OrderSide, position_mode: str) -> PositionSide:
    """hedge → BUY=LONG / SELL=SHORT; one_way → BOTH (與 pre_trade_risk 對齊)."""
    if position_mode == "hedge":
        return PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT
    return PositionSide.BOTH


@dataclass
class OrderBuildResult:
    """完整、已驗證的訂單參數, 可直接送入 executor.place_order."""

    symbol: str
    side: OrderSide
    order_type: str
    quantity: float
    price: Optional[float]
    reference_price: float
    position_side: PositionSide
    reduce_only: bool
    rationale: str
    stop_price: Optional[float] = None
    notional: float = field(init=False)

    def __post_init__(self) -> None:
        self.notional = self.quantity * self.reference_price


class OrderBuilder:
    """單一訂單建構器 — 保險路徑與 PM 路徑共用, 參數合法性由 build() 保證."""

    def __init__(
        self,
        *,
        reference_price: Optional[float],
        position_mode: str = "hedge",
        step_size: float = 0.0001,
        min_qty: float = 0.0001,
        min_notional: float = 50.0,
        notional_cap: float = 100.0,
    ) -> None:
        self.reference_price = reference_price
        self.position_mode = position_mode
        self.step_size = step_size
        self.min_qty = min_qty
        self.min_notional = min_notional
        self.notional_cap = notional_cap

    def build(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        rationale: str = "",
    ) -> OrderBuildResult:
        quantity = compute_quantity(
            notional_cap=self.notional_cap,
            reference_price=self.reference_price,
            step_size=self.step_size,
            min_qty=self.min_qty,
            min_notional=self.min_notional,
        )
        position_side = resolve_position_side(side, self.position_mode)
        assert self.reference_price is not None  # compute_quantity 已驗證非 None
        return OrderBuildResult(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            reference_price=self.reference_price,
            position_side=position_side,
            reduce_only=reduce_only,
            rationale=rationale,
            stop_price=stop_price,
        )
