"""
Unit tests for PaperOrderExecutor real-ledger accounting.

Validates that the paper engine now behaves like a real margin ledger:
- BUY deducts margin (notional / leverage) from the cash balance
- SELL returns margin + credits realized PnL into the balance
- realized PnL survives a full close (position deleted from dict)
- balance reflects realized PnL even with no open positions
"""
import pytest

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.execution.order_executor import PaperOrderExecutor


@pytest.mark.asyncio
async def test_buy_deducts_margin_from_balance():
    """BUY should deduct margin (notional / leverage) from the cash balance."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)

    result = await ex.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        position_side=PositionSide.LONG,
    )

    assert result.status == "FILLED"
    bal = await ex.get_balance()
    # margin = 64000 * 0.01 / 5 = 128
    assert bal["USDT"]["balance"] == pytest.approx(10000.0 - 128.0)
    assert bal["USDT"]["realized_pnl"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_sell_full_close_credits_realized_pnl():
    """Full close should return margin and credit realized PnL into balance."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    # price rises to 65000, close full position
    ex.update_price("BTCUSDT", 65000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    bal = await ex.get_balance()
    # realized = (65000 - 64000) * 0.01 = 10
    # balance = 10000 - 128 (margin) + 128 (margin returned) + 10 (profit) = 10010
    assert bal["USDT"]["balance"] == pytest.approx(10010.0)
    assert bal["USDT"]["realized_pnl"] == pytest.approx(10.0)

    positions = await ex.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_realized_pnl_survives_full_close():
    """Regression: realized PnL must persist after position is deleted."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    # losing trade: close at 63000
    ex.update_price("BTCUSDT", 63000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    bal = await ex.get_balance()
    # realized = (63000 - 64000) * 0.01 = -10
    assert bal["USDT"]["realized_pnl"] == pytest.approx(-10.0)
    assert bal["USDT"]["balance"] == pytest.approx(9990.0)


@pytest.mark.asyncio
async def test_partial_close_credits_only_closed_qty():
    """Partial close should credit realized PnL only for the closed quantity."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.02, position_side=PositionSide.LONG,
    )

    ex.update_price("BTCUSDT", 65000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    bal = await ex.get_balance()
    # realized on 0.01 closed = (65000-64000)*0.01 = 10
    assert bal["USDT"]["realized_pnl"] == pytest.approx(10.0)
    # margin: bought 0.02 @64000 (margin 256), closed 0.01 (margin back 128 @entry price)
    # balance = 10000 - 256 + 128 + 10 = 9882
    assert bal["USDT"]["balance"] == pytest.approx(9882.0)

    positions = await ex.get_positions()
    assert len(positions) == 1
    assert positions[0].position_amount == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_close_without_position_is_noop():
    """Closing a non-existent position must not corrupt the ledger."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 65000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    bal = await ex.get_balance()
    assert bal["USDT"]["balance"] == pytest.approx(10000.0)
    assert bal["USDT"]["realized_pnl"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_add_position_averages_entry_price():
    """Adding to a position should re-average the entry price."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )
    ex.update_price("BTCUSDT", 66000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    positions = await ex.get_positions()
    assert len(positions) == 1
    assert positions[0].position_amount == pytest.approx(0.02)
    assert positions[0].entry_price == pytest.approx(65000.0)


@pytest.mark.asyncio
async def test_unrealized_pnl_tracks_mark_price():
    """Unrealized PnL should update with mark price while position is open."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    ex.update_price("BTCUSDT", 64500.0)
    bal = await ex.get_balance()
    # unrealized = (64500 - 64000) * 0.01 = 5
    assert bal["USDT"]["unrealized_pnl"] == pytest.approx(5.0)
    # available = cash balance + unrealized
    assert bal["USDT"]["available"] == pytest.approx(10000.0 - 128.0 + 5.0)


@pytest.mark.asyncio
async def test_short_position_realized_pnl():
    """SHORT position: profit when price falls."""
    ex = PaperOrderExecutor(initial_balance=10000.0)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.SHORT,
    )

    ex.update_price("BTCUSDT", 63000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.SHORT,
    )

    bal = await ex.get_balance()
    # realized = (64000 - 63000) * 0.01 = 10
    assert bal["USDT"]["realized_pnl"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 持久化：跨重啟保留 balance / positions / realized_pnl
# ---------------------------------------------------------------------------
import json
from pathlib import Path

from vibe_trading.execution.order_executor import create_executor, TradingMode


@pytest.mark.asyncio
async def test_state_persists_across_restart(tmp_path):
    """Restart (new executor, same state_file) must restore balance + positions."""
    state_file = str(tmp_path / "paper_account.json")
    ex = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    # simulate restart
    ex2 = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    bal = await ex2.get_balance()
    assert bal["USDT"]["balance"] == pytest.approx(10000.0 - 128.0)
    positions = await ex2.get_positions()
    assert len(positions) == 1
    assert positions[0].position_amount == pytest.approx(0.01)
    assert positions[0].entry_price == pytest.approx(64000.0)


@pytest.mark.asyncio
async def test_reset_flag_ignores_state_file(tmp_path):
    """reset=True must start fresh even when a state file exists."""
    state_file = str(tmp_path / "paper_account.json")
    ex = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    ex2 = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file, reset=True)
    bal = await ex2.get_balance()
    assert bal["USDT"]["balance"] == pytest.approx(10000.0)
    assert await ex2.get_positions() == []


@pytest.mark.asyncio
async def test_no_state_file_starts_fresh(tmp_path):
    """No state file → fresh account with initial balance."""
    state_file = str(tmp_path / "does_not_exist.json")
    ex = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    bal = await ex.get_balance()
    assert bal["USDT"]["balance"] == pytest.approx(10000.0)
    assert bal["USDT"]["realized_pnl"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_realized_pnl_survives_restart_after_full_close(tmp_path):
    """Realized PnL from a fully closed trade must survive restart."""
    state_file = str(tmp_path / "paper_account.json")
    ex = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )
    ex.update_price("BTCUSDT", 65000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.SELL, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    ex2 = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    bal = await ex2.get_balance()
    assert bal["USDT"]["realized_pnl"] == pytest.approx(10.0)
    assert bal["USDT"]["balance"] == pytest.approx(10010.0)
    assert await ex2.get_positions() == []


@pytest.mark.asyncio
async def test_save_state_writes_json_file(tmp_path):
    """place_order must persist state to the JSON file."""
    state_file = str(tmp_path / "paper_account.json")
    ex = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    ex.update_price("BTCUSDT", 64000.0)
    await ex.place_order(
        symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET,
        quantity=0.01, position_side=PositionSide.LONG,
    )

    data = json.loads(Path(state_file).read_text(encoding="utf-8"))
    assert data["balance"] == pytest.approx(10000.0 - 128.0)
    assert data["realized_pnl"] == pytest.approx(0.0)
    assert len(data["positions"]) == 1
    assert data["positions"][0]["quantity"] == pytest.approx(0.01)


def test_create_executor_paper_passes_state_file(tmp_path):
    """create_executor(PAPER) must forward paper_state_file / reset_paper."""
    state_file = str(tmp_path / "paper_account.json")
    ex = create_executor(TradingMode.PAPER, paper_state_file=state_file, reset_paper=True)
    assert isinstance(ex, PaperOrderExecutor)
    assert ex._state_file == state_file
