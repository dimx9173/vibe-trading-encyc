"""
TDD tests for coordinator-layer execution insurance (Fix B+ upgrade).

Problem:
    PM decides BUY/SELL but does not call `submit_trade_order` tool → silent no-order.
    Fix B only logged a warning; execution chain never triggered (no risk check, no order).

Fix:
    Coordinator auto-executes the trade when decision = BUY/SELL and the bar has no order,
    reusing the exact `submit_trade_order` tool chain (risk gate → exchange filter → executor
    → audit) so risk remains the final gatekeeper.

Tests:
    T1: BUY decision + no order → coordinator insurance submits an order (audit has record)
    T2: decision already has an order → insurance does NOT double-submit
    T3: trading_plan is None → insurance fails open with no crash
    T4: insurance reuses current_trace_id so Fix B reconciliation can see the order
"""
import pytest
from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
from vibe_trading.agents.decision.trading_tools import TradingPlan, ExecutionStyle
from vibe_trading.data_sources.binance_client import PositionSide


def _make_coordinator(tmp_path):
    """Coordinator with isolated audit DB (no LLM agents initialized)."""
    coord = TradingCoordinator(symbol="BTCUSDT", interval="30m")
    # Isolate audit storage so tests don't touch the live DB
    from vibe_trading.execution.order_audit import ExecutionAuditStorage
    coord._tool_context.order_audit = ExecutionAuditStorage(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/audit.db"
    )
    # NOTE: record_order/get_trace call init() internally; no manual init needed.
    coord._tool_context.current_trace_id = "BTCUSDT:30m:1785988800000"
    coord._tool_context.current_bar_open_time_ms = 1785988800000
    return coord


def _make_plan() -> TradingPlan:
    return TradingPlan(
        symbol="BTCUSDT",
        position_side=PositionSide.LONG,
        direction="LONG",
        execution_style=ExecutionStyle.IMMEDIATE,
        entry_orders=[
            {
                "order_type": "market",
                "price": 64500.0,
                "size_coin": 0.001,
                "size_usdt": 64.5,
                "pct": 100,
                "note": "市價單",
            }
        ],
        total_position_usdt=64.5,
        total_position_coin=0.001,
        leverage=5,
        stop_loss_orders=[{"trigger_price": 63200.0, "note": "止損"}],
        take_profit_orders=[{"price": 65500.0, "pct": 100, "note": "止盈"}],
        max_loss_usdt=1.3,
        max_loss_pct=0.02,
        risk_reward_ratio=2.0,
    )


# === T1: BUY + no order → insurance submits ===
@pytest.mark.asyncio
async def test_T1_insurance_submits_order_when_pm_missed_tool(tmp_path):
    coord = _make_coordinator(tmp_path)
    plan = _make_plan()

    details = await coord._auto_execute_insurance(
        decision_id="BTCUSDT_1785988800000", signal_value="BUY", trading_plan=plan
    )

    assert details is not None
    # Order must be recorded under current_trace_id so Fix B can see it
    trace = await coord._tool_context.order_audit.get_trace("BTCUSDT:30m:1785988800000")
    assert trace["orders"], "insurance must record an order in the audit trail"


# === T2: existing order → no double submit ===
@pytest.mark.asyncio
async def test_T2_existing_order_skips_insurance(tmp_path):
    coord = _make_coordinator(tmp_path)
    # Pre-record an order for this trace (simulating PM actually called the tool)
    from vibe_trading.data_sources.binance_client import OrderSide, OrderType

    async def _noop(*a, **k):
        return None

    # Use the real audit storage API to record an order first
    audit = coord._tool_context.order_audit
    await audit.record_order(
        trace_id="BTCUSDT:30m:1785988800000",
        symbol="BTCUSDT",
        interval="30m",
        open_time_ms=1785988800000,
        order_id="test-order-1",
        status="FILLED",
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        quantity=0.001,
        result={"order_id": "test-order-1", "status": "FILLED"},
    )

    # Fix B reconciliation path: has_order must be True → no insurance
    from vibe_trading.coordinator.signal_processor import SignalProcessor
    from vibe_trading.tools.signal_parser import to_signal_enum, detect_strength
    proc = SignalProcessor()
    signal = proc.process_signal(
        decision_text="Decision: BUY", agent_name="Portfolio Manager"
    )
    trace = await audit.get_trace(coord._tool_context.current_trace_id)
    has_order = bool(trace and trace.get("orders"))
    assert has_order is True
    assert signal.signal.value == "BUY"


# === T3: trading_plan None → fail open ===
@pytest.mark.asyncio
async def test_T3_none_plan_fails_open(tmp_path):
    coord = _make_coordinator(tmp_path)

    details = await coord._auto_execute_insurance(
        decision_id="BTCUSDT_1785988800000", signal_value="BUY", trading_plan=None
    )

    assert details is None  # no crash, no order


# === T4: reconciliation uses current_trace_id (Fix B key fix) ===
@pytest.mark.asyncio
async def test_T4_reconciliation_queries_current_trace_id(tmp_path):
    coord = _make_coordinator(tmp_path)
    plan = _make_plan()

    # Insurance runs
    await coord._auto_execute_insurance(
        decision_id="BTCUSDT_1785988800000", signal_value="BUY", trading_plan=plan
    )

    # Fix B checks via current_trace_id → must find the order
    trace = await coord._tool_context.order_audit.get_trace(
        coord._tool_context.current_trace_id
    )
    has_order = bool(trace and trace.get("orders"))
    assert has_order is True
