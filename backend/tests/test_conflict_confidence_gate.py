"""TDD Red tests for F1 (conflict detection) + F2 (confidence gate).

F1: decision_aggregator._make_decision currently picks max-score side even when
    bullish and bearish scores are both high and close (signal conflict).
    Expected: force HOLD + metadata["conflict"]=True when
    bullish>0.3 AND bearish>0.3 AND abs(bullish-bearish)<0.15.

F2: PreTradeRiskGate.validate_order has no confidence parameter — any decision
    confidence (including 0.55) passes through to execution.
    Expected: optional keyword-only `confidence` param; when provided and below
    policy.min_confidence (default 0.6, env RISK_MIN_CONFIDENCE) -> REJECTED.
"""
import os

import pytest

from vibe_trading.prime.decision_aggregator import DecisionAggregator
from vibe_trading.prime.models import TradingAction
from vibe_trading.execution.pre_trade_risk import (
    PreTradeRiskGate,
    RiskPolicy,
    RiskVerdict,
)
from vibe_trading.data_sources.binance_client import (
    OrderSide,
    OrderType,
    PositionSide,
)


# ---------------------------------------------------------------------------
# F1: conflict detection in DecisionAggregator._make_decision
# ---------------------------------------------------------------------------

class TestConflictDetection:
    def test_close_bullish_bearish_scores_force_hold(self):
        """bullish=0.42 vs bearish=0.38 (both >0.3, diff 0.04<0.15) -> HOLD."""
        agg = DecisionAggregator(min_signals=1)
        scores = {"bullish": 0.42, "bearish": 0.38, "neutral": 0.1, "hold": 0.1}

        decision = agg._make_decision(scores)

        assert decision.action == TradingAction.HOLD, (
            f"conflicting signals should force HOLD, got {decision.action}"
        )
        assert decision.metadata.get("conflict") is True

    def test_large_gap_does_not_trigger_conflict(self):
        """bullish=0.60 vs bearish=0.35 (diff 0.25>0.15) -> BUY unchanged."""
        agg = DecisionAggregator(min_signals=1)
        scores = {"bullish": 0.60, "bearish": 0.35, "neutral": 0.03, "hold": 0.02}

        decision = agg._make_decision(scores)

        assert decision.action == TradingAction.BUY
        assert decision.metadata.get("conflict") is not True

    def test_conflict_flagged_even_below_action_threshold(self):
        """bullish=0.32 vs bearish=0.31: both <0.4 (HOLD anyway) but conflict
        flag should still be set so operators see the disagreement."""
        agg = DecisionAggregator(min_signals=1)
        scores = {"bullish": 0.32, "bearish": 0.31, "neutral": 0.2, "hold": 0.17}

        decision = agg._make_decision(scores)

        assert decision.action == TradingAction.HOLD
        assert decision.metadata.get("conflict") is True


# ---------------------------------------------------------------------------
# F2: confidence gate in PreTradeRiskGate.validate_order
# ---------------------------------------------------------------------------

class _FakeExecutor:
    """Minimal executor double: no positions, 10k USDT available."""

    async def get_positions(self):
        return []

    async def get_balance(self):
        return {"USDT": {"available": 10000.0, "balance": 10000.0}}


class TestConfidenceGate:
    def test_policy_has_min_confidence_default(self):
        policy = RiskPolicy()
        assert policy.min_confidence == pytest.approx(0.6)

    def test_policy_min_confidence_from_env(self, monkeypatch):
        monkeypatch.setenv("RISK_MIN_CONFIDENCE", "0.7")
        # reset settings singleton so from_env re-reads
        import vibe_trading.config.settings as settings_mod

        monkeypatch.setattr(settings_mod, "_settings", None)
        try:
            policy = RiskPolicy.from_settings()
            assert policy.min_confidence == pytest.approx(0.7)
        finally:
            monkeypatch.setattr(settings_mod, "_settings", None)

    @pytest.mark.asyncio
    async def test_low_confidence_order_rejected(self):
        gate = PreTradeRiskGate(_FakeExecutor(), RiskPolicy())
        result = await gate.validate_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
            position_side=PositionSide.LONG,
            price=65000.0,
            confidence=0.55,
        )
        assert result.verdict == RiskVerdict.REJECTED
        assert "confidence" in result.reason.lower()
        assert result.checks.get("confidence") == 0.55

    @pytest.mark.asyncio
    async def test_high_confidence_order_approved(self):
        gate = PreTradeRiskGate(_FakeExecutor(), RiskPolicy())
        result = await gate.validate_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
            position_side=PositionSide.LONG,
            price=65000.0,
            confidence=0.75,
        )
        assert result.verdict == RiskVerdict.APPROVED

    @pytest.mark.asyncio
    async def test_no_confidence_param_backward_compatible(self):
        """Existing callers that don't pass confidence must be unaffected."""
        gate = PreTradeRiskGate(_FakeExecutor(), RiskPolicy())
        result = await gate.validate_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
            position_side=PositionSide.LONG,
            price=65000.0,
        )
        assert result.verdict == RiskVerdict.APPROVED
