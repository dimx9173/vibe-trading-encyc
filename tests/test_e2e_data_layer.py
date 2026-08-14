"""
End-to-end tests for the external data layer (Phase 4).

Covers: full decision flow, backtest flow, plugin toggle, evidence gate,
and performance (per tasks file Task 4.6 acceptance criteria).
"""
import time as _time
from datetime import datetime, timedelta

import pytest

from vibe_trading.data_sources.decision_enhancer import DecisionEnhancer
from vibe_trading.data_sources.evidence_gate import (
    EvidenceGate,
    EvidenceGateConfig,
)
from vibe_trading.data_sources.performance_tracker import (
    PerformanceTracker,
    TradeRecord,
)
from vibe_trading.data_sources.report_generator import ReportGenerator


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeSentimentPlugin:
    """Available sentiment plugin"""
    name = "FakeSentiment"
    is_available = True

    def __init__(self, score: float = 0.8):
        self._score = score

    async def get_sentiment(self, symbol: str) -> float:
        return self._score


class BrokenSentimentPlugin:
    """Plugin that raises — must degrade, not crash"""
    name = "BrokenSentiment"
    is_available = True

    async def get_sentiment(self, symbol: str) -> float:
        raise RuntimeError("sentiment API down")


class DisabledSentimentPlugin:
    """Plugin marked unavailable"""
    name = "DisabledSentiment"
    is_available = False

    async def get_sentiment(self, symbol: str) -> float:
        return 0.5  # should never be called


# ---------------------------------------------------------------------------
# 完整決策流程測試
# ---------------------------------------------------------------------------

class TestFullDecisionFlow:
    """決策 → 插件增強 → 交易記錄 → 證據門控 → 報告 全流程"""

    @pytest.mark.asyncio
    async def test_enhanced_decision_flow(self, tmp_path):
        """Decision function wrapped by enhancer keeps decision and gains plugin data"""
        enhancer = DecisionEnhancer(sentiment_plugin=FakeSentimentPlugin())
        tracker = PerformanceTracker(str(tmp_path / "flow.db"))
        gate = EvidenceGate(
            tracker=tracker,
            config=EvidenceGateConfig(min_sharpe=0.0, min_trades=1),
            db_path=str(tmp_path / "gate.db"),
        )
        reporter = ReportGenerator(mode="paper")

        async def decide(symbol: str) -> dict:
            return {"decision": "BUY", "symbol": symbol, "quantity": 0.01}

        wrapped = enhancer.enhance(decide)
        result = await wrapped("BTCUSDT")

        assert result["decision"] == "BUY"
        assert result["enhancements"]["sentiment_score"] == 0.8
        assert result["enhancements"]["sentiment_source"] == "FakeSentiment"

        # 記錄一筆獲利交易並通過門控
        tracker.record_trade(
            TradeRecord(
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.01,
                entry_price=50_000,
                exit_price=50_100,
                realized_pnl=100.0,
                closed_at=datetime.now() - timedelta(days=1),
            )
        )
        evaluation = gate.evaluate_paper_performance(period_days=14)
        assert evaluation.passed

        report = reporter.build_report(
            symbol="BTCUSDT",
            metrics=tracker.get_metrics(),
            mode="paper",
        )
        assert report["metrics"]["trade_count"] == 1
        assert report["mode"] == "paper"

    @pytest.mark.asyncio
    async def test_broken_plugin_degrades_decision(self):
        """插件故障時決策仍執行，不中斷"""
        enhancer = DecisionEnhancer(sentiment_plugin=BrokenSentimentPlugin())

        async def decide(symbol: str) -> dict:
            return {"decision": "HOLD", "symbol": symbol}

        result = await enhancer.enhance(decide)("BTCUSDT")
        assert result["decision"] == "HOLD"
        # 故障 → 無 enhancements key（或無 sentiment_score）
        assert "sentiment_score" not in result.get("enhancements", {})

    @pytest.mark.asyncio
    async def test_disabled_plugin_skipped(self):
        """插件關閉時完全不調用，決策不受影響"""
        enhancer = DecisionEnhancer(sentiment_plugin=DisabledSentimentPlugin())

        async def decide(symbol: str) -> dict:
            return {"decision": "SELL", "symbol": symbol}

        result = await enhancer.enhance(decide)("BTCUSDT")
        assert result["decision"] == "SELL"
        assert "sentiment_score" not in result.get("enhancements", {})


