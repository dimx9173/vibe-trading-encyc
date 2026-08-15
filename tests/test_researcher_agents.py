"""Tests for researcher agents (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.agents.researchers.debate_analyzer import (
    Argument,
    ArgumentCategory,
    ArgumentStrength,
)
from vibe_trading.agents.researchers.researcher_agents import (
    BearResearcherAgent,
    BullResearcherAgent,
    ResearchManagerAgent,
    ResearcherAgent,
    run_debate_round,
    run_research_phase,
)


def _researcher() -> ResearcherAgent:
    r = ResearcherAgent.__new__(ResearcherAgent)
    r._tool_context = MagicMock()
    r._tool_context.symbol = "BTCUSDT"
    r.config = MagicMock()
    r.config.role.value = "bull_researcher"
    r._my_arguments = []
    return r


class TestBuildDebatePrompt:
    def test_prompt_with_context(self):
        r = _researcher()
        prompt = r._build_debate_prompt("市場背景", None, None)
        assert "BTCUSDT" in prompt
        assert "市場背景" in prompt

    def test_prompt_with_history(self):
        r = _researcher()
        prompt = r._build_debate_prompt("ctx", "history1", "opponent arg")
        assert "history1" in prompt
        assert "opponent arg" in prompt


class TestArguments:
    def test_empty_arguments(self):
        r = _researcher()
        assert r.get_my_arguments() == []
        summary = r.get_argument_summary()
        assert summary["total"] == 0

    def test_argument_summary(self):
        r = _researcher()
        r._my_arguments = [
            Argument(content="a", category=ArgumentCategory.TECHNICAL,
                     strength=ArgumentStrength.STRONG, confidence=0.8,
                     evidence_based=True, data_mentioned=[], key_points=[],
                     timestamp=__import__("datetime").datetime(2026, 1, 1)),
            Argument(content="b", category=ArgumentCategory.FUNDAMENTAL,
                     strength=ArgumentStrength.WEAK, confidence=0.3,
                     evidence_based=False, data_mentioned=[], key_points=[],
                     timestamp=__import__("datetime").datetime(2026, 1, 1)),
        ]
        summary = r.get_argument_summary()
        assert summary["total"] == 2
        assert summary["by_category"]["technical"] == 1
        assert summary["by_strength"]["strong"] == 1


class TestSubclasses:
    def test_bull_init(self):
        b = BullResearcherAgent(config=None)
        assert b.config is not None

    def test_bear_init(self):
        b = BearResearcherAgent(config=None)
        assert b.config is not None


class TestAnalysisSummary:
    def test_generate_summary(self):
        rm = ResearchManagerAgent(config=None)
        sc = MagicMock()
        sc.dominant_view = "bullish"
        sc.bull_score = 70.0
        sc.bear_score = 30.0
        sc.consensus_level = "high"
        sc.bull_arguments = [1, 2]
        sc.bear_arguments = [1]
        sc.bull_strength_count = {"strong": 1, "very_strong": 1}
        sc.bear_strength_count = {"strong": 0, "very_strong": 0}
        rec = MagicMock()
        rec.action = "BUY"
        rec.confidence = 0.8
        rec.overall_score = 60
        rec.technical_score = 70
        rec.fundamental_score = 50
        rec.sentiment_score = 60
        summary = rm._generate_analysis_summary(sc, rec)
        assert summary["dominant_view"] == "bullish"
        assert summary["view_strength"] == 40.0
        assert summary["total_arguments"] == 3
        assert summary["strong_arguments"] == 2


class TestDebateRound:
    @pytest.mark.asyncio
    async def test_run_debate_round(self):
        bull = MagicMock()
        bull.respond = AsyncMock(return_value="Bull 看漲")
        bear = MagicMock()
        bear.respond = AsyncMock(return_value="Bear 看跌")
        bull_resp, bear_resp = await run_debate_round(
            bull, bear, "context", "bull_hist", "bear_hist")
        assert bull_resp == "Bull 看漲"
        assert bear_resp == "Bear 看跌"
        # Bear 收到 Bull 的最後一句
        bear.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_debate_round_empty_history(self):
        bull = MagicMock()
        bull.respond = AsyncMock(return_value="B1")
        bear = MagicMock()
        bear.respond = AsyncMock(return_value="R1")
        bull_resp, bear_resp = await run_debate_round(bull, bear, "ctx", "", "")
        assert bull_resp == "B1"


class TestResearchPhase:
    @pytest.mark.asyncio
    async def test_run_research_phase(self):
        bull = MagicMock()
        bull.respond = AsyncMock(return_value="Bull 觀點")
        bear = MagicMock()
        bear.respond = AsyncMock(return_value="Bear 觀點")
        rm = MagicMock()
        rm.make_decision = AsyncMock(return_value={"recommendation": "BUY"})
        result = await run_research_phase(
            bull, bear, rm, "ctx", {}, rounds=1)
        assert result["recommendation"] == "BUY"
        # 歷史已傳遞
        rm.make_decision.assert_called_once()
        kwargs = rm.make_decision.call_args.kwargs
        assert "Round 1" in kwargs["bull_history"]
