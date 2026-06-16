from pathlib import Path

import pytest

from vibe_trading.agents.agent_factory import ToolContext
from vibe_trading.agents.agent_tools import SubmitTradeOrderParams, get_execution_tools
from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide, SymbolFilters
from vibe_trading.execution.order_executor import PaperOrderExecutor
from vibe_trading.execution.order_executor import BinanceOrderExecutor
from vibe_trading.execution.order_audit import ExecutionAuditStorage
from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate, RiskPolicy, RiskVerdict
from vibe_trading.execution.exchange_filters import ExchangeFilterValidator
from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
from vibe_trading.main.multi_thread_main import MultiThreadedTradingSystem
from vibe_trading.config import settings as settings_module


@pytest.mark.asyncio
async def test_pre_trade_risk_gate_rejects_order_above_single_notional_limit():
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(max_single_order_notional=100, max_total_exposure=1_000),
    )

    result = await gate.validate_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        position_side=PositionSide.LONG,
        reference_price=50_000,
    )

    assert result.verdict == RiskVerdict.REJECTED
    assert "single order notional" in result.reason
    assert result.order_notional == pytest.approx(500)


@pytest.mark.asyncio
async def test_pre_trade_risk_gate_rejects_reduce_only_without_position():
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(max_single_order_notional=1_000, max_total_exposure=1_000),
    )

    result = await gate.validate_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=0.01,
        position_side=PositionSide.LONG,
        reference_price=50_000,
        reduce_only=True,
    )

    assert result.verdict == RiskVerdict.REJECTED
    assert "reduce-only" in result.reason


@pytest.mark.asyncio
async def test_pre_trade_risk_gate_rejects_hedge_position_side_when_one_way_mode():
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(
            max_single_order_notional=1_000,
            max_total_exposure=1_000,
            position_mode="one_way",
        ),
    )

    result = await gate.validate_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        position_side=PositionSide.LONG,
        reference_price=50_000,
    )

    assert result.verdict == RiskVerdict.REJECTED
    assert "one-way" in result.reason


def test_exchange_filter_validator_rejects_invalid_quantity_price_and_notional():
    filters = SymbolFilters(
        symbol="BTCUSDT",
        tick_size=0.1,
        step_size=0.001,
        min_qty=0.001,
        max_qty=100,
        min_notional=100,
    )
    validator = ExchangeFilterValidator({"BTCUSDT": filters})

    bad_qty = validator.validate(symbol="BTCUSDT", quantity=0.0015, price=50_000)
    bad_price = validator.validate(symbol="BTCUSDT", quantity=0.01, price=50_000.05)
    bad_notional = validator.validate(symbol="BTCUSDT", quantity=0.001, price=50_000)
    ok = validator.validate(symbol="BTCUSDT", quantity=0.002, price=50_000.1)

    assert bad_qty.approved is False
    assert "stepSize" in bad_qty.reason
    assert bad_price.approved is False
    assert "tickSize" in bad_price.reason
    assert bad_notional.approved is False
    assert "minNotional" in bad_notional.reason
    assert ok.approved is True


@pytest.mark.asyncio
async def test_submit_trade_order_tool_does_not_place_rejected_order():
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(max_single_order_notional=100, max_total_exposure=1_000),
    )
    context = ToolContext(symbol="BTCUSDT", interval="30m", executor=executor)
    context.risk_gate = gate
    submit_tool = get_execution_tools(context)[0]

    result = await submit_tool.execute(
        "submit_trade_order",
        SubmitTradeOrderParams(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=0.01,
            position_side="LONG",
            reference_price=50_000,
            rationale="test rejected by hard risk gate",
        ),
        None,
        None,
    )

    assert result.details["status"] == "REJECTED_BY_RISK"
    assert await executor.get_positions() == []


