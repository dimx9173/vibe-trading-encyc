"""Tests for memory reflection module — Wave D107."""
from unittest.mock import MagicMock

import pytest

from vibe_trading.memory.reflection import (
    ReflectionOutcome,
    TradeReflector,
    TradeResult,
    compute_alpha,
    compute_return_pct,
    evaluate_decision_outcome,
    reflect_on_matured_snapshot,
)


class TestComputeAlpha:
    def test_basic(self):
        assert compute_alpha(5.0, 2.0) == 3.0

    def test_none_inputs(self):
        assert compute_alpha(None, 2.0) is None
        assert compute_alpha(5.0, None) is None


class TestComputeReturnPct:
    def test_basic(self):
        assert compute_return_pct(100.0, 110.0) == 10.0

    def test_invalid(self):
        assert compute_return_pct(None, 110.0) is None
        assert compute_return_pct(0.0, 110.0) is None
        assert compute_return_pct(100.0, None) is None


class TestEvaluateDecisionOutcome:
    def test_buy(self):
        pnl, alpha = evaluate_decision_outcome("BUY", 100.0, 110.0, 2.0)
        assert pnl == 10.0
        assert alpha == 8.0

    def test_sell(self):
        pnl, alpha = evaluate_decision_outcome("SELL", 100.0, 90.0, 2.0)
        assert pnl == 10.0  # 做空盈利
        assert alpha == 8.0

    def test_hold(self):
        pnl, alpha = evaluate_decision_outcome("HOLD", 100.0, 110.0, 5.0)
        assert pnl == 0.0
        assert alpha == -5.0  # 機會成本

    def test_none_prices(self):
        assert evaluate_decision_outcome("BUY", None, 110.0) == (None, None)

    def test_unknown_decision(self):
        pnl, _ = evaluate_decision_outcome("WEIRD", 100.0, 110.0)
        assert pnl == 0.0


def _tr(pnl_pct=1.0, alpha=None):
    return TradeResult(
            symbol="BTCUSDT", decision="BUY", entry_price=100.0,
            exit_price=110.0, position_size=1.0, pnl=10.0,
            pnl_percentage=pnl_pct, hold_duration_hours=1.0,
            market_condition="trending", alpha=alpha)

class TestEvaluateOutcome:
    def test_correct(self):
        r = TradeReflector(memory=MagicMock())
        assert r._evaluate_outcome(_tr(pnl_pct=5.0)) == ReflectionOutcome.CORRECT

    def test_incorrect(self):
        r = TradeReflector(memory=MagicMock())
        assert r._evaluate_outcome(_tr(pnl_pct=-5.0)) == ReflectionOutcome.INCORRECT

    def test_partial(self):
        r = TradeReflector(memory=MagicMock())
        assert r._evaluate_outcome(_tr(pnl_pct=0.1)) == ReflectionOutcome.PARTIAL

    def test_uncertain(self):
        r = TradeReflector(memory=MagicMock())
        assert r._evaluate_outcome(_tr(pnl_pct=1.0)) == ReflectionOutcome.UNCERTAIN

    def test_alpha_priority(self):
        # alpha 存在 → 用 alpha 判斷
        r = TradeReflector(memory=MagicMock())
        assert r._evaluate_outcome(_tr(pnl_pct=-5.0, alpha=5.0)) == ReflectionOutcome.CORRECT


class TestReflectRules:
    def _reflector(self):
        return TradeReflector(memory=MagicMock())

    @pytest.mark.asyncio
    async def test_rule_generation(self):
        r = self._reflector()
        content = r._generate_reflection_with_rules(
            "technical", "buy signal", _tr(pnl_pct=5.0),
            ReflectionOutcome.CORRECT)
        assert "盈利交易" in content["key_factors"]
        assert "technical" in content["lessons"][0]

    @pytest.mark.asyncio
    async def test_rules_trending(self):
        r = self._reflector()
        tr = _tr(pnl_pct=-5.0)
        tr.market_condition = "ranging"
        content = r._generate_reflection_with_rules(
            "fundamental", "report", tr, ReflectionOutcome.INCORRECT)
        assert "亏损交易" in content["key_factors"]
        assert any("震荡市场" in l for l in content["lessons"])

    def test_parse_json(self):
        r = self._reflector()
        parsed = r._parse_reflection_content('{"key_factors": ["a"], "lessons": ["b"], "confidence": 0.8}')
        assert parsed["confidence"] == 0.8

    def test_parse_bad(self):
        r = self._reflector()
        parsed = r._parse_reflection_content("not json at all")
        assert parsed["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_reflect_on_trade_full(self):
        r = TradeReflector(memory=MagicMock(), llm_model=None)
        tr = _tr(pnl_pct=5.0)
        reflections = await r.reflect_on_trade(
            trade_result=tr,
            agent_reports={"technical": "buy signal"},
            decision_context={"decision_id": "D1"})
        assert len(reflections) == 2  # 1 agent + overall
        assert reflections[0].agent_name == "technical"
        assert reflections[1].agent_name == "Overall"

    @pytest.mark.asyncio
    async def test_reflect_overall_correct_agents(self):
        r = TradeReflector(memory=MagicMock())
        tr = _tr(pnl_pct=5.0)
        refl = await r._reflect_overall(
            tr, {"technical": "buy signal", "news": "sell signal"},
            ReflectionOutcome.CORRECT)
        assert "technical" in refl.key_factors[0]

    @pytest.mark.asyncio
    async def test_matured_snapshot(self):
        from types import SimpleNamespace
        r = TradeReflector(memory=MagicMock(), llm_model=None)
        snapshot = SimpleNamespace(
            decision="BUY", price_at_decision=100.0, symbol="BTCUSDT",
            decision_id="D1")
        refls = await reflect_on_matured_snapshot(r, snapshot, 110.0)
        assert len(refls) == 1  # 無 agent_reports → 只有 overall

    @pytest.mark.asyncio
    async def test_matured_snapshot_no_pnl(self):
        from types import SimpleNamespace
        r = TradeReflector(memory=MagicMock())
        snapshot = SimpleNamespace(
            decision="BUY", price_at_decision=None, symbol="BTCUSDT",
            decision_id="D1")
        assert await reflect_on_matured_snapshot(r, snapshot, 110.0) == []
