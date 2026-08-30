"""Integration: MacroAnalysisThread._collect_market_data 注入 klines_24h → MacroAnalysisAgent prompt."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

from vibe_trading.threads.macro_thread import MacroAnalysisThread
from vibe_trading.agents.macro_agent import MacroAnalysisAgent


def _fake_rows(n: int = 48):
    return [
        SimpleNamespace(
            open_time=1_700_000_000_000 + i * 1_800_000,
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100.5 + i,
            volume=1000 + i,
        )
        for i in range(n)
    ]


def _thread_with_fake_storage(rows, interval="30m", lookback=24):
    t = MacroAnalysisThread.__new__(MacroAnalysisThread)
    t.symbol = "BTCUSDT"
    t.interval_seconds = 7200
    t.storage = MagicMock()
    storage = MagicMock()
    storage.query_klines = AsyncMock(return_value=rows)
    t.kline_storage = storage
    t.kline_lookback_hours = lookback
    t.kline_interval = interval
    t._agent = MagicMock()
    t._tool_context = MagicMock()
    t._running = False
    t._task = None
    t._total_runs = 0
    t._successful_runs = 0
    t._failed_runs = 0
    t._last_run_time = None
    return t


@pytest.mark.asyncio
async def test_collect_market_data_end_to_end_with_real_storage_shape():
    rows = _fake_rows(48)
    t = _thread_with_fake_storage(rows)

    from vibe_trading.threads import macro_thread as mt

    # Patch the other data sources to stable values
    with (
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            mt.sentiment_tools,
            "get_fear_and_greed_index",
            new=AsyncMock(return_value={"value": 50}),
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            mt.fundamental_tools,
            "get_funding_rates",
            new=AsyncMock(return_value={"rate": 0.01}),
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            mt.market_data_tools,
            "get_24hr_ticker",
            new=AsyncMock(return_value={"price": 1.0}),
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch.object(
            mt.sentiment_tools, "get_trending_symbols", new=AsyncMock(return_value=[])
        ),
    ):
        data = await t._collect_market_data()

    assert "klines_24h" in data
    assert len(data["klines_24h"]) == 48
    assert set(data["klines_24h"][0].keys()) == {"t", "o", "h", "l", "c", "v"}
    assert data["klines_24h_interval"] == "30m"
    assert data["klines_24h_hours"] == 24

    # Prompt 注入验证
    agent = MacroAnalysisAgent()
    prompt = agent._build_analysis_prompt(data)
    assert "24h KLINES" in prompt
    assert prompt.count("t=") == 48
