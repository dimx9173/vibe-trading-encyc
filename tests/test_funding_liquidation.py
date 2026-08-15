"""Tests for perpetual fidelity (Phase 2.3) — funding settlement + tiered liquidation."""
import asyncio
from datetime import datetime, timezone

import pytest

from vibe_trading.execution.order_executor import (
    OrderSide,
    OrderType,
    PaperOrderExecutor,
    PositionSide,
)


def _funding_ms(hour: int) -> int:
    """今天指定 UTC 小時的 ms 時間戳."""
    now = datetime.now(timezone.utc)
    return int(datetime(now.year, now.month, now.day, hour, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _run(coro):
    return asyncio.run(coro)


async def _open_long(executor, qty=1.0, price=100.0, leverage=10):
    executor.update_price("BTCUSDT", price)
    await executor.place_order(
        "BTCUSDT", OrderSide.BUY, OrderType.MARKET, qty,
        price=price, position_side=PositionSide.LONG,
    )
    # 設定槓桿 (place_order 無 leverage 參數, PaperPosition 預設 5)
    key = f"BTCUSDT_{PositionSide.LONG.value}"
    if key in executor._positions:
        executor._positions[key].leverage = leverage
    return executor


class TestFunding:
    def _executor(self, leverage=10):
        ex = PaperOrderExecutor(initial_balance=10000.0, reset=True)
        return ex

    @pytest.mark.asyncio
    async def test_funding_hour_detection(self):
        ex = self._executor()
        assert ex._is_funding_hour(_funding_ms(0)) is True
        assert ex._is_funding_hour(_funding_ms(8)) is True
        assert ex._is_funding_hour(_funding_ms(16)) is True
        assert ex._is_funding_hour(_funding_ms(5)) is False

    @pytest.mark.asyncio
    async def test_funding_fee_deducted(self):
        ex = self._executor()
        await _open_long(ex, qty=1.0, price=100.0)
        # 建倉時 leverage=5 (place_order 無 leverage 參數): 扣 margin 20 → balance 9980
        r = ex.settle_funding("BTCUSDT", _funding_ms(8), 100.0, funding_rate=0.001)
        assert r["settled"] is True
        # fee = 1.0 × 100 × 0.001 = 0.1
        assert abs(r["fee"] - 0.1) < 1e-9
        assert abs(ex._balance - (9980.0 - 0.1)) < 1e-6

    @pytest.mark.asyncio
    async def test_funding_no_double_settle(self):
        ex = self._executor()
        await _open_long(ex)
        ms = _funding_ms(8)
        ex.settle_funding("BTCUSDT", ms, 100.0)
        r2 = ex.settle_funding("BTCUSDT", ms + 1_800_000, 100.0)  # 同小時
        assert r2["settled"] is False
        assert r2["fee"] == 0.0

    @pytest.mark.asyncio
    async def test_funding_non_settlement_hour(self):
        ex = self._executor()
        await _open_long(ex)
        r = ex.settle_funding("BTCUSDT", _funding_ms(5), 100.0)
        assert r["settled"] is False

    @pytest.mark.asyncio
    async def test_funding_short_pays(self):
        """short 持倉 + 正費率 → balance 增加 (收到 funding)."""
        ex = PaperOrderExecutor(initial_balance=10000.0, reset=True)
        ex.update_price("BTCUSDT", 100.0)
        await ex.place_order(
            "BTCUSDT", OrderSide.SELL, OrderType.MARKET, 1.0,
            price=100.0, position_side=PositionSide.SHORT,
        )
        key = f"BTCUSDT_{PositionSide.SHORT.value}"
        if key in ex._positions:
            ex._positions[key].leverage = 10
        r = ex.settle_funding("BTCUSDT", _funding_ms(8), 100.0, funding_rate=0.001)
        assert r["settled"] is True
        # short + 正費率 → fee 為負 (收取), balance 增加
        assert r["fee"] < 0
        assert ex._balance > 9980.0  # 建倉扣 20, funding 收 0.1 → 9980.1


class TestLiquidation:
    def _executor(self):
        return PaperOrderExecutor(initial_balance=10000.0, reset=True)

    @pytest.mark.asyncio
    async def test_liquidation_triggered(self):
        ex = self._executor()
        await _open_long(ex, qty=1.0, price=100.0)  # 10x
        ex.update_price("BTCUSDT", 50.0)  # 跌 50%
        assert len(ex._positions) == 0
        assert len(ex._liquidation_events) == 1
        ev = ex._liquidation_events[-1]
        assert ev["symbol"] == "BTCUSDT"
        assert ev["side"] == "LONG"
        assert ev["realized"] < 0  # 虧損

    @pytest.mark.asyncio
    async def test_liquidation_not_triggered(self):
        ex = self._executor()
        await _open_long(ex, qty=1.0, price=100.0)
        ex.update_price("BTCUSDT", 95.0)  # 小跌 5%
        assert len(ex._positions) == 1  # 未強平
        assert len(ex._liquidation_events) == 0

    @pytest.mark.asyncio
    async def test_low_leverage_not_liquidated(self):
        ex = PaperOrderExecutor(initial_balance=10000.0, reset=True)
        await _open_long(ex, qty=1.0, price=100.0, leverage=10)
        # 現貨 (leverage=1) 不強平
        ex._positions["BTCUSDT_LONG"].leverage = 1
        ex.update_price("BTCUSDT", 50.0)  # 跌 50%
        assert len(ex._positions) == 1  # 現貨不強平
        assert len(ex._liquidation_events) == 0

    def test_maintenance_tier(self):
        ex = self._executor()
        assert ex._maintenance_rate(50_000) == 0.004
        assert ex._maintenance_rate(300_000) == 0.006
        assert ex._maintenance_rate(2_000_000) == 0.02
        assert ex._maintenance_rate(50_000_000) == 0.10

    @pytest.mark.asyncio
    async def test_liquidation_balance_refund(self):
        """強平後剩餘保證金退回 balance."""
        ex = self._executor()
        await _open_long(ex, qty=1.0, price=100.0, leverage=10)  # 10x, margin 10, balance 9990
        ex.update_price("BTCUSDT", 50.0)  # 跌 50%: margin+unrealized = 10-50 = -40 ≤ 0.2 → 強平
        assert len(ex._positions) == 0
        assert len(ex._liquidation_events) == 1
        assert ex._balance < 10000.0  # 有虧損
