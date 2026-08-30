import pytest

from vibe_trading.agents.macro_agent import MacroAnalysisAgent


def _agent() -> MacroAnalysisAgent:
    return MacroAnalysisAgent(config=None)


class TestMacroPromptDiscrete:
    def test_prompt_contains_regime_detail(self):
        a = _agent()
        prompt = a._build_analysis_prompt({})
        assert "REGIME_DETAIL" in prompt
        assert "CHOPPY" in prompt
        assert "TRENDING" in prompt
        assert "UNCERTAIN" in prompt

    def test_prompt_contains_choppy_constraint(self):
        a = _agent()
        prompt = a._build_analysis_prompt({})
        assert "CHOPPY" in prompt
        assert "qty" in prompt.lower() or "threshold" in prompt.lower()

    def test_system_prompt_contains_regime_detail(self):
        a = _agent()
        assert "REGIME_DETAIL" in a._system_prompt


class TestParseDiscreteDetail:
    def test_parse_choppy(self):
        a = _agent()
        result = a._parse_analysis("REGIME: NEUTRAL\nREGIME_DETAIL: CHOPPY\nCONFIDENCE: 0.6")
        assert result["regime_detail"] == "CHOPPY"

    def test_parse_trending_case_insensitive(self):
        a = _agent()
        result = a._parse_analysis("REGIME: RISK_ON\nREGIME_DETAIL: trending\nCONFIDENCE: 0.7")
        assert result["regime_detail"] == "TRENDING"

    def test_parse_uncertain_fallback(self):
        a = _agent()
        result = a._parse_analysis("REGIME: NEUTRAL\nREGIME_DETAIL: FLUFFY\nCONFIDENCE: 0.5")
        assert result["regime_detail"] == "UNCERTAIN"

    def test_parse_missing_detail_fallback(self):
        a = _agent()
        result = a._parse_analysis("REGIME: NEUTRAL\nCONFIDENCE: 0.5")
        assert result["regime_detail"] == "UNCERTAIN"

    def test_parse_lowercase_choppy(self):
        a = _agent()
        result = a._parse_analysis("REGIME_DETAIL: choppy")
        assert result["regime_detail"] == "CHOPPY"

    def test_primary_regime_and_detail_both_parsed(self):
        a = _agent()
        result = a._parse_analysis("REGIME: RISK_ON\nREGIME_DETAIL: CHOPPY\nCONFIDENCE: 0.9")
        assert result["market_regime"] == "RISK_ON"
        assert result["regime_detail"] == "CHOPPY"

    def test_parse_detail_does_not_override_regime(self):
        a = _agent()
        result = a._parse_analysis("REGIME: RISK_OFF\nREGIME_DETAIL: TRENDING")
        assert result["market_regime"] == "RISK_OFF"
        assert result["regime_detail"] == "TRENDING"

    def test_empty_fallback_uncertain(self):
        a = _agent()
        result = a._parse_analysis("")
        assert result["regime_detail"] == "UNCERTAIN"


class TestCreateMacroStateDiscrete:
    @pytest.mark.asyncio
    async def test_create_state_has_regime_detail(self):
        a = _agent()
        analysis = {"market_regime": "NEUTRAL", "regime_detail": "CHOPPY", "confidence": 0.6}
        state = await a.create_macro_state("BTCUSDT", analysis)
        assert state.regime_detail == "CHOPPY"

    @pytest.mark.asyncio
    async def test_create_state_default_uncertain(self):
        a = _agent()
        state = await a.create_macro_state("BTCUSDT", {})
        assert state.regime_detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_create_state_case_insensitive_clamped(self):
        a = _agent()
        analysis = {"regime_detail": "trending"}
        state = await a.create_macro_state("BTCUSDT", analysis)
        assert state.regime_detail == "TRENDING"

    @pytest.mark.asyncio
    async def test_create_state_unknown_clamped(self):
        a = _agent()
        analysis = {"regime_detail": "FLUFFY"}
        state = await a.create_macro_state("BTCUSDT", analysis)
        assert state.regime_detail == "UNCERTAIN"

    @pytest.mark.asyncio
    async def test_create_state_preserves_regime_detail_when_present(self):
        a = _agent()
        analysis = {"regime_detail": "CHOPPY", "market_regime": "RISK_ON"}
        state = await a.create_macro_state("BTCUSDT", analysis)
        assert state.market_regime == "RISK_ON"
        assert state.regime_detail == "CHOPPY"