@pytest.mark.asyncio
async def test_submit_trade_order_tool_passes_reduce_only_to_executor():
    class RecordingExecutor(PaperOrderExecutor):
        def __init__(self):
            super().__init__(initial_balance=10_000)
            self.last_reduce_only = None

        async def place_order(self, *args, **kwargs):
            self.last_reduce_only = kwargs.get("reduce_only")
            return await super().place_order(*args, **kwargs)

    executor = RecordingExecutor()
    executor.update_price("BTCUSDT", 50_000)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        position_side=PositionSide.LONG,
    )
    context = ToolContext(symbol="BTCUSDT", interval="30m", executor=executor)
    context.risk_gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(max_single_order_notional=1_000, max_total_exposure=2_000),
    )
    submit_tool = get_execution_tools(context)[0]

    result = await submit_tool.execute(
        "submit_trade_order",
        SubmitTradeOrderParams(
            symbol="BTCUSDT",
            side="SELL",
            order_type="MARKET",
            quantity=0.01,
            position_side="LONG",
            reference_price=50_000,
            reduce_only=True,
            rationale="test reduce only close",
        ),
        None,
        None,
    )

    assert result.details["status"] == "FILLED"
    assert executor.last_reduce_only is True


@pytest.mark.asyncio
async def test_submit_trade_order_tool_does_not_place_exchange_filter_rejected_order():
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    context = ToolContext(symbol="BTCUSDT", interval="30m", executor=executor)
    context.risk_gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(max_single_order_notional=1_000, max_total_exposure=1_000),
    )
    context.exchange_filter_validator = ExchangeFilterValidator({
        "BTCUSDT": SymbolFilters(
            symbol="BTCUSDT",
            tick_size=0.1,
            step_size=0.001,
            min_qty=0.001,
            max_qty=100,
            min_notional=100,
        )
    })
    submit_tool = get_execution_tools(context)[0]

    result = await submit_tool.execute(
        "submit_trade_order",
        SubmitTradeOrderParams(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=0.0015,
            position_side="LONG",
            reference_price=50_000,
            rationale="test rejected by exchange filters",
        ),
        None,
        None,
    )

    assert result.details["status"] == "REJECTED_BY_EXCHANGE_FILTER"
    assert await executor.get_positions() == []


@pytest.mark.asyncio
async def test_binance_executor_loads_exchange_filter_validator(monkeypatch):
    executor = BinanceOrderExecutor(api_key="key", api_secret="secret", testnet=True, dry_run=True)

    async def fake_get_symbol_filters():
        return {
            "BTCUSDT": SymbolFilters(
                symbol="BTCUSDT",
                tick_size=0.1,
                step_size=0.001,
                min_qty=0.001,
                max_qty=100,
                min_notional=100,
            )
        }

    monkeypatch.setattr(executor._client.rest, "get_symbol_filters", fake_get_symbol_filters)

    validator = await executor.get_exchange_filter_validator()

    result = validator.validate(symbol="BTCUSDT", quantity=0.0015, price=50_000)
    assert result.approved is False
    assert "stepSize" in result.reason


