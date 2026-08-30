from vibe_trading.agents.macro_agent import MacroAnalysisAgent


def _agent() -> MacroAnalysisAgent:
    return MacroAnalysisAgent(config=None)


def _kline(t=1000, o=50000.0, h=50100.0, low=49900.0, c=50050.0, v=100.0):
    return {"t": t, "o": o, "h": h, "l": low, "c": c, "v": v}


class TestBuildPromptKlines:
    def test_with_klines_includes_block(self):
        a = _agent()
        klines = [_kline(t=1000 + i * 1800000, o=50000 + i) for i in range(5)]
        prompt = a._build_analysis_prompt(
            {"klines_24h": klines, "klines_24h_interval": "30m", "klines_24h_hours": 24}
        )
        assert "24h KLINES" in prompt
        assert "t=" in prompt
        assert "o=" in prompt
        assert "h=" in prompt
        assert "l=" in prompt
        assert "c=" in prompt
        assert "v=" in prompt
        # at least one formatted line
        assert "t=1000" in prompt

    def test_without_klines_no_block(self):
        a = _agent()
        prompt = a._build_analysis_prompt({"symbol": "BTCUSDT"})
        assert "KLINES" not in prompt

    def test_empty_list_no_block(self):
        a = _agent()
        prompt = a._build_analysis_prompt(
            {"klines_24h": [], "klines_24h_interval": "30m", "klines_24h_hours": 24}
        )
        assert "KLINES" not in prompt

    def test_caps_at_48_for_30m(self):
        a = _agent()
        klines = [_kline(t=i, o=50000 + i) for i in range(60)]
        prompt = a._build_analysis_prompt(
            {"klines_24h": klines, "klines_24h_interval": "30m", "klines_24h_hours": 24}
        )
        # count lines with "  t="
        lines = [line for line in prompt.splitlines() if "  t=" in line]
        assert len(lines) == 48

    def test_small_list_not_capped(self):
        a = _agent()
        klines = [_kline(t=i) for i in range(10)]
        prompt = a._build_analysis_prompt(
            {"klines_24h": klines, "klines_24h_interval": "30m", "klines_24h_hours": 24}
        )
        lines = [line for line in prompt.splitlines() if "  t=" in line]
        assert len(lines) == 10
