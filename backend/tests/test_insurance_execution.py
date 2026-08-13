"""
TDD tests for coordinator insurance execution (VBT B5/B6).

背景:
    B5 (P0): 2026-08-13 04:07:20/26 risk APPROVED 後無對應 order 記錄 — 執行鏈斷。
    B6 (P0): 執行對帳把 REJECTED_BY_RISK 的 order 記錄也算 has_order,
             保險誤判「已有訂單」→ approved 無單時安全網癱瘓。

修復契約:
    C1: 對帳只認有效訂單 (FILLED/SUBMITTED/PENDING) — REJECTED 不阻擋保險
    C2: 保險觸發後 60s cooldown — 防 04:07 式 6 秒 3 連砲
    C3: 保險執行成功後 audit 必有 order 記錄 (B5 回歸)
"""
import pytest

from vibe_trading.coordinator.trading_coordinator import TradingCoordinator


# === C1: 對帳只認有效訂單 (B6) ===
def test_T6_rejected_order_does_not_block_insurance():
    """REJECTED_BY_RISK 訂單不算 has_order → 保險仍應觸發."""
    # 模擬對帳查詢結果: 只有一筆 REJECTED 訂單
    rejected_orders = [
        {
            "status": "REJECTED_BY_RISK",
            "created_at": "2026-08-13T04:07:16",
            "order_id": None,
        }
    ]
    # 對帳邏輯 (L855 has_order) 應過濾 rejected — 用 coordinator 的 helper 驗證
    from vibe_trading.coordinator import trading_coordinator as tc_mod

    has_valid = tc_mod._has_valid_order(rejected_orders, cycle_start=None)
    assert has_valid is False, "REJECTED 訂單不應算 has_order (B6)"


def test_T6b_valid_order_blocks_insurance():
    """FILLED 訂單算 has_order → 保險不觸發 (不雙重下單)."""
    from vibe_trading.coordinator import trading_coordinator as tc_mod

    filled_orders = [
        {
            "status": "FILLED",
            "created_at": "2026-08-13T04:07:44",
            "order_id": "paper_abc123",
        }
    ]
    assert tc_mod._has_valid_order(filled_orders, cycle_start=None) is True


# === C2: cooldown (04:07 6 秒 3 連砲防護) ===
def test_T7_insurance_cooldown_blocks_resubmit():
    """60s 內第二次觸發保險應被 cooldown 擋下."""

    coord = TradingCoordinator(symbol="BTCUSDT", interval="30m")
    # 模擬上次觸發是剛剛
    coord._last_insurance_at = 1000.0
    coord._insurance_cooldown_s = 300.0

    from vibe_trading.coordinator import trading_coordinator as tc_mod

    blocked = tc_mod._insurance_on_cooldown(coord._last_insurance_at, coord._insurance_cooldown_s, now_ts=1100.0)
    assert blocked is True, "cooldown 期間不應重送"

    # 超過 cooldown 後可再送
    blocked = tc_mod._insurance_on_cooldown(coord._last_insurance_at, coord._insurance_cooldown_s, now_ts=1000.0 + 300.0 + 1.0)
    assert blocked is False


# === C3: 保險執行成功 → audit 必有 order (B5 回歸) ===
@pytest.mark.asyncio
async def test_T8_insurance_approved_produces_order_record(tmp_path):
    """保險路徑走 OrderBuilder (A1-A4) → risk approved → audit 有 order 記錄."""

    from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
    from vibe_trading.agents.decision.trading_tools import TradingPlan, ExecutionStyle
    from vibe_trading.data_sources.binance_client import PositionSide
    from vibe_trading.execution.order_audit import ExecutionAuditStorage

    coord = TradingCoordinator(symbol="BTCUSDT", interval="30m")
    coord._tool_context.order_audit = ExecutionAuditStorage(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/audit.db"
    )
    coord._tool_context.current_trace_id = "BTCUSDT:30m:1786591800000"
    coord._tool_context.current_bar_open_time_ms = 1786591800000

    plan = TradingPlan(
        symbol="BTCUSDT",
        position_side=PositionSide.LONG,
        direction="LONG",
        execution_style=ExecutionStyle.IMMEDIATE,
        entry_orders=[
            {
                "order_type": "market",
                "price": 63618.7,
                "size_coin": 0.01,  # 原始 PM 建議 (超 cap)
                "size_usdt": 636.19,
                "pct": 100,
                "note": "市價單",
            }
        ],
        total_position_usdt=636.19,
        total_position_coin=0.01,
        leverage=5,
        stop_loss_orders=[],
        take_profit_orders=[],
        max_loss_usdt=10.0,
        max_loss_pct=0.02,
        risk_reward_ratio=1.0,
    )

    # 保險路徑: 應 cap 至 100/63618.7=0.00157 → floor 0.0015, LONG, ref 必填
    details = await coord._auto_execute_insurance(
        decision_id="BTCUSDT_1786593600773",
        signal_value="BUY",
        trading_plan=plan,
    )
    assert details is not None, "保險應執行成功"

    trace = await coord._tool_context.order_audit.get_trace("BTCUSDT:30m:1786591800000")
    orders = trace.get("orders", []) or []
    assert orders, "保險執行成功後 audit 必有 order 記錄 (B5 回歸)"
    # 最後一筆不應是 REJECTED_BY_RISK (A1-A4 保證參數合法)
    last_status = orders[-1].get("status", "")
    assert "REJECTED_BY_RISK" not in last_status, f"不應被風控拒: {last_status}"
    assert "REJECTED_BY_EXCHANGE_FILTER" not in last_status, f"不應被 filter 拒: {last_status}"
