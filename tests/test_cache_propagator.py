"""Tests for DataCache + StatePropagator (Wave D — coverage 85% plan)."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.coordinator.state_propagator import (
    AgentMessage,
    AgentReport,
    StatePropagator,
)
from vibe_trading.data_sources.data_cache import CachedAPIClient, DataCache


class TestDataCache:
    @pytest.mark.asyncio
    async def test_set_get(self):
        c = DataCache()
        await c.set("k", "v")
        assert await c.get("k") == "v"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        c = DataCache()
        assert await c.get("nope") is None

    @pytest.mark.asyncio
    async def test_get_expired(self):
        c = DataCache()
        await c.set("k", "v", ttl=-1)
        assert await c.get("k") is None

    @pytest.mark.asyncio
    async def test_delete(self):
        c = DataCache()
        await c.set("k", "v")
        await c.delete("k")
        assert await c.get("k") is None

    @pytest.mark.asyncio
    async def test_clear(self):
        c = DataCache()
        await c.set("a", 1)
        await c.clear()
        assert await c.get("a") is None

    @pytest.mark.asyncio
    async def test_stats(self):
        c = DataCache()
        await c.set("a", 1)
        await c.set("b", 2, ttl=-1)  # 立即過期
        stats = c.get_stats()
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["expired"] == 1


class TestCachedAPIClient:
    @pytest.mark.asyncio
    async def test_fetch_caches(self):
        client = CachedAPIClient(cache=DataCache())
        calls = []

        async def fetch_fn():
            calls.append("called")
            return {"data": "fresh"}

        r1 = await client.fetch_with_fallback(fetch_fn, "k")
        r2 = await client.fetch_with_fallback(fetch_fn, "k")
        assert r1 == {"data": "fresh"}
        assert r2 == {"data": "fresh"}
        assert len(calls) == 2  # cache 是 error-fallback 用, 非 hit 加速

    @pytest.mark.asyncio
    async def test_error_uses_cache(self):
        client = CachedAPIClient(cache=DataCache())
        await client.cache.set("k", "stale-data")

        async def fetch_fn():
            raise RuntimeError("down")

        result = await client.fetch_with_fallback(fetch_fn, "k")
        assert result == "stale-data"
        assert client.get_fallback_count() == 1

    @pytest.mark.asyncio
    async def test_fetch_error_fallback(self):
        client = CachedAPIClient(cache=DataCache())
        async def fetch_fn():
            raise RuntimeError("down")
        with pytest.raises(RuntimeError):
            await client.fetch_with_fallback(fetch_fn, "k")

    @pytest.mark.asyncio
    async def test_fallback_count(self):
        client = CachedAPIClient(cache=DataCache())
        async def fetch_fn():
            raise RuntimeError("down")
        with pytest.raises(RuntimeError):
            await client.fetch_with_fallback(fetch_fn, "k")
        assert client.get_fallback_count() == 0
        client.reset_fallback_count()
        assert client.get_fallback_count() == 0


class TestStateModels:
    def test_agent_message_to_dict(self):
        m = AgentMessage(
            agent_name="tech", agent_role="analyst", content="看漲",
            timestamp=datetime(2026, 1, 1), correlation_id="cid",
        )
        d = m.to_dict()
        assert d["agent_name"] == "tech"
        assert d["correlation_id"] == "cid"

    def test_agent_report_to_dict(self):
        r = AgentReport(
            agent_name="fund", agent_role="analyst", report_type="fundamentals",
            content="基本面佳", key_findings=["好"], confidence=0.8,
        )
        d = r.to_dict()
        assert d["report_type"] == "fundamentals"
        assert d["confidence"] == 0.8


class TestStatePropagator:
    def test_create_initial_state(self):
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m", {"price": 50000},
                                     {"regime": "BULL"})
        assert ctx.symbol == "BTCUSDT"
        assert ctx.market_data == {"price": 50000}
        assert ctx.debate_state is not None
        assert p._current_context is ctx

    def test_add_analyst_report(self):
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        report = AgentReport(
            agent_name="tech", agent_role="analyst", report_type="market",
            content="看漲", key_findings=["RSI"], confidence=0.8,
        )
        p.add_analyst_report(ctx, report)
        assert ctx.analyst_reports["tech"] is report
        assert len(ctx.messages) == 1
        assert ctx.messages[0].agent_name == "tech"

    def test_add_agent_report_updates_context(self):
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        report = AgentReport(
            agent_name="sent", agent_role="analyst", report_type="sentiment",
            content="中性", key_findings=[], confidence=0.5,
        )
        p.add_analyst_report(ctx, report)
        assert ctx.analyst_reports["sent"] is report


class TestStatePropagatorUpdate:
    def test_update_debate_bull(self):
        from vibe_trading.coordinator.state_propagator import DebatePhase
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        p.update_debate_state(ctx, "bull", "看漲論點", round_number=1)
        assert ctx.debate_state.bull_history == ["看漲論點"]
        assert ctx.debate_state.current_phase == DebatePhase.BEAR_TURN
        assert len(ctx.messages) == 1

    def test_update_debate_bear(self):
        from vibe_trading.coordinator.state_propagator import DebatePhase
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        p.update_debate_state(ctx, "bear", "看跌論點", round_number=1)
        assert ctx.debate_state.current_phase == DebatePhase.BULL_TURN

    def test_set_judgment(self):
        from vibe_trading.coordinator.state_propagator import DebatePhase
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        p.set_judgment(ctx, "BUY", 0.8, "看漲")
        assert ctx.debate_state.judge_decision == "BUY"
        assert ctx.debate_state.confidence == 0.8
        assert ctx.debate_state.current_phase == DebatePhase.COMPLETED

    def test_update_risk_debate(self):
        from vibe_trading.coordinator.state_propagator import RiskDebatePhase
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        p.update_risk_debate(ctx, "aggressive", "高風險", {"risk_level": "high"})
        assert ctx.risk_debate_state.aggressive_history == ["高風險"]
        assert ctx.risk_debate_state.current_phase == RiskDebatePhase.CONSERVATIVE
        assert ctx.risk_debate_state.risk_parameters["risk_level"] == "high"

    def test_update_risk_debate_conservative(self):
        from vibe_trading.coordinator.state_propagator import RiskDebatePhase
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        p.update_risk_debate(ctx, "conservative", "保守", {})
        assert ctx.risk_debate_state.current_phase == RiskDebatePhase.NEUTRAL

    def test_update_risk_debate_neutral(self):
        from vibe_trading.coordinator.state_propagator import RiskDebatePhase
        p = StatePropagator()
        ctx = p.create_initial_state("BTCUSDT", "30m")
        p.update_risk_debate(ctx, "neutral", "中性", {})
        assert ctx.risk_debate_state.current_phase == RiskDebatePhase.CONSENSUS