# ---------------------------------------------------------------------------
# 回測流程測試
# ---------------------------------------------------------------------------

class TestBacktestFlow:
    """回測數據層 facade + 回測報告"""

    def test_backtest_data_loader_facade(self):
        """BacktestDataLoader 提供 binance/local/hybrid 來源"""
        from vibe_trading.backtest.data_loader import BacktestDataLoader, DataSource

        loader = BacktestDataLoader(default_source=DataSource.HYBRID)
        assert loader.default_source == DataSource.HYBRID
        assert DataSource.BINANCE.value == "binance"
        assert DataSource.LOCAL.value == "local"

    def test_backtest_report_marks_source_differences(self):
        """回測報告不含即時插件數據，並標記差異"""
        reporter = ReportGenerator(mode="backtest")
        report = reporter.build_report(
            symbol="BTCUSDT",
            metrics={"sharpe": 1.5, "win_rate": 0.6},
            data_sources=["歷史 K-line", "技術指標", "Alpha 因子", "Skills"],
        )
        assert report["data_source_notes"] == []  # 回測源無即時專用項
        assert "未使用新聞" in report["note"]

    @pytest.mark.asyncio
    async def test_backtest_loader_loads_klines(self):
        """BacktestDataLoader.load_klines 走新數據層、空庫安全回傳空 list"""
        from vibe_trading.backtest.data_loader import BacktestDataLoader, DataSource

        loader = BacktestDataLoader(default_source=DataSource.LOCAL)
        bars = await loader.load_klines(
            "BTCUSDT", "1h", limit=5, source=DataSource.LOCAL
        )
        assert isinstance(bars, list)  # 空 storage → []，不 crash

        # 無指定 source → 用 default
        bars2 = await loader.load_klines("BTCUSDT", "1h", limit=5)
        assert isinstance(bars2, list)

    @pytest.mark.asyncio
    async def test_engine_run_from_loader(self):
        """BacktestEngine.run_from_loader 走統一數據層並正規化 Kline → dict"""
        from datetime import datetime, timedelta, timezone
        from vibe_trading.backtest.engine import BacktestEngine
        from vibe_trading.backtest.models import BacktestConfig
        from vibe_trading.data_sources.base import Kline

        class FakeLoader:
            async def load_klines(self, symbol, interval, start=None, end=None, limit=None):
                base = datetime(2026, 1, 1, tzinfo=timezone.utc)
                return [
                    Kline(
                        symbol=symbol, interval=interval,
                        open_time=base + timedelta(hours=i),
                        open=100.0 + i * 0.5, high=101.0 + i * 0.5,
                        low=99.0 + i * 0.5, close=100.5 + i * 0.5,
                        volume=1000.0,
                    )
                    for i in range(100)
                ]

        class EmptyLoader:
            async def load_klines(self, **kwargs):
                return []

        cfg = BacktestConfig(
            symbol="BTCUSDT", interval="1h",
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        engine = BacktestEngine(cfg)

        result = await engine.run_from_loader(FakeLoader())
        assert result.symbol == "BTCUSDT"
        assert len(result.trades) > 0  # 趨勢數據產生 MA crossover 交易
        assert result.initial_balance == 10_000

        empty = await engine.run_from_loader(EmptyLoader())
        assert empty.total_trades == 0
        assert empty.final_balance == 10_000

    @pytest.mark.asyncio
    async def test_engine_run_from_loader_real_kline_int_ms(self):
        """run_from_loader 支援 binance_client.Kline（open_time 為 int 毫秒）"""
        from datetime import datetime, timezone
        from vibe_trading.backtest.engine import BacktestEngine
        from vibe_trading.backtest.models import BacktestConfig
        from vibe_trading.data_sources.binance_client import Kline as BinanceKline

        class RealKlineLoader:
            async def load_klines(self, symbol, interval, start=None, end=None, limit=None):
                base_ms = int(
                    datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
                )
                return [
                    BinanceKline(
                        symbol=symbol, interval=interval,
                        open_time=base_ms + i * 3_600_000,
                        open=100.0 + i * 0.5, high=101.0 + i * 0.5,
                        low=99.0 + i * 0.5, close=100.5 + i * 0.5,
                        volume=1000.0,
                        close_time=base_ms + i * 3_600_000 + 60_000,
                        quote_volume=100_000.0, trades=100,
                        taker_buy_base=500.0, taker_buy_quote=50_000.0,
                        is_final=True,
                    )
                    for i in range(100)
                ]

        cfg = BacktestConfig(
            symbol="BTCUSDT", interval="1h",
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        engine = BacktestEngine(cfg)

        result = await engine.run_from_loader(RealKlineLoader())
        assert result.total_trades > 0
        assert result.start_time.year == 2026

    @pytest.mark.asyncio
    async def test_data_loader_binance_source_uses_binance(self, monkeypatch):
        """source=BINANCE 走 BinanceClient.get_klines，不查 KlineStorage"""
        from vibe_trading.backtest.data_loader import BacktestDataLoader, DataSource
        from vibe_trading.data_sources.binance_client import BinanceRestClient

        captured = {}

        async def fake_get_klines(self, symbol, interval, limit=500,
                                  start_time=None, end_time=None):
            captured["symbol"] = symbol
            captured["interval"] = interval
            return [[1767225600000, "100.0", "101.0", "99.0", "100.5", "1000.0",
                     1767229200000, "0", 0, "0", "0", "0"]]

        monkeypatch.setattr(BinanceRestClient, "get_klines", fake_get_klines)

        loader = BacktestDataLoader(default_source=DataSource.BINANCE)
        bars = await loader.load_klines("BTCUSDT", "1h", limit=5)
        assert captured.get("symbol") == "BTCUSDT"
        assert len(bars) == 1
        assert bars[0].open == 100.0

    @pytest.mark.asyncio
    async def test_data_loader_hybrid_falls_back_to_binance(self, monkeypatch):
        """HYBRID：本地 storage 空 → 回退 BinanceClient"""
        from vibe_trading.backtest.data_loader import BacktestDataLoader, DataSource
        from vibe_trading.data_sources.binance_client import BinanceRestClient

        captured = {}

        async def fake_get_klines(self, symbol, interval, limit=500,
                                  start_time=None, end_time=None):
            captured["symbol"] = symbol
            return [[1767225600000, "100.0", "101.0", "99.0", "100.5", "1000.0",
                     1767229200000, "0", 0, "0", "0", "0"]]

        monkeypatch.setattr(BinanceRestClient, "get_klines", fake_get_klines)

        loader = BacktestDataLoader(default_source=DataSource.HYBRID)
        bars = await loader.load_klines("BTCUSDT", "1h", limit=5)
        assert captured.get("symbol") == "BTCUSDT"
        assert len(bars) == 1

    @pytest.mark.asyncio
    async def test_data_loader_local_never_calls_binance(self, monkeypatch):
        """source=LOCAL 只查 KlineStorage，絕不呼叫 BinanceClient"""
        from vibe_trading.backtest.data_loader import BacktestDataLoader, DataSource
        from vibe_trading.data_sources.binance_client import BinanceRestClient

        async def boom(self, *args, **kwargs):
            raise AssertionError("BINANCE called for LOCAL source")

        monkeypatch.setattr(BinanceRestClient, "get_klines", boom)

        loader = BacktestDataLoader(default_source=DataSource.LOCAL)
        bars = await loader.load_klines("BTCUSDT", "1h", limit=5)
        assert bars == []


# ---------------------------------------------------------------------------
# 插件開關測試
# ---------------------------------------------------------------------------

class TestPluginToggle:
    """插件開關：可用 / 故障 / 停用 三態"""

    @pytest.mark.asyncio
    async def test_plugin_states(self):
        on = DecisionEnhancer(sentiment_plugin=FakeSentimentPlugin(0.3))
        broken = DecisionEnhancer(sentiment_plugin=BrokenSentimentPlugin())
        off = DecisionEnhancer()

        ctx_on = await on.gather_context("BTCUSDT")
        assert ctx_on["sentiment_score"] == 0.3

        ctx_broken = await broken.gather_context("BTCUSDT")
        assert "sentiment_score" not in ctx_broken

        ctx_off = await off.gather_context("BTCUSDT")
        assert ctx_off == {}

    @pytest.mark.asyncio
    async def test_no_plugin_key_when_no_enhancement(self):
        enhancer = DecisionEnhancer()

        async def decide(symbol: str) -> dict:
            return {"decision": "HOLD", "symbol": symbol}

        result = await enhancer.enhance(decide)("BTCUSDT")
        assert result == {"decision": "HOLD", "symbol": "BTCUSDT"}


# ---------------------------------------------------------------------------
# 證據門控測試
# ---------------------------------------------------------------------------

class TestEvidenceGateFlow:
    """門控：通過 / 樣本不足 / 績效不佳 三態 + 歷史記錄"""

    def _good_tracker(self, path, n=10):
        tracker = PerformanceTracker(path)
        for i in range(n):
            tracker.record_trade(
                TradeRecord(
                    symbol="BTCUSDT",
                    side="BUY",
                    quantity=0.01,
                    entry_price=50_000 + i,
                    exit_price=50_000 + i + 50,
                    realized_pnl=60.0 + (i % 4) * 10.0,
                    closed_at=datetime.now() - timedelta(hours=i),
                )
            )
        return tracker

    def test_gate_passes_with_good_performance(self, tmp_path):
        tracker = self._good_tracker(str(tmp_path / "good.db"))
        gate = EvidenceGate(
            tracker=tracker,
            config=EvidenceGateConfig(min_sharpe=0.3, min_trades=3),
            db_path=str(tmp_path / "gate.db"),
        )
        result = gate.evaluate_paper_performance(period_days=14)
        assert result.passed
        assert "Live" in result.recommendation
        assert gate.latest_evaluation()["passed"] is True

    def test_gate_rejects_insufficient_samples(self, tmp_path):
        tracker = PerformanceTracker(str(tmp_path / "empty.db"))
        gate = EvidenceGate(
            tracker=tracker,
            config=EvidenceGateConfig(min_trades=5),
            db_path=str(tmp_path / "gate2.db"),
        )
        result = gate.evaluate_paper_performance(trades=[])
        assert not result.passed
        assert "樣本不足" in result.recommendation

    def test_gate_rejects_poor_sharpe(self, tmp_path):
        tracker = PerformanceTracker(str(tmp_path / "poor.db"))
        for i in range(8):
            tracker.record_trade(
                TradeRecord(
                    symbol="BTCUSDT",
                    side="BUY",
                    quantity=0.01,
                    entry_price=50_000 + i,
                    exit_price=50_000 + i + 5,
                    realized_pnl=10.0 if i % 2 == 0 else -10.0,
                    closed_at=datetime.now() - timedelta(hours=i),
                )
            )
        gate = EvidenceGate(
            tracker=tracker,
            config=EvidenceGateConfig(min_sharpe=1.0, min_trades=3),
            db_path=str(tmp_path / "gate3.db"),
        )
        result = gate.evaluate_paper_performance(trades=tracker.get_trades())
        assert not result.passed
        assert "Sharpe" in result.recommendation

    def test_gate_evaluation_history(self, tmp_path):
        tracker = self._good_tracker(str(tmp_path / "hist.db"), n=6)
        gate = EvidenceGate(
            tracker=tracker,
            config=EvidenceGateConfig(min_sharpe=0.3, min_trades=2),
            db_path=str(tmp_path / "gate_hist.db"),
        )
        gate.evaluate_paper_performance(period_days=14)
        gate.evaluate_paper_performance(period_days=7)
        history = gate.get_evaluations()
        assert len(history) == 2
        assert history[0]["evaluated_at"] >= history[1]["evaluated_at"]  # newest first

    def test_max_drawdown_is_ratio_and_order_independent(self, tmp_path):
        """MaxDD 為 PnL 曲線比率（峰值間峰谷/峰值），且與輸入順序無關"""
        from datetime import timezone

        tracker = PerformanceTracker(str(tmp_path / "dd.db"))
        trades = [
            TradeRecord(
                symbol="BTCUSDT", side="BUY", quantity=0.01,
                entry_price=50_000, exit_price=51_000, realized_pnl=100.0,
                closed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
            TradeRecord(
                symbol="BTCUSDT", side="SELL", quantity=0.01,
                entry_price=50_000, exit_price=49_500, realized_pnl=-50.0,
                closed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
            TradeRecord(
                symbol="BTCUSDT", side="BUY", quantity=0.01,
                entry_price=50_000, exit_price=51_000, realized_pnl=100.0,
                closed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
            TradeRecord(
                symbol="BTCUSDT", side="SELL", quantity=0.01,
                entry_price=50_000, exit_price=49_400, realized_pnl=-60.0,
                closed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            ),
        ]
        # 累計 PnL: 100 → 50（峰值100, DD 0.5）→ 150 → 90（峰值150, DD 0.4）
        # 標準 MaxDD = 逐點 (峰值-累計)/峰值 之最大 → 0.5
        expected = 0.5

        assert tracker.max_drawdown(trades) == pytest.approx(expected)
        # 逆序輸入（get_trades() 預設 DESC 傳入）結果一致
        assert tracker.max_drawdown(list(reversed(trades))) == pytest.approx(expected)
        dd = tracker.max_drawdown(trades)
        assert 0.0 <= dd <= 1.0

    def test_sharpe_normalizes_by_notional(self, tmp_path):
        """Sharpe 以每筆報酬率（PnL/名目倉位）計算，不被倉位規模主導"""
        from datetime import timezone

        tracker = PerformanceTracker(str(tmp_path / "sharpe.db"))
        # A: 大倉低報酬（2 BTC @ 50000 → +100 = 0.1%）；B: 小倉高報酬（0.04 BTC → +200 = 10%）
        # 美元 PnL 比值 2，報酬率比值 100 → 兩者 Sharpe 必須不同
        trades = [
            TradeRecord(
                symbol="BTCUSDT", side="BUY", quantity=2.0,
                entry_price=50_000, exit_price=50_100, realized_pnl=100.0,
                closed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
            TradeRecord(
                symbol="BTCUSDT", side="BUY", quantity=0.04,
                entry_price=50_000, exit_price=52_000, realized_pnl=200.0,
                closed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
        ]
        # 報酬率 0.001 / 0.1 → mean 0.0505, std 0.070004 → sharpe ≈ 0.7214
        assert tracker.sharpe_ratio(trades) == pytest.approx(0.7214, abs=1e-3)

    def test_sharpe_scale_free_under_uniform_scaling(self, tmp_path):
        """同一報酬型態、倉位等比放大 → Sharpe 不變"""
        from datetime import timezone

        def build(pnl_list, quantity):
            tracker = PerformanceTracker(str(tmp_path / f"s_{quantity}.db"))
            for i, p in enumerate(pnl_list):
                tracker.record_trade(
                    TradeRecord(
                        symbol="BTCUSDT", side="BUY", quantity=quantity,
                        entry_price=50_000, exit_price=50_100,
                        realized_pnl=p,
                        closed_at=datetime(2026, 8, 1 + i, tzinfo=timezone.utc),
                    )
                )
            return tracker

        # 0.01 BTC 賺 100 → 報酬率 0.2；0.1 BTC 賺 1000 → 報酬率同樣 0.2
        small = build([100.0, -50.0, 200.0, -100.0], 0.01)
        big = build([1000.0, -500.0, 2000.0, -1000.0], 0.1)
        assert small.sharpe_ratio() == pytest.approx(big.sharpe_ratio())


# ---------------------------------------------------------------------------
# 性能測試
# ---------------------------------------------------------------------------

class TestPerformance:
    """500 筆交易記錄 + 指標計算效能上限"""

    def test_500_trades_roundtrip_and_metrics(self, tmp_path):
        tracker = PerformanceTracker(str(tmp_path / "perf.db"))

        t0 = _time.time()
        for i in range(500):
            tracker.record_trade(
                TradeRecord(
                    symbol="BTCUSDT",
                    side="BUY",
                    quantity=0.01,
                    entry_price=50_000 + i,
                    exit_price=50_000 + i + (10 if i % 3 else -10),
                    realized_pnl=50.0 if i % 3 else -40.0,
                    closed_at=datetime.now() - timedelta(hours=i),
                )
            )
        write_elapsed = _time.time() - t0

        trades = tracker.get_trades()
        assert len(trades) == 500

        t1 = _time.time()
        metrics = tracker.get_metrics()
        metrics_elapsed = _time.time() - t1

        assert metrics["trade_count"] == 500
        assert 0 < metrics["win_rate"] < 1
        # i in 0..499: i%3==0 有 167 筆 (-40)，其餘 333 筆 (+50)
        assert metrics["total_pnl"] == pytest.approx(167 * -40.0 + 333 * 50.0)

        # CI 安全上限（非嚴格基準）
        assert write_elapsed < 10.0, f"500 寫入過慢: {write_elapsed:.2f}s"
        assert metrics_elapsed < 2.0, f"指標計算過慢: {metrics_elapsed:.2f}s"
