"""Task 6 integration: per-mode exits + discrete LLM de-risk wiring."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.data_sources.kline_storage import Kline as StorageKline
from vibe_trading.execution.order_executor import PaperOrderExecutor
from vibe_trading.execution.pre_trade_risk import RiskPolicy
from vibe_trading.rule_engine.config import RuleEngineConfig
from vibe_trading.rule_engine.loop import RuleEngineLoop

FACTORS_LONG_MOM = {
    "momentum_12_1": 0.08,
    "rate_of_change": 0.04,
    "atr": 1.0,
    "bollinger_band_width": 0.02,
    "rsi_zscore": 0.1,
    "price_to_ma": 0.01,
}
FACTORS_MR_LONG = {
    "momentum_12_1": 0.01,
    "rate_of_change": 0.01,
    "atr": 1.0,
    "bollinger_band_width": 0.01,
    "rsi_zscore": -0.9,
    "price_to_ma": -0.05,
}
LOOSE_POLICY = RiskPolicy(
    max_single_order_notional=5000.0,
    max_total_exposure=15000.0,
    max_margin_fraction=1.0,
    min_confidence=0.0,
)


def _kline(close: float = 100.0, open_time: int | None = None) -> StorageKline:
    ot = open_time or int(time.time() * 1000)
    return StorageKline(
        symbol="BTCUSDT",
        interval="30m",
        open_time=ot,
        open=close * 0.995,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=1000.0,
        close_time=ot + 1800000 - 1,
        quote_volume=0.0,
        trades=0,
        taker_buy_base=0.0,
        taker_buy_quote=0.0,
        is_final=True,
    )


def _macro_state_with_detail(detail: str, latency_ms=None):
    s = MagicMock()
    s.market_regime = "BULL"
    s.trend_strength = "STRONG"
    s.regime_detail = detail
    s.timestamp = int(time.time() * 1000)
    if latency_ms is not None:
        s.llm_latency_ms = latency_ms
    return s


def _macro_storage(detail: str, latency_ms=None):
    storage = MagicMock()
    storage.get_latest_state = AsyncMock(return_value=_macro_state_with_detail(detail, latency_ms))
    return storage


def _audit():
    a = MagicMock()
    a.record_risk_check = AsyncMock()
    a.record_order = AsyncMock()
    return a


def _make_loop(detail: str, factors=None, latency_ms=None, config=None):
    storage = MagicMock()
    storage.store_kline = AsyncMock()
    storage.query_klines = AsyncMock(return_value=[])
    macro_storage = _macro_storage(detail, latency_ms)
    executor = PaperOrderExecutor(initial_balance=10000.0, enable_exit_ladder=False)
    loop = RuleEngineLoop(
        symbol="BTCUSDT",
        interval="30m",
        storage=storage,
        executor=executor,
        macro_storage=macro_storage,
        config=config or RuleEngineConfig(entry_threshold=0.3),
        audit_storage=_audit(),
    )
    loop._risk_gate = loop._risk_gate  # keep default aligned
    # loosen risk gate for open tests
    from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate
    loop._risk_gate = PreTradeRiskGate(executor, LOOSE_POLICY)
    if factors is not None:
        loop._recent_factors = AsyncMock(return_value=factors)
    return loop, executor


class TestLoopPicksMrExitWhenChoppy:
    @pytest.mark.asyncio
    async def test_loop_picks_mr_exit_params_when_choppy(self):
        cfg = RuleEngineConfig(entry_threshold=0.3, mr_sl_atr=2.5, mr_tp_atr=1.8, mr_trailing=0.0)
        loop, _ = _make_loop("CHOPPY", factors=FACTORS_MR_LONG, config=cfg)
        # ensure bb_history allows MR path — loop will build history itself
        await loop.on_bar(_kline(100.0))
        assert loop._ladder.config.r_atr_multiple == pytest.approx(cfg.mr_sl_atr)
        assert loop._ladder.config.tp1_close_ratio == pytest.approx(0.5)
        assert loop._ladder.config.tp2_close_ratio == pytest.approx(0.3)
        assert loop._ladder.config.trailing_atr_multiple == pytest.approx(cfg.mr_trailing)
        # trending should stay normal
        loop2, _ = _make_loop("TRENDING", factors=FACTORS_LONG_MOM, config=cfg)
        await loop2.on_bar(_kline(100.0))
        assert loop2._ladder.config.r_atr_multiple == pytest.approx(cfg.sl_atr_mult)
        assert loop2._ladder.config.tp1_close_ratio == pytest.approx(0.30)


class TestDiscreteDeRiskOnly:
    @pytest.mark.asyncio
    async def test_loop_discrete_de_risk_only(self):
        cfg = RuleEngineConfig(entry_threshold=0.3)
        # threshold scaling via mock generate_signal
        for detail, expected_thr in [("CHOPPY", 0.3 * 1.4), ("TRENDING", 0.3 * 1.0), ("UNCERTAIN", 0.3 * 1.2)]:
            loop, _ = _make_loop(detail, factors=FACTORS_LONG_MOM, config=cfg)
            with patch("vibe_trading.rule_engine.loop.generate_signal") as mock_sig:
                mock_sig.return_value = MagicMock(direction="FLAT", composite=0.0, strength=0.0, reason="mock", fake_breakout_warning=False)
                await loop.on_bar(_kline(100.0))
                assert mock_sig.called
                called_thr = mock_sig.call_args.kwargs.get("threshold", mock_sig.call_args.args[1] if len(mock_sig.call_args.args) > 1 else None)
                assert called_thr == pytest.approx(expected_thr), f"detail {detail} thr {called_thr} != {expected_thr}"
                # verify mr_enabled flag
                called_kwargs = mock_sig.call_args.kwargs
                assert called_kwargs.get("mr_enabled") is (detail == "CHOPPY")
                assert "bb_history" in called_kwargs

        # qty scaling: CHOPPY 0.3x vs TRENDING 1.0x
        cfg2 = RuleEngineConfig(entry_threshold=0.0)  # ensure open
        loop_chop, _ = _make_loop("CHOPPY", factors=FACTORS_MR_LONG, config=cfg2)
        # Need bb_history to trigger CHOPPY mode inside signal but loop sets mr_enabled True,
        # so FACTORS_MR_LONG will produce LONG via MR path regardless of bb_history.
        # To avoid bb_history side effects, pre-seed loop history empty — mr_enabled alone drives MR.
        d_chop = await loop_chop.on_bar(_kline(100.0))
        loop_trend, _ = _make_loop("TRENDING", factors=FACTORS_LONG_MOM, config=cfg2)
        d_trend = await loop_trend.on_bar(_kline(100.0))
        assert d_chop.action == "open"
        assert d_trend.action == "open"
        assert d_chop.qty == pytest.approx(d_trend.qty * 0.3, rel=0.05)
        assert d_chop.qty <= d_trend.qty
        # UNCERTAIN 0.5x
        loop_unc, _ = _make_loop("UNCERTAIN", factors=FACTORS_LONG_MOM, config=cfg2)
        d_unc = await loop_unc.on_bar(_kline(100.0))
        assert d_unc.qty == pytest.approx(d_trend.qty * 0.5, rel=0.05)


class TestLlmLatencyWarning:
    @pytest.mark.asyncio
    async def test_llm_latency_warning_logged(self, caplog):
        import logging
        cfg = RuleEngineConfig(entry_threshold=0.3)
        loop, _ = _make_loop("TRENDING", factors=FACTORS_LONG_MOM, config=cfg, latency_ms=9000)
        # need to ensure macro_state with latency is returned for warning check
        # _make_loop already injects latency via macro_storage mock
        with caplog.at_level(logging.WARNING):
            await loop.on_bar(_kline(100.0))
        assert any("llm_latency_ms" in rec.message and "8000" in rec.message for rec in caplog.records), f"records: {[r.message for r in caplog.records]}"

        # no warning when latency low
        caplog.clear()
        loop2, _ = _make_loop("TRENDING", factors=FACTORS_LONG_MOM, config=cfg, latency_ms=1000)
        with caplog.at_level(logging.WARNING):
            await loop2.on_bar(_kline(100.0))
        assert not any("llm_latency_ms" in rec.message for rec in caplog.records)
