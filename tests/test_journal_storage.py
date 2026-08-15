"""Tests for web DecisionJournalStorage — Wave D108."""
import pytest

from vibe_trading.web.journal_storage import DecisionJournalStorage


@pytest.fixture
def store(tmp_path):
    s = DecisionJournalStorage(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/journal.db")
    return s


class TestJournalStorage:
    @pytest.mark.asyncio
    async def test_init_and_upsert_get(self, store):
        await store.init()
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1000,
            bar_time="2026-01-01", update={"kline": {"close": 50000.0}})
        bar = await store.get_bar(symbol="BTCUSDT", interval="30m",
                                  open_time_ms=1000)
        assert bar is not None
        assert bar.kline["close"] == 50000.0
        assert bar.decision is None
        assert bar.executions == []

    @pytest.mark.asyncio
    async def test_upsert_update_merges(self, store):
        await store.init()
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1000,
            bar_time="t1", update={"kline": {"close": 1.0}})
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1000,
            bar_time="t2", update={"decision": {"decision": "BUY"}})
        bar = await store.get_bar(symbol="BTCUSDT", interval="30m",
                                  open_time_ms=1000)
        assert bar.kline["close"] == 1.0  # 保留
        assert bar.decision["decision"] == "BUY"

    @pytest.mark.asyncio
    async def test_upsert_report_log_execution(self, store):
        await store.init()
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1000,
            bar_time="t", update={
                "report": {"phase": "analyzing", "agent": "technical",
                           "content": "bullish"},
                "log": {"message": "hello"},
                "execution": {"tool_name": "submit_trade_order"},
            })
        bar = await store.get_bar(symbol="BTCUSDT", interval="30m",
                                  open_time_ms=1000)
        assert bar.reports["analyzing"]["technical"] == "bullish"
        assert bar.logs[0]["message"] == "hello"
        assert bar.executions[0]["tool_name"] == "submit_trade_order"

    @pytest.mark.asyncio
    async def test_upsert_report_default_phase(self, store):
        await store.init()
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1000,
            bar_time="t", update={"report": {"content": "x"}})
        bar = await store.get_bar(symbol="BTCUSDT", interval="30m",
                                  open_time_ms=1000)
        assert bar.reports["unknown"]["unknown"] == "x"

    @pytest.mark.asyncio
    async def test_logs_capped(self, store):
        await store.init()
        for i in range(150):
            await store.upsert_bar(
                symbol="BTCUSDT", interval="30m", open_time_ms=1000,
                bar_time="t", update={"log": {"message": f"m{i}"}})
        bar = await store.get_bar(symbol="BTCUSDT", interval="30m",
                                  open_time_ms=1000)
        assert len(bar.logs) <= 120

    @pytest.mark.asyncio
    async def test_list_bars_filters(self, store):
        await store.init()
        for i, sym in enumerate(["BTCUSDT", "ETHUSDT"]):
            await store.upsert_bar(
                symbol=sym, interval="30m", open_time_ms=1000 + i,
                bar_time="t", update={})
        bars = await store.list_bars(symbol="BTCUSDT")
        assert len(bars) == 1
        assert bars[0].symbol == "BTCUSDT"
        # ascending
        bars2 = await store.list_bars(descending=False, limit=10)
        assert len(bars2) == 2

    @pytest.mark.asyncio
    async def test_count_bars(self, store):
        await store.init()
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=1000,
            bar_time="t", update={})  # 無 decision
        await store.upsert_bar(
            symbol="BTCUSDT", interval="30m", open_time_ms=2000,
            bar_time="t", update={"decision": {"decision": "BUY"}})
        assert await store.count_bars() == 1  # 只算有 decision
        assert await store.count_bars(with_decision_only=False) == 2
        assert await store.count_bars(symbol="BTCUSDT") == 1
        assert await store.count_bars(symbol="NOPE") == 0

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, store):
        await store.init()
        assert await store.get_bar(symbol="X", interval="30m",
                                   open_time_ms=1) is None

    def test_resolve_db_path(self):
        assert DecisionJournalStorage._resolve_db_path(
            "sqlite+aiosqlite:////tmp/x.db") == "/tmp/x.db"
        assert DecisionJournalStorage._resolve_db_path(
            "sqlite:///./y.db") == "y.db"
        assert DecisionJournalStorage._resolve_db_path(
            "postgres://x") == "vibe_trading.db"

    def test_get_journal_storage_singleton(self):
        from vibe_trading.web.journal_storage import (
            get_journal_storage, reset_journal_storage_for_tests,
        )
        reset_journal_storage_for_tests()
        a = get_journal_storage()
        b = get_journal_storage()
        assert a is b
        reset_journal_storage_for_tests()
