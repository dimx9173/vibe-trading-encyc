"""Tests for data storage layers (Wave A — coverage 85% plan).

新聞/宏觀/情緒/基本面 4 個 SQLAlchemy async sqlite storage.
模式: XStorage(f"sqlite:///{tmp_path}") + init() + CRUD (與 test_decision_journal_persistence 一致).
"""
from pathlib import Path

from vibe_trading.data_sources.fundamental_storage import (
    FundamentalData,
    FundamentalStorage,
    get_fundamental_storage,
    reset_fundamental_storage,
)
from vibe_trading.data_sources.macro_storage import (
    MacroState,
    MacroStorage,
    get_macro_storage,
    reset_macro_storage,
)
from vibe_trading.data_sources.news_storage import (
    NewsData,
    NewsStorage,
    get_news_storage,
    reset_news_storage,
)
from vibe_trading.data_sources.sentiment_storage import (
    SentimentData,
    SentimentStorage,
    get_sentiment_storage,
    reset_sentiment_storage,
)

T0 = 1_700_000_000_000  # 2023-11-14 UTC ms


def _news(symbol: str = "BTCUSDT", ts: int = T0, url: str = "https://x.com/1") -> NewsData:
    return NewsData(
        symbol=symbol, timestamp=ts, title="BTC 突破 40000",
        content="比特幣突破 40000 美元", url=url, source="test",
        sentiment="positive", sentiment_score=0.8,
        relevance_score=0.9, categories=["macro", "price"],
        author="tester", published_at=ts,
    )


def _macro(symbol: str = "BTCUSDT", ts: int = T0, trend: str = "UPTREND") -> MacroState:
    return MacroState(
        symbol=symbol, timestamp=ts,
        trend_direction=trend, trend_strength="STRONG", market_regime="BULL",
        overall_sentiment="POSITIVE", sentiment_score=65.0,
        major_events=[{"event": "halving"}], agent_recommendation={"action": "HOLD"},
        confidence=0.85, analysis_duration=2.5,
    )


def _sentiment(symbol: str = "BTC", ts: int = T0) -> SentimentData:
    return SentimentData(
        symbol=symbol, timestamp=ts,
        fear_greed_value=75, fear_greed_classification="Greed",
        social_sentiment_score=0.4, social_volume=1000, social_influence=0.6,
        trend_sentiment="bullish", trend_strength=0.7,
        put_call_ratio=0.9, implied_volatility=0.5,
        data_source="test", updated_at=ts,
    )


def _fundamental(symbol: str = "BTCUSDT", ts: int = T0) -> FundamentalData:
    return FundamentalData(
        symbol=symbol, timestamp=ts,
        funding_rate=0.0001, mark_price=40000.0, index_price=39999.0,
        open_interest=100.0, open_interest_value=4_000_000.0,
        funding_rate_annualized=0.0876, next_funding_time=ts + 8 * 3600 * 1000,
    )


