"""Tests for RuleEngineLoop (spec phase1 §7 core acceptance)."""
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.data_sources.kline_storage import Kline as StorageKline
from vibe_trading.execution.order_executor import PaperOrderExecutor
from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate, RiskPolicy
from vibe_trading.rule_engine.config import RuleEngineConfig
from vibe_trading.rule_engine.loop import RuleEngineLoop

FACTORS_LONG = {
    "momentum_12_1": 0.05,
    "rate_of_change": 0.02,
    "trend_strength": 0.6,
    "atr": 1.0,
}
FACTORS_FLAT = {"atr": 1.0}
LOOSE_POLICY = RiskPolicy(
    max_single_order_notional=1000.0,
    max_total_exposure=5000.0,
    max_margin_fraction=1.0,
    min_confidence=0.0,
)


def _kline(close: float = 100.0, open_time: "Optional[int]" = None,
           high: "Optional[float]" = None, low: "Optional[float]" = None) -> StorageKline:
    ot = open_time or int(time.time() * 1000)
    return StorageKline(
        symbol="BTCUSDT", interval="30m", open_time=ot,
        open=close * 0.995, high=high or close * 1.01, low=low or close * 0.99,
        close=close, volume=1000.0,
        close_time=ot + 1800000 - 1, quote_volume=0.0, trades=0,
        taker_buy_base=0.0, taker_buy_quote=0.0, is_final=True,
    )


def _macro_state(regime: str, strength: str = "STRONG") -> MagicMock:
    state = MagicMock()
    state.market_regime = regime
    state.trend_strength = strength
    state.overall_sentiment = "POSITIVE"
    state.timestamp = int(time.time() * 1000)
    return state


def _macro_storage(regime: str) -> MagicMock:
    storage = MagicMock()
    storage.get_latest_state = AsyncMock(return_value=_macro_state(regime))
    return storage


def _audit() -> MagicMock:
    audit = MagicMock()
    audit.record_risk_check = AsyncMock()
    audit.record_order = AsyncMock()
    return audit


def _make_loop(executor=None, regime="BULL", factors=None, policy=None,
               symbol="BTCUSDT", config=None) -> RuleEngineLoop:
    storage = MagicMock()
    storage.store_kline = AsyncMock()
    storage.query_klines = AsyncMock(return_value=[])
    loop = RuleEngineLoop(
        symbol=symbol,
        interval="30m",
        storage=storage,
        executor=executor,
        macro_storage=_macro_storage(regime),
        config=config or RuleEngineConfig(),
        audit_storage=_audit(),
    )
    if factors is not None:
        loop._recent_factors = AsyncMock(return_value=factors)
    if policy is not None:
        loop._risk_gate = PreTradeRiskGate(executor, policy)
    return loop


class TestRiskOffBlocksNewEntries:
    @pytest.mark.asyncio
    async def test_risk_off_blocks_open_and_no_position(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="RISK_OFF", factors=FACTORS_LONG)
        decision = await loop.on_bar(_kline(100.0))
        assert decision.blocked_by == "RISK_OFF"
        assert decision.direction == "FLAT"
        assert (await executor.get_positions()) == []
        assert decision.action == "hold"

    @pytest.mark.asyncio
    async def test_risk_off_records_regime(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="RISK_OFF", factors=FACTORS_LONG)
        decision = await loop.on_bar(_kline(100.0))
        assert decision.regime == "RISK_OFF"


