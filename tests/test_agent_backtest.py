"""Tests for agent-in-the-loop backtest modules (models, isolation, cache, report)."""
import json
import tempfile
from pathlib import Path

import pytest

from vibe_trading.backtest.agent_cache import (
    LLMCache,
    deserialize_response,
    prompt_hash,
    serialize_response,
)
from vibe_trading.backtest.agent_models import AgentReplayConfig, AgentReplayResult
from vibe_trading.backtest.agent_report import build_report, format_report


# === Models ===

class TestAgentModels:
    def test_defaults(self):
        config = AgentReplayConfig()
        assert config.symbol == "BTCUSDT"
        assert config.interval == "30m"
        assert config.start == 120
        assert config.resume is False
        assert config.use_cache is True
        assert config.yes is False

    def test_result_summary(self):
        result = AgentReplayResult(
            symbol="BTCUSDT",
            interval="30m",
            total_pnl=100.0,
            realized_pnl=80.0,
            unrealized_pnl=20.0,
            win_rate=0.5,
            decision_counts={"BUY": 1, "HOLD": 1},
            llm_cost_usd=0.01,
            llm_calls=13,
        )
        text = result.summary()
        assert "BTCUSDT" in text
        assert "80.00" in text
        assert "BUY" in text


# === Report ===

def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8",
    )
    return path


def _fixture_records() -> list[dict]:
    return [
        {
            "symbol": "BTCUSDT", "interval": "30m",
            "bar_open_ms": 1784876400000, "bar_close": 100.0,
            "decision": "BUY", "confidence": 0.8, "elapsed_s": 1.0,
            "account": {"balance": 10000.0, "positions": [], "equity": 10000.0},
        },
        {
            "symbol": "BTCUSDT", "interval": "30m",
            "bar_open_ms": 1784878200000, "bar_close": 110.0,
            "decision": "HOLD", "confidence": 0.6, "elapsed_s": 1.0,
            "account": {"balance": 10100.0, "positions": [], "equity": 10100.0},
        },
        {
            "symbol": "BTCUSDT", "interval": "30m",
            "bar_open_ms": 1784880000000, "bar_close": 95.0,
            "decision": "SELL", "confidence": 0.7, "elapsed_s": 1.0,
            "account": {"balance": 10150.0, "positions": [], "equity": 10150.0},
        },
    ]


class TestReport:
    def test_report_from_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            log = _write_jsonl(Path(td) / "decisions.jsonl", _fixture_records())
            result = build_report(str(log), with_cost=False)
            # balance: 10000 → 10100 → 10150; equity same (no open positions)
            assert result.total_pnl == pytest.approx(150.0)
            assert result.realized_pnl == pytest.approx(150.0)
            assert result.unrealized_pnl == pytest.approx(0.0)
            # balance deltas: +100 (win), +50 (win) → 2 closed, 2 winning
            assert result.win_rate == pytest.approx(1.0)
            assert result.decision_counts == {"BUY": 1, "HOLD": 1, "SELL": 1}
            assert len(result.records) == 3

    def test_report_skips_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "decisions.jsonl"
            lines = [json.dumps(r, ensure_ascii=False) for r in _fixture_records()]
            lines.insert(1, "{corrupt json!!!")
            path.write_text("\n".join(lines), encoding="utf-8")
            result = build_report(str(path), with_cost=False)
            assert len(result.records) == 3  # corrupt line skipped

    def test_report_empty_log(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            result = build_report(str(path), with_cost=False)
            assert len(result.records) == 0
            assert result.total_pnl == 0.0

    def test_format_report_includes_warning(self):
        with tempfile.TemporaryDirectory() as td:
            log = _write_jsonl(Path(td) / "d.jsonl", _fixture_records())
            result = build_report(str(log), with_cost=False)
            text = format_report(result)
            assert "單次採樣" in text
            assert "Realized" in text
            assert "BUY" in text


# === Cache ===

class TestLLMCache:
    @pytest.mark.asyncio
    async def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            cache = LLMCache(str(Path(td) / "cache.db"))
            h = prompt_hash("test prompt")
            assert await cache.get("model-a", "trader", h) is None
            await cache.put("model-a", "trader", h, serialize_response("cached answer"))
            got = await cache.get("model-a", "trader", h)
            assert deserialize_response(got) == "cached answer"
            # different hash → miss
            assert await cache.get("model-a", "trader", prompt_hash("other")) is None
            # different model → miss
            assert await cache.get("model-b", "trader", h) is None
            stats = await cache.get_stats()
            assert stats["entries"] == 1

    def test_prompt_hash_deterministic(self):
        assert prompt_hash("same") == prompt_hash("same")
        assert prompt_hash("same") != prompt_hash("different")


# === Tool isolation (look-ahead fixes) ===

class TestToolIsolation:
    @pytest.mark.asyncio
    async def test_live_tools_unavailable(self):
        from vibe_trading.backtest.agent_isolation import install_replay_tool_isolation
        from vibe_trading.data_sources.kline_storage import KlineStorage

        storage = KlineStorage(database_url="sqlite+aiosqlite:///:memory:")
        await storage.init()
        try:
            install_replay_tool_isolation(storage, interval="30m")

            import vibe_trading.tools.fundamental_tools as ft

            # MUST-FIX: coordinator calls these directly — must be unavailable
            r1 = await ft.get_funding_rates("BTCUSDT")
            assert "replay" in r1.get("error", "")
            r2 = await ft.get_open_interest("BTCUSDT")
            assert "replay" in r2.get("error", "")
            r3 = await ft.get_fear_and_greed_index()
            assert "replay" in r3.get("error", "")
        finally:
            await storage.close()

    @pytest.mark.asyncio
    async def test_price_accepts_storage_kwarg(self):
        from vibe_trading.backtest.agent_isolation import install_replay_tool_isolation
        from vibe_trading.data_sources.kline_storage import KlineStorage

        storage = KlineStorage(database_url="sqlite+aiosqlite:///:memory:")
        await storage.init()
        try:
            install_replay_tool_isolation(storage, interval="30m")

            import vibe_trading.tools.market_data_tools as mdt

            # coordinator._fetch_benchmark_price calls with storage= kwarg — must not TypeError
            result = await mdt.get_current_price("BTCUSDT", storage=storage)
            assert isinstance(result, dict)
        finally:
            await storage.close()
