"""
TDD tests for B10 — MARKET 訂單不該套用 tickSize 價格對齊驗證 (agent_tools 的
exchange filter 驗證端).

B10 鐵證 (2026-08-13 09:37:36 order #260): SELL MARKET 0.0015, risk approved
(notional 95.49), 但本地 ExchangeFilterValidator 收到 price=63657.73
(args.reference_price fallback) → "price is not aligned to tickSize 0.1" →
REJECTED_BY_EXCHANGE_FILTER。

根因: agent_tools.py 對 filter 驗證傳 `price=args.price or args.reference_price`,
無條件套用 PRICE_FILTER.tickSize。Binance 的 tickSize 只適用於 LIMIT 價格;
MARKET 單根本不帶 price (B8 已修 place_order 送價端, 此處修 filter 驗證端)。

修復契約:
    B10-C1: MARKET 單 → filter 驗證 price=None (跳 tickSize, 保留 qty stepSize)
    B10-C2: LIMIT 單 → 仍驗 tickSize (不對齊照樣拒)
    B10-C3: qty 對齊 stepSize 檢查不受影響
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vibe_trading.agents.agent_tools import create_submit_trade_order_tool, SubmitTradeOrderParams
from vibe_trading.data_sources.binance_client import SymbolFilters
from vibe_trading.execution.exchange_filters import ExchangeFilterValidator
from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate, RiskPolicy


class RecordingExecutor:
    """記錄 place_order 參數 + 提供參考價的 mock executor (與 B8/B9 測試同款)."""

    def __init__(self, ref_price: float = 63657.73):
        self.ref_price = ref_price
        self.calls = []

    def get_reference_price(self, symbol: str) -> float:
        return self.ref_price

    async def get_positions(self):
        return []

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
    ctx = SimpleNamespace(
        executor=executor,
        risk_gate=risk_gate,
        order_audit=None,
        exchange_filter_validator=None,
        interval="30m",
        current_trace_id="BTCUSDT:30m:1786611600000",
        current_bar_open_time_ms=1786611600000,
        symbol="BTCUSDT",
    )
    # 掛上真實的 Binance BTCUSDT filter (與 testnet exchangeInfo 一致)
    ctx.exchange_filter_validator = ExchangeFilterValidator(
        {
            "BTCUSDT": SymbolFilters(
                symbol="BTCUSDT",
                tick_size=0.1,
                step_size=0.0001,
                min_qty=0.0001,
                max_qty=1000.0,
                min_notional=50.0,
            )
        }
    )
    return ctx


# === B10-C1: MARKET 單跳 tickSize ===
@pytest.mark.asyncio
async def test_market_order_skips_price_alignment():
    """MARKET 單 + reference_price → 不該被 tickSize 拒 (order #260 場景)."""
    ex = RecordingExecutor(ref_price=63657.73)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    res = await tool.execute(
        "t1",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="MARKET",
            quantity=0.0015, position_side="SHORT", reference_price=63657.73,
        ),
    )
    details = res.details or {}
    assert details.get("status") == "FILLED", (
        f"MARKET 單不應被 tickSize 拒, got {details.get('status')}: "
        f"{details.get('exchange_filter')}"
    )
    assert ex.calls and ex.calls[0]["price"] is None


# === B10-C2: LIMIT 單仍驗 tickSize ===
@pytest.mark.asyncio
async def test_limit_order_still_checks_price_alignment():
    """LIMIT 單 price 未對齊 tickSize → 仍被拒 (不因 B10 放寬)."""
    ex = RecordingExecutor(ref_price=63657.73)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    res = await tool.execute(
        "t2",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="LIMIT",
            quantity=0.0015, price=63657.73, position_side="SHORT",
            reference_price=63657.73,
        ),
    )
    details = res.details or {}
    assert details.get("status") == "REJECTED_BY_EXCHANGE_FILTER", (
        f"LIMIT 未對齊 price 應被拒, got {details.get('status')}"
    )
    assert "tickSize" in (details.get("exchange_filter") or {}).get("reason", "")


@pytest.mark.asyncio
async def test_limit_order_aligned_price_passes():
    """LIMIT 單 price 對齊 tickSize → 通過 (正常 LIMIT 路徑不破壞)."""
    ex = RecordingExecutor(ref_price=63657.7)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    res = await tool.execute(
        "t3",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="LIMIT",
            quantity=0.0015, price=63657.7, position_side="SHORT",
            reference_price=63657.7,
        ),
    )
    details = res.details or {}
    assert details.get("status") == "FILLED", (
        f"LIMIT 對齊 price 應通過, got {details.get('status')}: "
        f"{details.get('exchange_filter')}"
    )


# === B10-C3: qty stepSize 檢查不受影響 ===
@pytest.mark.asyncio
async def test_market_order_still_rejects_bad_quantity():
    """MARKET 單 qty 未對齊 stepSize → 仍被拒 (B1 防線保留)."""
    ex = RecordingExecutor(ref_price=63657.73)
    tool = create_submit_trade_order_tool(_make_ctx(ex))

    res = await tool.execute(
        "t4",
        SubmitTradeOrderParams(
            symbol="BTCUSDT", side="SELL", order_type="MARKET",
            quantity=0.00015, position_side="SHORT", reference_price=63657.73,
        ),
    )
    details = res.details or {}
    assert details.get("status") == "REJECTED_BY_EXCHANGE_FILTER", (
        f"qty 未對齊 stepSize 應被拒, got {details.get('status')}"
    )
    assert "stepSize" in (details.get("exchange_filter") or {}).get("reason", "")
