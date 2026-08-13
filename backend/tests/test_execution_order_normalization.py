"""
TDD tests for B8/B9 — PM tool 路徑訂單正規化 (agent_tools.create_submit_trade_order_tool).

B8: MARKET 單不該帶 price — L712-714 fill_price fallback 把 risk effective_price
    塞進 MARKET 單 → Binance -1106 "Parameter 'price' sent when not required".
B9: PM 直接路徑未過 OrderBuilder — LLM 送 qty=0.01(超 cap) / position_side=BOTH(撞 hedge)
    / reference_price=None → risk 連三拒 (06:37 鐵證 orders #255-257).

修復契約:
    C1: MARKET 單 place_order(price=None); 只有 LIMIT/非市價單才套 effective_price fallback
    C2: hedge mode + position_side=BOTH → 自動推導 LONG/SHORT
    C3: 非 reduce_only 時 qty cap 至 notional ≤ 100 (floor stepSize)
    C4: reference_price 缺時自動從 executor 取價
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vibe_trading.agents.agent_tools import create_submit_trade_order_tool, SubmitTradeOrderParams
from vibe_trading.data_sources.binance_client import PositionSide
from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate, RiskPolicy


class RecordingExecutor:
    """記錄 place_order 參數 + 提供參考價的 mock executor."""

    def __init__(self, ref_price: float = 63878.0, positions: list = None):
        self.ref_price = ref_price
        self.positions = positions or []
        self.calls = []

    def get_reference_price(self, symbol: str) -> float:
        return self.ref_price

    async def get_positions(self):
        return self.positions

    async def get_balance(self):
        return {"USDT": {"balance": 10000.0, "available": 10000.0, "unrealized_pnl": 0.0, "realized_pnl": 0.0}}

    async def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            order_id="paper_test123",
            symbol=kwargs["symbol"],
            side=kwargs["side"],
            order_type=kwargs["order_type"],
            quantity=kwargs["quantity"],
            price=kwargs["price"],
            filled_price=kwargs["price"],
            filled_quantity=kwargs["quantity"],
            status="FILLED",
            is_paper=True,
        )


def _make_ctx(executor: RecordingExecutor):
    risk_gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(
            max_single_order_notional=100.0,
            max_total_exposure=300.0,
            max_margin_fraction=0.5,
            position_mode="hedge",
        ),
    )
    return SimpleNamespace(
        executor=executor,
        risk_gate=risk_gate,
        order_audit=None,  # 簡化: 跳過 audit (record_order 有 getattr guard)
        exchange_filter_validator=None,
        interval="30m",
        current_trace_id="BTCUSDT:30m:1786600800000",
        current_bar_open_time_ms=1786600800000,
        symbol="BTCUSDT",
    )


# === C1: B8 MARKET 不帶 price ===
@pytest.mark.asyncio
async def test_T1_market_order_does_not_send_price():
    """MARKET 單: fill_price fallback 不套用 → place_order(price=None)."""
    ex = RecordingExecutor(ref_price=63878.0)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    await tool.execute(
        "t1",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="MARKET",
            quantity=0.0015, position_side="SHORT", reference_price=63878.0,
        ),
    )
    assert ex.calls, "place_order 必須被呼叫"
    assert ex.calls[0]["price"] is None, f"MARKET 單 price 應為 None, got {ex.calls[0]['price']}"


# === C2: B9 hedge + BOTH → LONG/SHORT ===
@pytest.mark.asyncio
async def test_T2_hedge_both_normalized_to_side():
    """position_side=BOTH + hedge → 自動推導 LONG (不再被風控拒)."""
    ex = RecordingExecutor(ref_price=63878.0)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    await tool.execute(
        "t2",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="BUY", order_type="MARKET",
            quantity=0.0015, position_side="BOTH", reference_price=63878.0,
        ),
    )
    assert ex.calls, "BOTH 正規化後 place_order 必須被呼叫 (風險不再拒)"
    assert ex.calls[0]["position_side"] == PositionSide.LONG


# === C3: B9 qty cap ===
@pytest.mark.asyncio
async def test_T3_quantity_capped_to_notional():
    """LLM qty=0.01 (notional 638) → cap 至 0.0015 (≤100)."""
    ex = RecordingExecutor(ref_price=63878.0)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    await tool.execute(
        "t3",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="MARKET",
            quantity=0.01, position_side="SHORT", reference_price=63878.0,
        ),
    )
    assert ex.calls, "qty cap 後 place_order 必須被呼叫"
    q = ex.calls[0]["quantity"]
    assert q * 63878.0 <= 100.0 + 1e-9, f"notional 應 ≤100, got {q*63878.0}"
    assert q == 0.0015


# === C4: B9 reference_price 自動補 ===
@pytest.mark.asyncio
async def test_T4_reference_price_auto_filled():
    """reference_price=None → 自動從 executor 取價 → 風控 approved."""
    ex = RecordingExecutor(ref_price=63878.0)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    await tool.execute(
        "t4",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="MARKET",
            quantity=0.0015, position_side="SHORT", reference_price=None,
        ),
    )
    assert ex.calls, "ref 自動補後 place_order 必須被呼叫 (不再 'reference price required')"


# === C4b: reduce_only 不 cap (殘倉平倉需精確 qty) ===
@pytest.mark.asyncio
async def test_T5_reduce_only_keeps_quantity():
    """reduce_only=True → 不 cap qty (平倉用殘倉精確數量)."""
    # risk gate 對 reduce_only 要求既有持倉
    from vibe_trading.execution.order_executor import Position

    pos = Position(
        symbol="BTCUSDT",
        position_amount=0.0004,
        entry_price=64000.0,
        mark_price=63878.0,
        unrealized_profit=-0.05,
        liquidation_price=0.0,
        leverage=5,
        position_side=PositionSide.LONG,
        notional=25.6,
        isolated=False,
        adl_quantile=0,
    )
    ex = RecordingExecutor(ref_price=63878.0, positions=[pos])
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    await tool.execute(
        "t5",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="MARKET",
            quantity=0.0004, position_side="LONG", reference_price=63878.0,
            reduce_only=True,
        ),
    )
    assert ex.calls
    assert ex.calls[0]["quantity"] == 0.0004, "reduce_only 不應被 cap"
