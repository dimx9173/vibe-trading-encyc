"""Tests for PaperOrderExecutor internals (Wave D — coverage 85% plan)."""
import json
import os
from unittest.mock import MagicMock

import pytest

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.execution.order_executor import PaperOrderExecutor, PaperPosition


class TestPaperPosition:
    def test_notional(self):
        p = PaperPosition(symbol="BTCUSDT", position_side=PositionSide.LONG,
                          entry_price=50000.0, quantity=0.1)
        assert p.notional == 5000.0

    def test_update_unrealized_pnl_long(self):
        p = PaperPosition(symbol="BTCUSDT", position_side=PositionSide.LONG,
                          entry_price=50000.0, quantity=0.1)
        p.update_unrealized_pnl(51000.0)
        assert p.unrealized_pnl == pytest.approx(100.0)

    def test_update_unrealized_pnl_short(self):
        p = PaperPosition(symbol="BTCUSDT", position_side=PositionSide.SHORT,
                          entry_price=50000.0, quantity=0.1)
        p.update_unrealized_pnl(49000.0)
        assert p.unrealized_pnl == pytest.approx(100.0)


class TestStatePersistence:
    def test_save_and_load(self, tmp_path):
        state_file = str(tmp_path / "paper.json")
        ex = PaperOrderExecutor(initial_balance=5000.0, state_file=state_file)
        # 建倉
        ex._positions["BTCUSDT_LONG"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.LONG,
            entry_price=50000.0, quantity=0.1)
        ex._realized_pnl = 150.0
        ex._save_state()
        assert os.path.exists(state_file)

        # 新 executor 載入
        ex2 = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
        assert ex2._balance == 5000.0
        assert ex2._realized_pnl == 150.0
        assert len(ex2._positions) == 1
        pos = ex2._positions["BTCUSDT_LONG"]
        assert pos.entry_price == 50000.0

    def test_load_missing_file(self, tmp_path):
        ex = PaperOrderExecutor(state_file=str(tmp_path / "nope.json"))
        assert ex._balance == 10000.0  # 預設

    def test_load_corrupt_file(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json{{{")
        ex = PaperOrderExecutor(state_file=str(f))
        assert ex._balance == 10000.0  # fail-safe

    def test_no_state_file_no_save(self):
        ex = PaperOrderExecutor()
        ex._save_state()  # 不 raise

    def test_reset_flag(self, tmp_path):
        state_file = str(tmp_path / "paper.json")
        ex = PaperOrderExecutor(initial_balance=5000.0, state_file=state_file)
        ex._save_state()
        ex2 = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file, reset=True)
        assert ex2._balance == 10000.0  # reset 忽略 state


class TestFunding:
    def test_is_funding_hour(self):
        ex = PaperOrderExecutor()
        # UTC 08:00 = 8h
        import datetime as dt
        open_ms = int(dt.datetime(2026, 1, 1, 8, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        assert ex._is_funding_hour(open_ms) is True
        open_ms2 = int(dt.datetime(2026, 1, 1, 5, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        assert ex._is_funding_hour(open_ms2) is False

    def test_settle_funding_long(self):
        ex = PaperOrderExecutor(initial_balance=10000.0)
        ex._positions["BTCUSDT_LONG"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.LONG,
            entry_price=50000.0, quantity=1.0, leverage=5)
        import datetime as dt
        open_ms = int(dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        result = ex.settle_funding("BTCUSDT", open_ms, mark_price=50000.0, funding_rate=0.0001)
        assert result["settled"] is True
        assert result["fee"] == pytest.approx(5.0)  # 1.0 * 50000 * 0.0001
        assert ex._balance == pytest.approx(9995.0)

    def test_settle_funding_dedup(self):
        ex = PaperOrderExecutor()
        ex._positions["BTCUSDT_LONG"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.LONG,
            entry_price=50000.0, quantity=1.0, leverage=5)
        import datetime as dt
        open_ms = int(dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        ex.settle_funding("BTCUSDT", open_ms, 50000.0)
        # 同 hour 再結算 → 跳過
        result = ex.settle_funding("BTCUSDT", open_ms + 1000, 50000.0)
        assert result["settled"] is False

    def test_settle_funding_non_funding_hour(self):
        ex = PaperOrderExecutor()
        ex._positions["BTCUSDT_LONG"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.LONG,
            entry_price=50000.0, quantity=1.0, leverage=5)
        import datetime as dt
        open_ms = int(dt.datetime(2026, 1, 1, 3, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        result = ex.settle_funding("BTCUSDT", open_ms, 50000.0)
        assert result["settled"] is False

    def test_settle_funding_spot_no_funding(self):
        ex = PaperOrderExecutor()
        ex._positions["BTCUSDT_LONG"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.LONG,
            entry_price=50000.0, quantity=1.0, leverage=1)  # 現貨
        import datetime as dt
        open_ms = int(dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        result = ex.settle_funding("BTCUSDT", open_ms, 50000.0)
        assert result["fee"] == 0.0
        assert result["settled"] is False


class TestMaintenanceRate:
    def test_tiers(self):
        ex = PaperOrderExecutor()
        assert ex._maintenance_rate(50_000) == 0.004
        assert ex._maintenance_rate(200_000) == 0.006
        assert ex._maintenance_rate(2_000_000) == 0.02
        assert ex._maintenance_rate(50_000_000) == 0.10


class TestGetSet:
    @pytest.mark.asyncio
    async def test_get_balance_positions(self):
        ex = PaperOrderExecutor(initial_balance=1234.0)
        bal = await ex.get_balance()
        assert bal["USDT"]["balance"] == 1234.0
        assert await ex.get_positions() == []
        assert await ex.cancel_order("BTCUSDT", "x") is False  # 無此訂單


class TestPendingOrders:
    def _pending(self, order_type, stop_price):
        return {
            "order_id": "o1", "symbol": "BTCUSDT", "side": OrderSide.SELL,
            "order_type": order_type, "quantity": 0.1,
            "position_side": PositionSide.LONG, "stop_price": stop_price,
            "reduce_only": True,
        }

    def test_stop_market_triggers(self):
        ex = PaperOrderExecutor()
        pending = self._pending(OrderType.STOP_MARKET, 49000.0)
        ex._pending_orders.append(pending)
        ex._positions["BTCUSDT_LONG"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.LONG,
            entry_price=50000.0, quantity=0.1, leverage=5)
        ex.update_price("BTCUSDT", 48000.0)  # 觸發 STOP
        assert pending not in ex._pending_orders
        assert "BTCUSDT_LONG" not in ex._positions  # 平倉

    def test_stop_market_not_triggered(self):
        ex = PaperOrderExecutor()
        pending = self._pending(OrderType.STOP_MARKET, 49000.0)
        ex._pending_orders.append(pending)
        ex.update_price("BTCUSDT", 50000.0)  # 未觸發
        assert pending in ex._pending_orders

    def test_take_profit_triggers(self):
        ex = PaperOrderExecutor()
        pending = self._pending(OrderType.TAKE_PROFIT_MARKET, 51000.0)
        ex._pending_orders.append(pending)
        ex.update_price("BTCUSDT", 51500.0)  # 觸發 TP
        assert pending not in ex._pending_orders

    def test_execute_pending_order_direct(self):
        ex = PaperOrderExecutor()
        pending = self._pending(OrderType.STOP_MARKET, 49000.0)
        result = ex._execute_pending_order(pending, 48000.0)
        assert result is not None
        assert result.order_id == "o1"


class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_place_order_opens_long(self):
        ex = PaperOrderExecutor(initial_balance=10000.0)
        result = await ex.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 0.1,
            position_side=PositionSide.LONG,
        )
        assert result.status in ("FILLED", "PENDING", "SUBMITTED")
        assert "BTCUSDT_LONG" in ex._positions

    @pytest.mark.asyncio
    async def test_place_order_zero_qty_fills(self):
        ex = PaperOrderExecutor()
        result = await ex.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 0.0)
        assert result.status == "FILLED"  # paper 模式無 qty 驗證

    @pytest.mark.asyncio
    async def test_conditional_no_stop_rejected(self):
        ex = PaperOrderExecutor()
        result = await ex.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.STOP_MARKET, 0.1)
        assert result.status == "REJECTED"

    @pytest.mark.asyncio
    async def test_place_order_short_close(self):
        ex = PaperOrderExecutor(initial_balance=10000.0)
        ex._positions["BTCUSDT_SHORT"] = PaperPosition(
            symbol="BTCUSDT", position_side=PositionSide.SHORT,
            entry_price=50000.0, quantity=0.1, leverage=5)
        result = await ex.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 0.1,
            position_side=PositionSide.SHORT, reduce_only=True,
        )
        assert "BTCUSDT_SHORT" not in ex._positions  # 平倉

    @pytest.mark.asyncio
    async def test_place_order_pending_stop(self):
        ex = PaperOrderExecutor()
        result = await ex.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.STOP_MARKET, 0.1,
            stop_price=49000.0,
        )
        assert result.status in ("PENDING", "FILLED")