class TestExitLadderDerivedFromConfig:
    @pytest.mark.asyncio
    async def test_ladder_tp_scales_with_rule_config(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        cfg = RuleEngineConfig(sl_atr_mult=2.0, tp_atr_mult=4.0, entry_threshold=0.0)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG,
                          policy=LOOSE_POLICY, config=cfg)
        assert loop._ladder.config.r_atr_multiple == pytest.approx(2.0)
        assert loop._ladder.config.tp1_r_multiple == pytest.approx(0.6 * 4.0 / 2.0)
        assert loop._ladder.config.tp2_r_multiple == pytest.approx(4.0 / 2.0)

    @pytest.mark.asyncio
    async def test_wide_tp_defers_ladder_stage(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        executor.update_price("BTCUSDT", 100.0)
        await executor.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 2.0,
            position_side=PositionSide.LONG,
        )
        # tp_atr_mult=8 → TP1 @ 0.6×8=4.8 (price 104.8); atr=1.0 (FACTORS_LONG).
        # 旧固定阶梯 TP1=2.25 → close 103.0 (gain 3.0) 已触发 reduce; 修复后应仍 hold.
        cfg = RuleEngineConfig(sl_atr_mult=1.0, tp_atr_mult=8.0, entry_threshold=0.0)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG,
                          policy=LOOSE_POLICY, config=cfg)
        d = await loop.on_bar(_kline(103.0))
        assert d.action == "hold"
        positions = await executor.get_positions()
        assert len(positions) == 1


class TestRiskOffDoesNotBlockExits:
    @pytest.mark.asyncio
    async def test_exit_proceeds_under_risk_off(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        executor.update_price("BTCUSDT", 100.0)
        await executor.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 2.0,
            position_side=PositionSide.LONG,
        )
        loop = _make_loop(executor, regime="RISK_OFF", factors=FACTORS_LONG, policy=LOOSE_POLICY)

        # RISK_OFF 下 TP1 (default config sl=1.5/tp=2.5 → TP1 = 0.6×2.5×ATR = 1.5, close 101.5) → reduce 30%
        # 注: 102.25 > TP2 (2.5×ATR = 102.5) 下沿, 仍处 TP1 阶段
        d1 = await loop.on_bar(_kline(102.25))
        assert d1.action == "reduce"
        assert d1.qty == pytest.approx(0.6, rel=0.01)
        positions = await executor.get_positions()
        assert len(positions) == 1
        assert positions[0].position_amount == pytest.approx(1.4, rel=0.01)

        # 下一 bar 止损已移至保本 (entry 100), 价格回落 → 全平 (仍处 RISK_OFF)
        d2 = await loop.on_bar(_kline(99.0))
        assert d2.action == "exit"
        assert (await executor.get_positions()) == []


class TestNeutralHalfPosition:
    @pytest.mark.asyncio
    async def test_neutral_qty_is_half_of_risk_on(self):
        executor_on = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop_on = _make_loop(executor_on, regime="BULL", factors=FACTORS_LONG, policy=LOOSE_POLICY)
        d_on = await loop_on.on_bar(_kline(100.0))
        assert d_on.action == "open"

        executor_neutral = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop_neutral = _make_loop(executor_neutral, regime="NEUTRAL", factors=FACTORS_LONG,
                                  policy=LOOSE_POLICY)
        d_neutral = await loop_neutral.on_bar(_kline(100.0))
        assert d_neutral.action == "open"
        assert d_neutral.regime == "NEUTRAL"

        assert d_on.qty > 0
        assert d_neutral.qty == pytest.approx(0.5 * d_on.qty, rel=0.01)

    @pytest.mark.asyncio
    async def test_risk_on_opens_position(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG, policy=LOOSE_POLICY)
        d = await loop.on_bar(_kline(100.0))
        assert d.action == "open"
        positions = await executor.get_positions()
        assert len(positions) == 1
        assert positions[0].position_side == PositionSide.LONG