class TestNewsStorage:
    async def test_init_creates_db(self, tmp_path: Path):
        db = tmp_path / "news.db"
        s = NewsStorage(f"sqlite+aiosqlite:///{db}")
        await s.init()
        assert db.exists() and db.stat().st_size > 0
        await s.close()

    async def test_save_and_get(self, tmp_path: Path):
        s = NewsStorage(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
        await s.init()
        assert await s.save_news(_news()) is True
        got = await s.get_news_at("BTCUSDT", T0)
        assert got is not None and len(got) == 1
        assert got[0].title == "BTC 突破 40000"
        assert got[0].categories == ["macro", "price"]
        await s.close()

    async def test_save_duplicate_skips(self, tmp_path: Path):
        s = NewsStorage(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
        await s.init()
        await s.save_news(_news())
        await s.save_news(_news())  # 同 symbol/ts/url
        got = await s.get_news_at("BTCUSDT", T0)
        assert got is not None and len(got) == 1
        await s.close()

    async def test_save_batch(self, tmp_path: Path):
        s = NewsStorage(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
        await s.init()
        batch = [_news(url=f"https://x.com/{i}") for i in range(3)]
        assert await s.save_news_batch(batch) == 3
        await s.close()

    async def test_get_history_with_filters(self, tmp_path: Path):
        s = NewsStorage(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
        await s.init()
        await s.save_news(_news(url="https://x.com/pos"))
        await s.save_news(NewsData(
            symbol="BTCUSDT", timestamp=T0 + 1000, title="負面消息",
            content="c", url="https://x.com/neg", source="test",
            sentiment="negative", sentiment_score=-0.5,
            relevance_score=0.7, categories=["macro"],
        ))
        hist = await s.get_news_history("BTCUSDT", T0, T0 + 5000, sentiment="negative")
        assert len(hist) == 1 and hist[0].sentiment == "negative"
        hist_all = await s.get_news_history("BTCUSDT", T0, T0 + 5000)
        assert len(hist_all) == 2
        await s.close()

    async def test_get_latest_news(self, tmp_path: Path):
        s = NewsStorage(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
        await s.init()
        await s.save_news(_news(ts=T0))
        await s.save_news(_news(ts=T0 + 5000, url="https://x.com/later"))
        latest = await s.get_latest_news("BTCUSDT")
        assert latest is not None and latest[0].timestamp == T0 + 5000
        await s.close()

    async def test_empty_returns_none(self, tmp_path: Path):
        s = NewsStorage(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
        await s.init()
        assert await s.get_news_at("BTCUSDT", T0) == []
        assert await s.get_latest_news("BTCUSDT") == []
        assert await s.get_news_history("BTCUSDT", T0, T0) == []
        await s.close()

    async def test_news_data_roundtrip(self):
        d = _news()
        assert NewsData.from_dict(d.to_dict()) == d

    async def test_global_singleton(self):
        reset_news_storage()
        a, b = get_news_storage(), get_news_storage()
        assert a is b
        reset_news_storage()


class TestMacroStorage:
    async def test_save_and_get_latest(self, tmp_path: Path):
        s = MacroStorage(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
        await s.init()
        await s.save_state(_macro(ts=T0))
        await s.save_state(_macro(ts=T0 + 1000, trend="DOWNTREND"))
        latest = await s.get_latest_state("BTCUSDT")
        assert latest is not None and latest.trend_direction == "DOWNTREND"
        assert latest.major_events == [{"event": "halving"}]
        await s.close()

    async def test_get_by_timestamp_tolerance(self, tmp_path: Path):
        s = MacroStorage(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
        await s.init()
        await s.save_state(_macro(ts=T0))
        # 偏移 30s 內 → 命中
        got = await s.get_state_by_timestamp("BTCUSDT", T0 + 30_000, tolerance_seconds=60)
        assert got is not None and got.timestamp == T0
        # 偏移超容差 → None
        miss = await s.get_state_by_timestamp("BTCUSDT", T0 + 120_000, tolerance_seconds=60)
        assert miss is None
        await s.close()

    async def test_get_history_with_bounds(self, tmp_path: Path):
        s = MacroStorage(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
        await s.init()
        for i, ts in enumerate([T0, T0 + 1000, T0 + 2000]):
            await s.save_state(_macro(ts=ts, trend=["UPTREND", "SIDEWAYS", "DOWNTREND"][i]))
        hist = await s.get_history("BTCUSDT", start_time=T0 + 1000)
        assert len(hist) == 2  # ts >= T0+1000
        hist2 = await s.get_history("BTCUSDT", end_time=T0 + 1000)
        assert len(hist2) == 2  # ts <= T0+1000
        await s.close()

    async def test_compare_states(self, tmp_path: Path):
        s = MacroStorage(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
        await s.init()
        a = _macro(trend="UPTREND")
        a.market_regime = "BULL"
        a.overall_sentiment = "POSITIVE"
        a.sentiment_score = 50.0
        a.confidence = 0.5
        b = _macro(trend="DOWNTREND")
        b.market_regime = "BEAR"
        b.overall_sentiment = "NEGATIVE"
        b.sentiment_score = 80.0
        b.confidence = 0.9
        changes = await s.compare_states(a, b)
        assert "trend_direction" in changes
        assert "market_regime" in changes
        assert "overall_sentiment" in changes
        assert changes["sentiment_score_change"] == 30.0
        assert "confidence" in changes
        await s.close()

    async def test_delete_old_and_statistics(self, tmp_path: Path):
        s = MacroStorage(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
        await s.init()
        now = __import__("time").time() * 1000
        await s.save_state(_macro(ts=int(now - 60 * 24 * 3600 * 1000), trend="UPTREND"))  # 60 天前
        await s.save_state(_macro(ts=int(now - 1000), trend="DOWNTREND"))  # 剛存
        deleted = await s.delete_old_states(days_to_keep=30)
        assert deleted == 1
        stats = await s.get_statistics("BTCUSDT")
        assert stats["total_records"] == 1
        assert stats["latest_timestamp"] is not None
        assert "DOWNTREND" in stats["trend_distribution"]
        await s.close()

    async def test_empty_returns(self, tmp_path: Path):
        s = MacroStorage(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
        await s.init()
        assert await s.get_latest_state("BTCUSDT") is None
        assert await s.get_state_by_timestamp("BTCUSDT", T0) is None
        assert await s.get_history("BTCUSDT") == []
        stats = await s.get_statistics("BTCUSDT")
        assert stats["total_records"] == 0
        await s.close()

    async def test_macro_roundtrip(self):
        m = _macro()
        assert MacroState.from_dict(m.to_dict()) == m

    async def test_global_singleton(self):
        reset_macro_storage()
        a, b = get_macro_storage(), get_macro_storage()
        assert a is b
        reset_macro_storage()


class TestSentimentStorage:
    async def test_save_and_get_at(self, tmp_path: Path):
        s = SentimentStorage(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
        await s.init()
        await s.save_sentiment(_sentiment())
        got = await s.get_sentiment_at("BTC", T0 + 1000, tolerance_seconds=10)
        assert got is not None and got.fear_greed_value == 75
        miss = await s.get_sentiment_at("BTC", T0 + 3_600_001, tolerance_seconds=3600)
        assert miss is None
        await s.close()

    async def test_history_and_latest(self, tmp_path: Path):
        s = SentimentStorage(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
        await s.init()
        await s.save_sentiment(_sentiment(ts=T0))
        await s.save_sentiment(_sentiment(ts=T0 + 1000))
        hist = await s.get_sentiment_history("BTC", T0, T0 + 5000)
        assert len(hist) == 2
        latest = await s.get_latest_sentiment("BTC")
        assert latest is not None and latest.timestamp == T0 + 1000
        await s.close()

    async def test_fear_greed_history(self, tmp_path: Path):
        s = SentimentStorage(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
        await s.init()
        await s.save_sentiment(_sentiment(symbol="GLOBAL", ts=T0))
        await s.save_sentiment(_sentiment(symbol="GLOBAL", ts=T0 + 1000))
        fg = await s.get_fear_greed_history(T0, T0 + 5000)
        assert len(fg) == 2 and all(d.symbol == "GLOBAL" for d in fg)
        await s.close()

    async def test_empty(self, tmp_path: Path):
        s = SentimentStorage(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
        await s.init()
        assert await s.get_sentiment_at("BTC", T0) is None
        assert await s.get_sentiment_history("BTC", T0, T0) == []
        assert await s.get_latest_sentiment("BTC") is None
        await s.close()

    async def test_sentiment_roundtrip(self):
        d = _sentiment()
        assert SentimentData.from_dict(d.to_dict()) == d

    async def test_global_singleton(self):
        reset_sentiment_storage()
        a, b = get_sentiment_storage(), get_sentiment_storage()
        assert a is b
        reset_sentiment_storage()


class TestFundamentalStorage:
    async def test_save_and_get(self, tmp_path: Path):
        s = FundamentalStorage(f"sqlite+aiosqlite:///{tmp_path / 'f.db'}")
        await s.init()
        await s.save_fundamental_data(_fundamental())
        got = await s.get_fundamental_data("BTCUSDT", T0, tolerance_seconds=60)
        assert got is not None and got.funding_rate == 0.0001
        assert got.open_interest_value == 4_000_000.0
        miss = await s.get_fundamental_data("BTCUSDT", T0 + 120_000, tolerance_seconds=60)
        assert miss is None
        await s.close()

    async def test_history_and_latest(self, tmp_path: Path):
        s = FundamentalStorage(f"sqlite+aiosqlite:///{tmp_path / 'f.db'}")
        await s.init()
        await s.save_fundamental_data(_fundamental(ts=T0))
        await s.save_fundamental_data(_fundamental(ts=T0 + 1000))
        hist = await s.get_fundamental_history("BTCUSDT", T0, T0 + 5000)
        assert len(hist) == 2
        latest = await s.get_latest_fundamental_data("BTCUSDT")
        assert latest is not None and latest.timestamp == T0 + 1000
        await s.close()

    async def test_empty(self, tmp_path: Path):
        s = FundamentalStorage(f"sqlite+aiosqlite:///{tmp_path / 'f.db'}")
        await s.init()
        assert await s.get_fundamental_data("BTCUSDT", T0) is None
        assert await s.get_fundamental_history("BTCUSDT", T0, T0) == []
        assert await s.get_latest_fundamental_data("BTCUSDT") is None
        await s.close()

    async def test_fundamental_roundtrip(self):
        d = _fundamental()
        assert FundamentalData.from_dict(d.to_dict()) == d

    async def test_global_singleton(self):
        reset_fundamental_storage()
        a, b = get_fundamental_storage(), get_fundamental_storage()
        assert a is b
        reset_fundamental_storage()