@pytest.mark.asyncio
async def test_submit_trade_order_tool_records_fill_and_position_snapshot(tmp_path: Path):
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    context = ToolContext(symbol="BTCUSDT", interval="30m", executor=executor)
    context.current_trace_id = "trace-tool"
    context.current_bar_open_time_ms = 1_700_000_000_000
    context.risk_gate = PreTradeRiskGate(
        executor=executor,
        policy=RiskPolicy(max_single_order_notional=1_000, max_total_exposure=1_000),
    )
    context.order_audit = ExecutionAuditStorage(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    submit_tool = get_execution_tools(context)[0]

    result = await submit_tool.execute(
        "submit_trade_order",
        SubmitTradeOrderParams(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=0.01,
            position_side="LONG",
            reference_price=50_000,
            rationale="test approved by hard risk gate",
        ),
        None,
        None,
    )

    assert result.details["status"] == "FILLED"
    trace = await context.order_audit.get_trace("trace-tool")
    assert len(trace["fills"]) == 1
    assert trace["fills"][0]["order_id"] == result.details["order_id"]
    assert len(trace["position_snapshots"]) == 1
    assert trace["position_snapshots"][0]["positions"][0]["notional"] == pytest.approx(500)


@pytest.mark.asyncio
async def test_execution_audit_storage_persists_risk_checks_and_orders(tmp_path: Path):
    storage = ExecutionAuditStorage(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    await storage.init()

    await storage.record_risk_check(
        trace_id="trace-1",
        symbol="BTCUSDT",
        interval="30m",
        open_time_ms=1_700_000_000_000,
        verdict="approved",
        reason="ok",
        request={"quantity": 0.01},
        metrics={"order_notional": 500},
    )
    await storage.record_order(
        trace_id="trace-1",
        symbol="BTCUSDT",
        interval="30m",
        open_time_ms=1_700_000_000_000,
        order_id="paper_1",
        status="FILLED",
        side="BUY",
        order_type="MARKET",
        quantity=0.01,
        result={"filled_price": 50_000},
    )

    trace = await storage.get_trace("trace-1")
    assert len(trace["risk_checks"]) == 1
    assert trace["risk_checks"][0]["verdict"] == "approved"
    assert len(trace["orders"]) == 1
    assert trace["orders"][0]["order_id"] == "paper_1"


def test_trading_coordinator_wires_risk_gate_and_order_audit():
    settings_module.set_settings(settings_module.Settings(
        execution_max_single_order_notional=250,
        execution_max_total_exposure=750,
        execution_max_margin_fraction=0.25,
    ))

    coordinator = TradingCoordinator(symbol="BTCUSDT", interval="30m")

    assert coordinator._tool_context.risk_gate is not None
    assert coordinator._tool_context.risk_gate.policy.max_single_order_notional == 250
    assert coordinator._tool_context.risk_gate.policy.max_total_exposure == 750
    assert coordinator._tool_context.risk_gate.policy.max_margin_fraction == 0.25
    assert coordinator._tool_context.order_audit is not None
    settings_module.set_settings(None)


@pytest.mark.asyncio
async def test_trading_coordinator_loads_executor_exchange_filters(monkeypatch):
    executor = BinanceOrderExecutor(api_key="key", api_secret="secret", testnet=True, dry_run=True)

    async def fake_get_symbol_filters():
        return {
            "BTCUSDT": SymbolFilters(
                symbol="BTCUSDT",
                tick_size=0.1,
                step_size=0.001,
                min_qty=0.001,
                max_qty=100,
                min_notional=100,
            )
        }

    monkeypatch.setattr(executor._client.rest, "get_symbol_filters", fake_get_symbol_filters)
    coordinator = TradingCoordinator(symbol="BTCUSDT", interval="30m", executor=executor)
    await coordinator._initialize_exchange_filters()

    assert coordinator._tool_context.exchange_filter_validator is not None
    result = coordinator._tool_context.exchange_filter_validator.validate(
        symbol="BTCUSDT",
        quantity=0.0015,
        price=50_000,
    )
    assert result.approved is False


@pytest.mark.asyncio
async def test_multi_thread_system_reads_positions_from_executor():
    executor = PaperOrderExecutor(initial_balance=10_000)
    executor.update_price("BTCUSDT", 50_000)
    await executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.01,
        position_side=PositionSide.LONG,
    )
    system = MultiThreadedTradingSystem(symbol="BTCUSDT", interval="30m", executor=executor)

    positions = await system._get_positions()

    assert len(positions) == 1
    assert positions[0]["symbol"] == "BTCUSDT"
    assert positions[0]["notional"] == pytest.approx(500)


@pytest.mark.asyncio
async def test_execution_audit_storage_persists_fills_and_position_snapshots(tmp_path: Path):
    storage = ExecutionAuditStorage(f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}")
    await storage.init()

    await storage.record_fill(
        trace_id="trace-2",
        symbol="BTCUSDT",
        interval="30m",
        open_time_ms=1_700_000_000_000,
        order_id="paper_2",
        fill_id="fill_1",
        side="BUY",
        quantity=0.01,
        price=50_000,
        fee=0.1,
        fee_asset="USDT",
    )
    await storage.record_position_snapshot(
        trace_id="trace-2",
        symbol="BTCUSDT",
        interval="30m",
        open_time_ms=1_700_000_000_000,
        positions=[{"symbol": "BTCUSDT", "notional": 500}],
        balances={"USDT": {"available": 9_500}},
    )

    trace = await storage.get_trace("trace-2")
    assert len(trace["fills"]) == 1
    assert trace["fills"][0]["fill_id"] == "fill_1"
    assert len(trace["position_snapshots"]) == 1
    assert trace["position_snapshots"][0]["positions"][0]["notional"] == 500
