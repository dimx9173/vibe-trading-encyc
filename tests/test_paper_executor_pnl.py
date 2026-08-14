"""
Test P0-1: realized_pnl calculation in PaperOrderExecutor

Verifies that:
1. SELL orders correctly calculate and accumulate realized PnL
2. Multiple BUY → partial SELL cycles maintain correct PnL
3. PnL persists across state save/load cycles
"""

import pytest

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.execution.order_executor import PaperOrderExecutor


@pytest.fixture
def executor():
    """Create a fresh PaperOrderExecutor for each test."""
    return PaperOrderExecutor(initial_balance=10000.0)


@pytest.fixture
def executor_with_state_file(tmp_path):
    """Create executor with state file for persistence tests."""
    state_file = tmp_path / "paper_account.json"
    return PaperOrderExecutor(initial_balance=10000.0, state_file=str(state_file))


@pytest.mark.asyncio
async def test_buy_sell_simple_profit(executor):
    """Test simple BUY → SELL with profit."""
    # Setup: set price and buy
    executor.update_price("BTCUSDT", 50000.0)
    
    # BUY 0.001 BTC at 50000
    buy_result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    assert buy_result.status == "FILLED"
    assert buy_result.filled_price == 50000.0
    
    # Price goes up to 51000
    executor.update_price("BTCUSDT", 51000.0)
    
    # SELL 0.001 BTC at 51000
    sell_result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    assert sell_result.status == "FILLED"
    assert sell_result.filled_price == 51000.0
    
    # Check realized PnL: (51000 - 50000) * 0.001 = 1.0
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(1.0, rel=1e-6)


@pytest.mark.asyncio
async def test_buy_sell_simple_loss(executor):
    """Test simple BUY → SELL with loss."""
    executor.update_price("BTCUSDT", 50000.0)
    
    # BUY 0.001 BTC at 50000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Price drops to 49000
    executor.update_price("BTCUSDT", 49000.0)
    
    # SELL 0.001 BTC at 49000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Check realized PnL: (49000 - 50000) * 0.001 = -1.0
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(-1.0, rel=1e-6)


@pytest.mark.asyncio
async def test_multiple_buys_partial_sell(executor):
    """Test multiple BUY orders followed by partial SELL."""
    executor.update_price("BTCUSDT", 50000.0)
    
    # BUY 0.001 BTC at 50000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Price goes to 51000
    executor.update_price("BTCUSDT", 51000.0)
    
    # BUY another 0.001 BTC at 51000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Now we have 0.002 BTC at avg price (50000 + 51000) / 2 = 50500
    positions = await executor.get_positions()
    assert len(positions) == 1
    assert positions[0].position_amount == pytest.approx(0.002, rel=1e-6)
    assert positions[0].entry_price == pytest.approx(50500.0, rel=1e-6)
    
    # Price goes to 52000
    executor.update_price("BTCUSDT", 52000.0)
    
    # SELL 0.001 BTC at 52000 (partial close)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # PnL: (52000 - 50500) * 0.001 = 1.5
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(1.5, rel=1e-6)
    
    # Still have 0.001 BTC position
    positions = await executor.get_positions()
    assert len(positions) == 1
    assert positions[0].position_amount == pytest.approx(0.001, rel=1e-6)


@pytest.mark.asyncio
async def test_realized_pnl_accumulation(executor):
    """Test that realized PnL accumulates across multiple trades."""
    executor.update_price("BTCUSDT", 50000.0)
    
    # Trade 1: BUY at 50000, SELL at 51000 → +1.0
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    executor.update_price("BTCUSDT", 51000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(1.0, rel=1e-6)
    
    # Trade 2: BUY at 51000, SELL at 50500 → -0.5
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    executor.update_price("BTCUSDT", 50500.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Total PnL: 1.0 - 0.5 = 0.5
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(0.5, rel=1e-6)


@pytest.mark.asyncio
async def test_realized_pnl_persistence(executor_with_state_file):
    """Test that realized PnL persists across executor restart."""
    executor = executor_with_state_file
    
    executor.update_price("BTCUSDT", 50000.0)
    
    # BUY and SELL with profit
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    executor.update_price("BTCUSDT", 51000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Check PnL before restart
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(1.0, rel=1e-6)
    
    # Create new executor with same state file
    state_file = executor._state_file
    executor2 = PaperOrderExecutor(initial_balance=10000.0, state_file=state_file)
    
    # Check PnL after restart
    balance_info2 = await executor2.get_balance()
    assert balance_info2["USDT"]["realized_pnl"] == pytest.approx(1.0, rel=1e-6)


@pytest.mark.asyncio
async def test_realized_pnl_with_leverage(executor):
    """Test realized PnL calculation with leverage."""
    executor.update_price("BTCUSDT", 50000.0)
    
    # BUY with 5x leverage
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Position should have leverage=5
    positions = await executor.get_positions()
    assert len(positions) == 1
    assert positions[0].leverage == 5
    
    executor.update_price("BTCUSDT", 51000.0)
    
    # SELL
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # PnL should be same regardless of leverage: (51000 - 50000) * 0.001 = 1.0
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(1.0, rel=1e-6)


@pytest.mark.asyncio
async def test_short_position_pnl(executor):
    """Test realized PnL for short positions."""
    executor.update_price("BTCUSDT", 50000.0)
    
    # SELL (open short) at 50000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.SHORT,
    )
    
    # Price drops to 49000 (profit for short)
    executor.update_price("BTCUSDT", 49000.0)
    
    # BUY (close short) at 49000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.SHORT,
        reduce_only=True,
    )
    
    # PnL for short: (50000 - 49000) * 0.001 = 1.0
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(1.0, rel=1e-6)
