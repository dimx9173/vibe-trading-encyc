"""Tests for SimplifiedTradingCoordinator (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.coordinator.simplified_coordinator import SimplifiedTradingCoordinator


@pytest.fixture
def coord():
    return SimplifiedTradingCoordinator(symbol="BTCUSDT", interval="30m")


class TestInit:
    def test_defaults(self, coord):
        assert coord.symbol == "BTCUSDT"
        assert coord._technical_analyst is None
        assert coord._portfolio_manager is None

    def test_macro_storage_default(self, coord):
        assert coord.macro_storage is not None


class TestPrepareContext:
    @pytest.mark.asyncio
    async def test_prepare_context(self, coord):
        ctx = await coord._prepare_context(50000.0)
        assert ctx.symbol == "BTCUSDT"
        assert ctx.current_price == 50000.0
        assert ctx.market_data == {"price": 50000.0}


class TestTechnicalAnalysis:
    @pytest.mark.asyncio
    async def test_no_analyst_returns_empty(self, coord):
        assert await coord._run_technical_analysis(MagicMock()) == {}

    @pytest.mark.asyncio
    async def test_with_analyst(self, coord):
        analyst = MagicMock()
        analyst.analyze = AsyncMock(return_value="bullish")
        coord._technical_analyst = analyst
        ctx = MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                        klines=[], indicators={}, market_data={})
        result = await coord._run_technical_analysis(ctx)
        assert result == {"technical": "bullish"}

    @pytest.mark.asyncio
    async def test_analyst_error_failsafe(self, coord):
        analyst = MagicMock()
        analyst.analyze = AsyncMock(side_effect=RuntimeError("boom"))
        coord._technical_analyst = analyst
        ctx = MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                        klines=[], indicators={}, market_data={})
        result = await coord._run_technical_analysis(ctx)
        assert "Error" in result["technical"]


class TestMacroState:
    @pytest.mark.asyncio
    async def test_load_macro_state(self, coord):
        ms = MagicMock()
        ms.get_latest_state = AsyncMock(return_value=MagicMock(
            market_regime="BULL", trend_direction="UPTREND", overall_sentiment="POSITIVE"))
        coord.macro_storage = ms
        state = await coord._load_macro_state()
        assert state is not None

    @pytest.mark.asyncio
    async def test_load_macro_state_none(self, coord):
        ms = MagicMock()
        ms.get_latest_state = AsyncMock(return_value=None)
        coord.macro_storage = ms
        assert await coord._load_macro_state() is None

    @pytest.mark.asyncio
    async def test_load_macro_state_error(self, coord):
        ms = MagicMock()
        ms.get_latest_state = AsyncMock(side_effect=RuntimeError("down"))
        coord.macro_storage = ms
        assert await coord._load_macro_state() is None


class TestResearchDebate:
    @pytest.mark.asyncio
    async def test_no_researchers(self, coord):
        assert await coord._run_research_debate(MagicMock(), {}, None) == {}

    @pytest.mark.asyncio
    async def test_with_researchers(self, coord):
        coord._bull_researcher = MagicMock()
        coord._bear_researcher = MagicMock()
        with pytest.importorskip("unittest.mock").patch(
            "vibe_trading.coordinator.simplified_coordinator.run_debate_round",
            new=AsyncMock(return_value=("bull_arg", "bear_arg")),
        ):
            ctx = MagicMock(symbol="BTCUSDT", current_price=1.0)
            result = await coord._run_research_debate(ctx, {"technical": "t"}, None)
        assert result["debate"]["bull_response"] == "bull_arg"


class TestRiskCheck:
    def test_no_macro_low_risk(self, coord):
        r = coord._perform_risk_check(10000.0, [], None)
        assert r["risk_level"] == "LOW"

    def test_bear_macro_high_risk(self, coord):
        macro = MagicMock(market_regime="BEAR")
        r = coord._perform_risk_check(10000.0, [], macro)
        assert r["risk_level"] == "HIGH"
        assert r["position_size_pct"] == 0.2

    def test_bull_macro_low_risk(self, coord):
        macro = MagicMock(market_regime="BULL")
        r = coord._perform_risk_check(10000.0, [], macro)
        assert r["risk_level"] == "LOW"

    def test_high_exposure_risk(self, coord):
        r = coord._perform_risk_check(
            10000.0, [{"position_amount": 9000.0}], None)
        assert r["risk_level"] == "HIGH"
        assert r["position_size_pct"] == 0.1


class TestFinalDecision:
    @pytest.mark.asyncio
    async def test_no_pm_hold(self, coord):
        result = await coord._make_final_decision({}, {}, None, 10000.0, [])
        assert result["decision"] == "HOLD"

    @pytest.mark.asyncio
    async def test_pm_scorecard(self, coord):
        pm = MagicMock()
        scorecard = MagicMock()
        scorecard.recommended_action = "BUY"
        scorecard.confidence = 0.8
        scorecard.rationale = "看漲"
        pm.make_final_decision = AsyncMock(return_value={
            "scorecard": scorecard, "decision_text": "Decision: BUY",
        })
        coord._portfolio_manager = pm
        result = await coord._make_final_decision(
            {"technical": "t"}, {"debate": {}}, None, 10000.0, [])
        assert result["decision"] == "BUY"
        assert result["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_pm_error_failsafe(self, coord):
        pm = MagicMock()
        pm.make_final_decision = AsyncMock(side_effect=RuntimeError("boom"))
        coord._portfolio_manager = pm
        result = await coord._make_final_decision({}, {}, None, 10000.0, [])
        assert result["decision"] == "HOLD"


class TestDecisionFlow:
    @pytest.mark.asyncio
    async def test_full_flow_no_agents(self, coord):
        decision = await coord.simplified_decision_flow(current_price=50000.0)
        assert decision.symbol == "BTCUSDT"
        assert decision.decision in ("HOLD", "BUY", "SELL")
