"""
Test P0-2: STOP/TP trigger mutual exclusivity in PaperOrderExecutor

Verifies that:
1. STOP_MARKET only triggers when price drops to/below stop_price
2. TAKE_PROFIT_MARKET only triggers when price rises to/above stop_price
3. Both orders can coexist as pending without interfering
4. Only the correct order triggers when price moves
"""
import asyncio

import pytest

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.execution.order_executor import PaperOrderExecutor


@pytest.fixture
def executor():
    """Create a fresh PaperOrderExecutor for each test."""
    return PaperOrderExecutor(initial_balance=10000.0)


@pytest.mark.asyncio
async def test_stop_market_stored_as_pending(executor):
    """STOP_MARKET order should be stored as pending, not executed immediately."""
    executor.update_price("BTCUSDT", 65000.0)
    
    result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=62000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Should be PENDING, not FILLED
    assert result.status == "PENDING"
    assert result.filled_price is None
    assert result.filled_quantity == 0
    
    # Should be in pending orders
    assert len(executor._pending_orders) == 1
    assert executor._pending_orders[0]['order_type'] == OrderType.STOP_MARKET
    assert executor._pending_orders[0]['stop_price'] == 62000.0


@pytest.mark.asyncio
async def test_take_profit_stored_as_pending(executor):
    """TAKE_PROFIT_MARKET order should be stored as pending, not executed immediately."""
    executor.update_price("BTCUSDT", 65000.0)
    
    result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity=0.001,
        stop_price=68000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    assert result.status == "PENDING"
    assert result.filled_price is None
    assert len(executor._pending_orders) == 1
    assert executor._pending_orders[0]['order_type'] == OrderType.TAKE_PROFIT_MARKET


@pytest.mark.asyncio
async def test_stop_market_triggers_on_price_drop(executor):
    """STOP_MARKET should trigger when price drops to stop_price."""
    # Setup: open a LONG position
    executor.update_price("BTCUSDT", 65000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Place STOP_MARKET at 62000
    stop_result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=62000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    assert stop_result.status == "PENDING"
    
    # Price drops but not yet to stop
    executor.update_price("BTCUSDT", 63000.0)
    assert len(executor._pending_orders) == 1  # Still pending
    
    # Price drops to stop price
    executor.update_price("BTCUSDT", 62000.0)
    
    # Wait for async execution
    await asyncio.sleep(0.1)
    
    # STOP should have triggered
    assert len(executor._pending_orders) == 0
    
    # Position should be closed
    positions = await executor.get_positions()
    assert len(positions) == 0
    
    # Realized PnL should be negative: (62000 - 65000) * 0.001 = -3.0
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(-3.0, rel=1e-2)


@pytest.mark.asyncio
async def test_take_profit_triggers_on_price_rise(executor):
    """TAKE_PROFIT_MARKET should trigger when price rises to stop_price."""
    # Setup: open a LONG position
    executor.update_price("BTCUSDT", 65000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Place TAKE_PROFIT_MARKET at 68000
    tp_result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity=0.001,
        stop_price=68000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    assert tp_result.status == "PENDING"
    
    # Price rises but not yet to TP
    executor.update_price("BTCUSDT", 67000.0)
    assert len(executor._pending_orders) == 1  # Still pending
    
    # Price rises to TP price
    executor.update_price("BTCUSDT", 68000.0)
    
    # Wait for async execution
    await asyncio.sleep(0.1)
    
    # TP should have triggered
    assert len(executor._pending_orders) == 0
    
    # Position should be closed
    positions = await executor.get_positions()
    assert len(positions) == 0
    
    # Realized PnL should be positive: (68000 - 65000) * 0.001 = 3.0
    balance_info = await executor.get_balance()
    assert balance_info["USDT"]["realized_pnl"] == pytest.approx(3.0, rel=1e-2)


@pytest.mark.asyncio
async def test_stop_and_tp_coexist_without_interference(executor):
    """Both STOP and TP can be pending simultaneously without triggering each other."""
    # Setup: open a LONG position
    executor.update_price("BTCUSDT", 65000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Place STOP at 62000 and TP at 68000
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=62000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity=0.001,
        stop_price=68000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Both should be pending
    assert len(executor._pending_orders) == 2
    
    # Price moves to 65500 - between SL and TP, neither should trigger
    executor.update_price("BTCUSDT", 65500.0)
    await asyncio.sleep(0.1)
    assert len(executor._pending_orders) == 2
    
    # Position should still be open
    positions = await executor.get_positions()
    assert len(positions) == 1


@pytest.mark.asyncio
async def test_only_stop_triggers_not_tp(executor):
    """When price drops to SL, only STOP triggers, TP stays pending."""
    executor.update_price("BTCUSDT", 65000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Place both SL and TP
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=62000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity=0.001,
        stop_price=68000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Price drops to SL
    executor.update_price("BTCUSDT", 62000.0)
    await asyncio.sleep(0.1)
    
    # STOP should have triggered, TP should still be pending
    assert len(executor._pending_orders) == 1
    assert executor._pending_orders[0]['order_type'] == OrderType.TAKE_PROFIT_MARKET
    
    # Position should be closed
    positions = await executor.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_only_tp_triggers_not_stop(executor):
    """When price rises to TP, only TP triggers, STOP stays pending."""
    executor.update_price("BTCUSDT", 65000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Place both SL and TP
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=62000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        quantity=0.001,
        stop_price=68000.0,
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Price rises to TP
    executor.update_price("BTCUSDT", 68000.0)
    await asyncio.sleep(0.1)
    
    # TP should have triggered, STOP should still be pending
    assert len(executor._pending_orders) == 1
    assert executor._pending_orders[0]['order_type'] == OrderType.STOP_MARKET
    
    # Position should be closed
    positions = await executor.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_stop_rejected_without_stop_price(executor):
    """STOP_MARKET without stop_price should be rejected."""
    executor.update_price("BTCUSDT", 65000.0)
    
    result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=None,  # Missing stop_price
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    assert result.status == "REJECTED"
    assert len(executor._pending_orders) == 0


@pytest.mark.asyncio
async def test_stop_triggers_immediately_if_already_past(executor):
    """If current price is already past stop_price, STOP triggers immediately."""
    executor.update_price("BTCUSDT", 65000.0)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        position_side=PositionSide.LONG,
    )
    
    # Place STOP at 66000 (above current price - unusual but should trigger immediately for SHORT)
    # Actually for LONG, stop at 66000 when price is 65000 shouldn't trigger
    # Let's test the correct case: stop at 64000, price drops to 63000 before placing
    executor.update_price("BTCUSDT", 63000.0)
    
    result = await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=0.001,
        stop_price=64000.0,  # Price already below this
        position_side=PositionSide.LONG,
        reduce_only=True,
    )
    
    # Should trigger immediately since price (63000) < stop_price (64000)
    await asyncio.sleep(0.1)
    assert len(executor._pending_orders) == 0
    
    # Position should be closed
    positions = await executor.get_positions()
    assert len(positions) == 0
