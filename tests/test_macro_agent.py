"""Tests for MacroAnalysisAgent parse + create state (Wave D — coverage 85% plan)."""
import pytest



from vibe_trading.agents.macro_agent import MacroAnalysisAgent


def _agent() -> MacroAnalysisAgent:
    return MacroAnalysisAgent(config=None)


class TestParseAnalysis:
    def test_full_parse(self):
        a = _agent()
        response = """TREND ANALYSIS:
Direction: UPTREND
Strength: STRONG
Market Regime: BULL

SENTIMENT ANALYSIS:
Overall: POSITIVE
Score: 65.0

MAJOR EVENTS:
- 加息預期降溫

RECOMMENDATION:
Stance: BULLISH
Rationale: 宏觀轉好

CONFIDENCE: 0.85
"""
        result = a._parse_analysis(response)
        assert result["trend_direction"] == "UPTREND"
        assert result["trend_strength"] == "STRONG"
        assert result["market_regime"] == "BULL"
        assert result["overall_sentiment"] == "POSITIVE"
        assert result["sentiment_score"] == 65.0
        assert result["confidence"] == 0.85
        assert result["recommendation"]["stance"] == "BULLISH"

    def test_empty_returns_defaults(self):
        a = _agent()
        result = a._parse_analysis("")
        assert result["trend_direction"] == "SIDEWAYS"
        assert result["confidence"] == 0.5

    def test_invalid_score_ignored(self):
        a = _agent()
        result = a._parse_analysis("Score: not-a-number")
        assert result["sentiment_score"] == 0.0

    def test_events_none(self):
        a = _agent()
        result = a._parse_analysis("MAJOR EVENTS:\nNone")
        assert result["major_events"] == []

    def test_events_parsed(self):
        a = _agent()
        result = a._parse_analysis("MAJOR EVENTS:\n- 事件一\n- 事件二")
        assert result["major_events"] == []


class TestCreateMacroState:
    @pytest.mark.asyncio
    async def test_creates_state(self):
        a = _agent()
        analysis = {
            "trend_direction": "UPTREND",
            "trend_strength": "STRONG",
            "market_regime": "BULL",
            "overall_sentiment": "POSITIVE",
            "sentiment_score": 60.0,
            "major_events": [{"event": "x"}],
            "recommendation": {"stance": "BULLISH"},
            "confidence": 0.8,
        }
        state = await a.create_macro_state("BTCUSDT", analysis, analysis_duration=2.5)
        assert state.symbol == "BTCUSDT"
        assert state.trend_direction == "UPTREND"
        assert state.market_regime == "BULL"
        assert state.confidence == 0.8
        assert state.analysis_duration == 2.5

    @pytest.mark.asyncio
    async def test_defaults(self):
        a = _agent()
        state = await a.create_macro_state("BTCUSDT", {})
        assert state.trend_direction == "SIDEWAYS"
        assert state.confidence == 0.5
