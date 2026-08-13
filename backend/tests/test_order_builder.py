"""
TDD tests for OrderBuilder — 統一訂單建構 (VBT B1-B4 執行鏈修復).

背景:
    保險路徑 (trading_coordinator.py _auto_execute_insurance) 與 PM 路徑
    (agent_tools.py create_submit_trade_order_tool) 各自建構訂單參數, 導致:
      B1: qty=0.0015768 未 floor stepSize 0.0001 → REJECTED_BY_EXCHANGE_FILTER
      B2: reference_price=None → REJECTED_BY_RISK "reference price is required"
      B3: position_side=BOTH 撞 hedge mode → REJECTED_BY_RISK
      B4: qty=0.01 notional=636 > cap 100 → REJECTED_BY_RISK

設計:
    單一 OrderBuilder 保證 A1-A4:
      A1: qty 必為 stepSize 整數倍且 ≥ min_qty、notional ≥ min_notional
      A2: reference_price 必填, 缺則 raise MissingReferencePriceError
      A3: hedge → positionSide=LONG/SHORT, one-way → BOTH
      A4: notional ≤ max_single_order_notional (100)

真實參數 (deviation #59 教訓 — 不用 synthetic):
    reference_price = 63618.7 (2026-08-13 04:07 bar 實際值)
    step_size = 0.0001, min_qty = 0.0001, min_notional = 50
    notional_cap = 100.0
"""
import pytest

from vibe_trading.execution.order_builder import (
    OrderBuilder,
    OrderBuildResult,
    MissingReferencePriceError,
    floor_to_step,
    compute_quantity,
    resolve_position_side,
)
from vibe_trading.data_sources.binance_client import OrderSide, PositionSide

# 真實參數 (2026-08-13 04:07 鐵證)
REF_PRICE = 63618.7
STEP_SIZE = 0.0001
MIN_QTY = 0.0001
MIN_NOTIONAL = 50.0
NOTIONAL_CAP = 100.0


# === A1: qty 對齊 stepSize ===
def test_T1_floor_to_step_alignment():
    """0.0015768 → 0.0015 (floor 到 0.0001 整數倍, 非四捨五入)."""
    assert floor_to_step(0.0015768, 0.0001) == 0.0015
    assert floor_to_step(0.0010001, 0.0001) == 0.0010
    assert floor_to_step(0.01, 0.0001) == 0.01


def test_T2_compute_quantity_capped_and_aligned():
    """cap=100, ref=63618.7 → qty=0.0015, notional=95.43 ≤ 100 且對齊 step."""
    qty = compute_quantity(
        notional_cap=NOTIONAL_CAP,
        reference_price=REF_PRICE,
        step_size=STEP_SIZE,
        min_qty=MIN_QTY,
        min_notional=MIN_NOTIONAL,
    )
    assert qty == 0.0015
    assert qty * REF_PRICE <= NOTIONAL_CAP
    # notional 必須 ≥ min_notional (50)
    assert qty * REF_PRICE >= MIN_NOTIONAL


def test_T3_quantity_never_exceeds_cap():
    """各種價格下 notional 永 ≤ cap."""
    for px in (50000.0, 63618.7, 70000.0, 120000.0):
        qty = compute_quantity(
            notional_cap=NOTIONAL_CAP,
            reference_price=px,
            step_size=STEP_SIZE,
            min_qty=MIN_QTY,
            min_notional=MIN_NOTIONAL,
        )
        assert qty * px <= NOTIONAL_CAP + 1e-9


# === A2: reference_price 必填 ===
def test_T4_missing_reference_price_raises():
    """reference_price=None → MissingReferencePriceError (不再送 None 給風控)."""
    with pytest.raises(MissingReferencePriceError):
        compute_quantity(
            notional_cap=NOTIONAL_CAP,
            reference_price=None,  # type: ignore[arg-type]
            step_size=STEP_SIZE,
            min_qty=MIN_QTY,
            min_notional=MIN_NOTIONAL,
        )


# === A3: position_side 推導 ===
def test_T5_hedge_mode_resolves_long_short():
    """hedge: BUY→LONG, SELL→SHORT (不再預設 BOTH)."""
    assert resolve_position_side(OrderSide.BUY, "hedge") == PositionSide.LONG
    assert resolve_position_side(OrderSide.SELL, "hedge") == PositionSide.SHORT


def test_T6_one_way_mode_resolves_both():
    """one-way: 任何 side → BOTH."""
    assert resolve_position_side(OrderSide.BUY, "one_way") == PositionSide.BOTH
    assert resolve_position_side(OrderSide.SELL, "one_way") == PositionSide.BOTH


# === A4 + 整合: OrderBuilder 產出合法訂單 ===
def test_T7_order_builder_full_build():
    """完整建構: BUY + hedge + ref=63618.7 → qty=0.0015, LONG, notional≤100."""
    builder = OrderBuilder(
        reference_price=REF_PRICE,
        position_mode="hedge",
        step_size=STEP_SIZE,
        min_qty=MIN_QTY,
        min_notional=MIN_NOTIONAL,
        notional_cap=NOTIONAL_CAP,
    )
    result: OrderBuildResult = builder.build(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type="MARKET",
        rationale="test",
    )
    assert result.quantity == 0.0015
    assert result.position_side == PositionSide.LONG
    assert result.reference_price == REF_PRICE
    assert result.quantity * REF_PRICE <= NOTIONAL_CAP
    assert result.quantity * REF_PRICE >= MIN_NOTIONAL


def test_T8_order_builder_missing_price_raises():
    """builder 缺 reference_price → 建構前即 raise (保險/PM 都無法送出無價單)."""
    builder = OrderBuilder(
        reference_price=None,  # type: ignore[arg-type]
        position_mode="hedge",
        step_size=STEP_SIZE,
        min_qty=MIN_QTY,
        min_notional=MIN_NOTIONAL,
        notional_cap=NOTIONAL_CAP,
    )
    with pytest.raises(MissingReferencePriceError):
        builder.build(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type="MARKET",
            rationale="test",
        )


def test_T9_below_min_notional_raises():
    """min_notional 守衛: notional ≈ cap 但 < min_notional(更高) → raise, 不送無法執行的單.

    注意: 在 cap=100 / min_notional=50 的實際配置下, floor 後 notional≈99 永不觸發;
    此檢查是 min_qty 之上的第二道守衛 (適用 min_notional > cap 或直接 qty 輸入情境).
    """
    with pytest.raises(ValueError):
        compute_quantity(
            notional_cap=NOTIONAL_CAP,
            reference_price=REF_PRICE,
            step_size=STEP_SIZE,
            min_qty=MIN_QTY,
            min_notional=150.0,  # > cap: notional≈95 必 < 150 → raise
        )


def test_T10_below_min_qty_raises():
    """參考價過高使 cap 換算 qty < min_qty(0.0001) → raise."""
    with pytest.raises(ValueError):
        compute_quantity(
            notional_cap=NOTIONAL_CAP,
            reference_price=1_200_000.0,  # 100/1200000 = 0.000083 < 0.0001
            step_size=STEP_SIZE,
            min_qty=MIN_QTY,
            min_notional=MIN_NOTIONAL,
        )