class TestSingleExitAuthority:
    @pytest.mark.asyncio
    async def test_internal_ladder_disabled_no_auto_exit(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        executor.update_price("BTCUSDT", 100.0)
        await executor.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0,
            position_side=PositionSide.LONG,
        )
        executor.update_price("BTCUSDT", 110.0)  # +10%: 简单阶梯会 moonbag 卖半
        positions = await executor.get_positions()
        assert len(positions) == 1
        assert positions[0].position_amount == pytest.approx(1.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_default_executor_keeps_internal_ladder(self):
        executor = PaperOrderExecutor(initial_balance=10000.0)
        executor.update_price("BTCUSDT", 100.0)
        await executor.place_order(
            "BTCUSDT", OrderSide.BUY, OrderType.MARKET, 1.0,
            position_side=PositionSide.LONG,
        )
        executor.update_price("BTCUSDT", 110.0)  # +10% → moonbag sell half
        positions = await executor.get_positions()
        assert len(positions) == 1
        assert positions[0].position_amount == pytest.approx(0.5, abs=1e-9)


class TestStoreBeforeDecide:
    @pytest.mark.asyncio
    async def test_kline_stored_before_signal_computed(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", policy=LOOSE_POLICY)
        events: list = []

        async def _store(k):
            events.append("store")

        async def _factors():
            events.append("factors")
            return FACTORS_LONG

        loop.storage.store_kline = AsyncMock(side_effect=_store)
        loop._recent_factors = AsyncMock(side_effect=_factors)
        await loop.on_bar(_kline(100.0))
        assert events == ["store", "factors"]


class TestFlatAndRiskGate:
    @pytest.mark.asyncio
    async def test_flat_signal_holds(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_FLAT)
        d = await loop.on_bar(_kline(100.0))
        assert d.action == "hold"
        assert d.direction == "FLAT"
        assert (await executor.get_positions()) == []

    @pytest.mark.asyncio
    async def test_risk_gate_rejects_oversized_order(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        # 显式严格策略: max_single_order_notional=100 (默认对齐策略允许 config 上限 500,
        # 无法触发拒绝; 用严格策略保持拒单路径测试确定性)
        strict = RiskPolicy(max_single_order_notional=100.0, max_total_exposure=300.0,
                            max_margin_fraction=0.5, min_confidence=0.0)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG, policy=strict)
        d = await loop.on_bar(_kline(100.0))
        assert d.blocked_by == "risk_gate"
        assert (await executor.get_positions()) == []


class TestRuleDecisionShape:
    @pytest.mark.asyncio
    async def test_decision_records_full_picture(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG, policy=LOOSE_POLICY)
        k = _kline(100.0)
        d = await loop.on_bar(k)
        payload = d.to_dict()
        assert payload["symbol"] == "BTCUSDT"
        assert payload["bar_open_time"] == k.open_time
        assert payload["regime"] == "RISK_ON"
        assert payload["action"] == "open"
        assert payload["qty"] > 0
        assert payload["signal"]["direction"] == "LONG"


class TestInitialStopProtection:
    """P0-1: 开仓即武装初始 hard stop (1.5×ATR)，TP1 达成前有止损保护."""

    @pytest.mark.asyncio
    async def test_close_below_initial_stop_exits_full(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG, policy=LOOSE_POLICY)
        t0 = int(time.time() * 1000)
        d_open = await loop.on_bar(_kline(100.0, open_time=t0))
        assert d_open.action == "open"
        # FACTORS_LONG atr=1.0 → sl = 100 − 1.5×1.0 = 98.5；下一 bar 收盘 98.0 跌破 → 全平
        d_exit = await loop.on_bar(_kline(98.0, open_time=t0 + 1800000))
        assert d_exit.action == "exit"
        assert (await executor.get_positions()) == []
        assert "stop" in d_exit.reason

    @pytest.mark.asyncio
    async def test_close_above_initial_stop_not_hard_stopped(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG, policy=LOOSE_POLICY)
        t0 = int(time.time() * 1000)
        await loop.on_bar(_kline(100.0, open_time=t0))
        # 98.6 > 98.5 → 非 hard stop 触发（可能 reduce/hold，但不得 exit-全平于 stop）
        d = await loop.on_bar(_kline(98.6, open_time=t0 + 1800000))
        assert d.action != "exit"


class TestMarketWideRegime:
    """P0-3: macro regime 是市场级判断 — ETH loop 读到主币 (BTC) 写入的同一 regime."""

    @pytest.mark.asyncio
    async def test_eth_loop_reads_btc_written_regime(self):
        executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
        loop = _make_loop(executor, regime="BULL", factors=FACTORS_LONG,
                          policy=LOOSE_POLICY, symbol="ETHUSDT")
        d = await loop.on_bar(_kline(100.0))
        assert d.symbol == "ETHUSDT"
        assert d.regime == "RISK_ON"
        assert d.action == "open"