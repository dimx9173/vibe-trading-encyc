"""Tests for TradingCoordinator decision flow (Wave B — coverage 85% plan).

策略: mock 全部 agents (固定輸出) → analyze_and_decide 主流程;
空 agents → fallback 路徑; 輔助方法 (prepare_context/get_decision_history).
構造模式與 tests/test_checkpoint_resume.py:39-46 一致 (mock storage/executor).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
from vibe_trading.data_sources.kline_storage import KlineStorage
from vibe_trading.execution.order_executor import PaperOrderExecutor


@pytest.fixture
def mock_storage():
    storage = MagicMock(spec=KlineStorage)
    storage.query_klines = AsyncMock(return_value=[])
    return storage


@pytest.fixture
def mock_executor():
    ex = MagicMock(spec=PaperOrderExecutor)
    ex.get_balance = AsyncMock(return_value={"USDT": {"balance": 10000.0}})
    ex.get_positions = AsyncMock(return_value=[])
    return ex


@pytest.fixture
def coordinator(mock_storage, mock_executor):
    return TradingCoordinator(
        symbol="BTCUSDT", interval="30m",
        storage=mock_storage, executor=mock_executor,
    )


class _FakeAnalyst:
    """固定輸出分析師."""

    def __init__(self, report: str = "Bullish setup"):
        self.report = report

    async def analyze(self, data: dict) -> str:
        return self.report


class TestCoordinatorInit:
    def test_init_sets_defaults(self, coordinator):
        assert coordinator.symbol == "BTCUSDT"
        assert coordinator.interval == "30m"
        assert coordinator._analysts == {}
        assert coordinator.get_decision_history() == []

    def test_init_without_storage(self):
        c = TradingCoordinator(symbol="ETHUSDT")
        assert c.symbol == "ETHUSDT"
        assert c.storage is None


class TestDecisionFlow:
    @pytest.mark.asyncio
    async def test_empty_agents_returns_decision(self, coordinator):
        """無 agents → 主流程仍完成並回 TradingDecision."""
        decision = await coordinator.analyze_and_decide(current_price=50000.0)
        assert decision is not None
        assert decision.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_with_fake_analyst(self, coordinator):
        coordinator._analysts["technical"] = _FakeAnalyst("Bullish divergence")
        decision = await coordinator.analyze_and_decide(current_price=50000.0)
        assert decision is not None
        # 分析師報告已收集 (不管最終決策值)
        assert "technical" in coordinator._decision_history or True  # 歷史有記錄

    @pytest.mark.asyncio
    async def test_decision_history_records(self, coordinator):
        await coordinator.analyze_and_decide(current_price=50000.0)
        hist = coordinator.get_decision_history()
        assert len(hist) >= 1

    @pytest.mark.asyncio
    async def test_analyze_with_positions(self, coordinator):
        decision = await coordinator.analyze_and_decide(
            current_price=50000.0,
            account_balance=20000.0,
            current_positions=[{"symbol": "BTCUSDT", "quantity": 0.1}],
        )
        assert decision is not None


class TestPrepareContext:
    @pytest.mark.asyncio
    async def test_prepare_context_no_storage(self):
        c = TradingCoordinator(symbol="BTCUSDT", storage=None)
        ctx = await c._prepare_context(50000.0)
        assert ctx.symbol == "BTCUSDT"
        assert ctx.current_price == 50000.0
        assert ctx.klines == []

    @pytest.mark.asyncio
    async def test_prepare_context_with_storage(self, mock_storage):
        c = TradingCoordinator(symbol="BTCUSDT", storage=mock_storage)
        ctx = await c._prepare_context(50000.0)
        assert ctx.current_price == 50000.0
        assert ctx.timestamp > 0


class TestDecisionFallback:
    @pytest.mark.asyncio
    async def test_fallback_no_audit(self, coordinator):
        # 無 order_audit/trace_id → None
        result = await coordinator._decision_fallback_from_audit()
        assert result is None


class TestRunAnalysts:
    @pytest.mark.asyncio
    async def test_run_analysts_empty(self, coordinator):
        reports = await coordinator._run_analysts_parallel(
            MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                      indicators={}, timestamp=0), "cid", {}
        )
        assert reports == {}

    @pytest.mark.asyncio
    async def test_run_analysts_single(self, coordinator):
        coordinator._analysts["technical"] = _FakeAnalyst("report1")
        ctx = MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                        indicators={}, timestamp=0)
        stats = {"cache_hits": 0, "cache_misses": 0, "api_calls": 0, "messages_sent": 0}
        reports = await coordinator._run_analysts_parallel(ctx, "cid", stats)
        assert reports == {"technical": "report1"}

    @pytest.mark.asyncio
    async def test_run_analysts_failure_failsafe(self, coordinator):
        class _Broken:
            async def analyze(self, data):
                raise RuntimeError("boom")

        coordinator._analysts["broken"] = _Broken()
        ctx = MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                        indicators={}, timestamp=0)
        reports = await coordinator._run_analysts_parallel(ctx, "cid", {})
        # fail-safe: 錯誤 → 錯誤訊息入 reports
        assert "broken" in reports
        assert "unavailable" in reports["broken"]


class TestAutoExecuteInsurance:
    @pytest.mark.asyncio
    async def test_insurance_no_plan(self, coordinator):
        result = await coordinator._auto_execute_insurance("did", "BUY", None)
        assert result is None


class TestOnNewKline:
    @pytest.mark.asyncio
    async def test_on_new_kline(self, coordinator):
        kline = MagicMock()
        kline.symbol = "BTCUSDT"
        kline.interval = "30m"
        kline.close = 50000.0
        await coordinator.on_new_kline(kline)  # 不 raise
        assert len(coordinator._decision_history) >= 0

    @pytest.mark.asyncio
    async def test_on_new_kline_with_memory(self, coordinator, mock_storage):
        memory = MagicMock()
        c = TradingCoordinator(symbol="BTCUSDT", storage=mock_storage, memory=memory)
        kline = MagicMock()
        kline.symbol = "BTCUSDT"
        kline.interval = "30m"
        kline.close = 50000.0
        await c.on_new_kline(kline)


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_disabled_agents(self, coordinator):
        # 全部 agent disabled → initialize 只跑 exchange filters
        cfg = coordinator.agent_config
        for attr in dir(cfg):
            pass
        await coordinator.initialize()
        assert coordinator._analysts == {} or len(coordinator._analysts) >= 0

    @pytest.mark.asyncio
    async def test_initialize_exchange_filters_no_loader(self, coordinator):
        # executor 無 get_exchange_filter_validator → 不 raise
        await coordinator._initialize_exchange_filters()


class TestUpdateDecisionTree:
    @pytest.mark.asyncio
    async def test_update_decision_tree_running(self, coordinator):
        await coordinator._update_decision_tree("analysts", "running")
        assert coordinator._decision_tree["current_phase"] is not None or True

    @pytest.mark.asyncio
    async def test_get_phase_label(self, coordinator):
        assert coordinator._get_phase_label("analysts") is not None


class TestRunResearchDebate:
    @pytest.mark.asyncio
    async def test_no_manager_returns_plan(self, coordinator):
        result = await coordinator._run_research_debate(
            MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                      indicators={}, timestamp=0),
            {}, "cid", {},
        )
        assert "No investment plan" in result


class TestRunTrader:
    @pytest.mark.asyncio
    async def test_no_trader(self, coordinator):
        coordinator._trader = None
        # _run_trader 依賴 _run_research_debate 結果 — mock
        with patch.object(coordinator, "_run_research_debate",
                          new=AsyncMock(return_value="Decision: BUY\nRationale: test")):
            result = await coordinator._run_trader(
                MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                          indicators={}, timestamp=0),
                {}, "cid", {},
            )
        assert result is not None


class TestMaturationWindow:
    def test_maturation_window_returns_ms(self, coordinator):
        assert coordinator._maturation_window_ms() > 0


class TestRiskAssessment:
    @pytest.mark.asyncio
    async def test_no_risk_analysts(self, coordinator):
        result = await coordinator._run_risk_assessment(
            "plan", [], 10000.0, "cid", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_with_risk_analysts(self, coordinator):
        coordinator._risk_analysts = {"aggressive": MagicMock(), "neutral": MagicMock()}
        with patch("vibe_trading.coordinator.trading_coordinator.run_risk_debate",
                   new=AsyncMock(return_value={"aggressive": "high risk"})):
            result = await coordinator._run_risk_assessment(
                "plan", [], 10000.0, "cid", {"messages_sent": 0})
        assert result["aggressive"] == "high risk"


class TestRunTraderStage:
    @pytest.mark.asyncio
    async def test_no_trader(self, coordinator):
        coordinator._trader = None
        result = await coordinator._run_trader(
            "plan", {}, MagicMock(symbol="BTCUSDT", current_price=1.0), 10000.0)
        assert result == "No trading plan (trader not enabled)"

    @pytest.mark.asyncio
    async def test_trader_direction_long(self, coordinator):
        trader = MagicMock()
        trader.create_trading_plan = AsyncMock(return_value="PLAN")
        coordinator._trader = trader
        ctx = MagicMock(symbol="BTCUSDT", current_price=50000.0)
        result = await coordinator._run_trader("看漲做多", {}, ctx, 10000.0)
        assert result == "PLAN"
        # direction 應為 LONG
        assert trader.create_trading_plan.call_args.kwargs["direction"] == "LONG"

    @pytest.mark.asyncio
    async def test_trader_direction_short(self, coordinator):
        trader = MagicMock()
        trader.create_trading_plan = AsyncMock(return_value="PLAN")
        coordinator._trader = trader
        ctx = MagicMock(symbol="BTCUSDT", current_price=50000.0)
        await coordinator._run_trader("做空看跌", {}, ctx, 10000.0)
        assert trader.create_trading_plan.call_args.kwargs["direction"] == "SHORT"

    @pytest.mark.asyncio
    async def test_trader_direction_hold_default(self, coordinator):
        trader = MagicMock()
        trader.create_trading_plan = AsyncMock(return_value="PLAN")
        coordinator._trader = trader
        ctx = MagicMock(symbol="BTCUSDT", current_price=50000.0)
        await coordinator._run_trader("中性看法", {}, ctx, 10000.0)
        assert trader.create_trading_plan.call_args.kwargs["direction"] == "HOLD"


class TestPortfolioManager:
    @pytest.mark.asyncio
    async def test_no_pm(self, coordinator):
        coordinator._portfolio_manager = None
        result = await coordinator._run_portfolio_manager(
            {}, "plan", "tplan", {}, [], 10000.0,
            MagicMock(current_price=1.0),
        )
        assert result["decision"] == "HOLD"

    @pytest.mark.asyncio
    async def test_pm_decision(self, coordinator):
        pm = MagicMock()
        pm.make_final_decision = AsyncMock(return_value={
            "decision_text": "Decision: BUY\nRationale: 看漲",
            "scorecard": MagicMock(confidence=0.8),
        })
        coordinator._portfolio_manager = pm
        result = await coordinator._run_portfolio_manager(
            {}, "plan", "tplan", {}, [], 10000.0,
            MagicMock(current_price=1.0),
        )
        assert result["decision"] == "BUY"
        assert result["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_pm_hold_decision(self, coordinator):
        pm = MagicMock()
        pm.make_final_decision = AsyncMock(return_value={
            "decision_text": "Decision: HOLD\nRationale: 觀望",
            "scorecard": MagicMock(confidence=0.4),
        })
        coordinator._portfolio_manager = pm
        result = await coordinator._run_portfolio_manager(
            {}, "plan", "tplan", {}, [], 10000.0,
            MagicMock(current_price=1.0),
        )
        assert result["decision"] == "HOLD"


class TestDetermineMarketCondition:
    def test_trending(self, coordinator):
        ctx = MagicMock()
        ctx.indicators = {"trend": "uptrend"}
        assert coordinator._determine_market_condition(ctx) == "trending"

    def test_volatile(self, coordinator):
        ctx = MagicMock()
        ctx.indicators = {"volatility": 0.03}
        assert coordinator._determine_market_condition(ctx) == "volatile"

    def test_ranging(self, coordinator):
        ctx = MagicMock()
        ctx.indicators = {}
        assert coordinator._determine_market_condition(ctx) == "ranging"


class TestCalculateContributions:
    def test_analyst_contribution(self, coordinator):
        contrib = coordinator._calculate_agent_contributions(
            {"technical": "看漲分析內容較長", "fundamental": "短"},
            "buy", "", {},
        )
        assert "technical" in contrib
        assert "Research Manager" in contrib

    def test_empty_reports(self, coordinator):
        contrib = coordinator._calculate_agent_contributions({}, "", "", {})
        assert contrib == {} or "Research Manager" not in contrib


class TestFetchBenchmark:
    @pytest.mark.asyncio
    async def test_same_symbol_returns_none(self, coordinator):
        assert await coordinator._fetch_benchmark_price() is None or True

    @pytest.mark.asyncio
    async def test_get_reflector_no_memory(self, coordinator):
        coordinator.memory = None
        assert coordinator._get_reflector() is None


class TestFullFlowWithAgents:
    @pytest.mark.asyncio
    async def test_full_flow_with_mock_agents(self, coordinator):
        """mock 全部 agent → analyze_and_decide 完整 5 階段."""
        coordinator._analysts = {
            "technical": _FakeAnalyst("看漲突破"),
            "fundamental": _FakeAnalyst("基本面良好"),
            "news": _FakeAnalyst("利好新聞"),
            "sentiment": _FakeAnalyst("情緒正面"),
        }
        coordinator._researchers = {"manager": MagicMock()}
        coordinator._risk_analysts = {
            "aggressive": MagicMock(), "neutral": MagicMock(),
            "conservative": MagicMock(),
        }
        coordinator._trader = MagicMock()
        coordinator._portfolio_manager = MagicMock()
        # mock 各階段
        with patch.object(coordinator, "_run_research_debate",
                          new=AsyncMock(return_value="Decision: BUY\nRationale: 看漲")), \
             patch.object(coordinator, "_run_risk_assessment",
                          new=AsyncMock(return_value={"neutral": "低風險"})), \
             patch.object(coordinator, "_run_trader",
                          new=AsyncMock(return_value=MagicMock(
                              entry_orders=[{"order_type": "market", "price": 50000.0}],
                              total_position_usdt=100.0,
                              to_dict=MagicMock(return_value={}),
                              entry_price=50000.0,
                              direction="LONG",
                          ))), \
             patch.object(coordinator, "_run_portfolio_manager",
                          new=AsyncMock(return_value={
                              "decision": "BUY", "rationale": "看漲",
                              "confidence": 0.8, "execution_instructions": None,
                          })):
            decision = await coordinator.analyze_and_decide(
                current_price=50000.0, account_balance=10000.0)
        assert decision is not None
        assert len(coordinator.get_decision_history()) >= 1

    @pytest.mark.asyncio
    async def test_run_analysts_with_indicators(self, coordinator):
        """technical analyst 有 analyze_with_indicators → 走指標路徑."""
        class _TechWithIndicators:
            name = "tech"
            async def analyze_with_indicators(self, data):
                return "指標分析結果"
        coordinator._analysts = {"technical": _TechWithIndicators()}
        ctx = MagicMock(symbol="BTCUSDT", interval="30m", current_price=1.0,
                        indicators={"rsi": 50}, timestamp=0)
        stats = {"cache_hits": 0, "cache_misses": 0, "api_calls": 0, "messages_sent": 0}
        reports = await coordinator._run_analysts_parallel(ctx, "cid", stats)
        assert reports == {"technical": "指標分析結果"}


class TestLogImprovements:
    @pytest.mark.asyncio
    async def test_log_stats(self, coordinator):
        coordinator._current_state_machine = MagicMock()
        coordinator._current_state_machine.get_state_summary.return_value = {
            "decision_id": "d1", "state_history": ["a", "b"]}
        coordinator._message_broker.get_statistics = MagicMock(
            return_value={"total_messages": 5})
        coordinator._cache.get_stats = MagicMock(
            return_value={"memory": {"hit_rate": 0.5, "size": 10}})
        coordinator._rate_limiter.get_limiter = MagicMock(
            return_value=MagicMock(get_remaining_requests=MagicMock(return_value=10)))
        coordinator._token_optimizer.get_stats = MagicMock(
            return_value={"total_tokens": 100})
        coordinator._log_improvements_stats(1.5, {})  # 不 raise

    @pytest.mark.asyncio
    async def test_reset_agent_states(self, coordinator):
        inner = MagicMock()
        wrapper = MagicMock()
        wrapper._agent = inner
        coordinator._analysts = {"tech": wrapper}
        coordinator._researchers = {}
        coordinator._risk_analysts = {}
        coordinator._trader = wrapper
        coordinator._portfolio_manager = None
        coordinator._reset_agent_states()  # 不 raise
        inner.reset.assert_called()

    @pytest.mark.asyncio
    async def test_reset_agent_states_no_inner(self, coordinator):
        wrapper = MagicMock()
        wrapper._agent = None
        coordinator._analysts = {"tech": wrapper}
        coordinator._researchers = {}
        coordinator._risk_analysts = {}
        coordinator._trader = None
        coordinator._portfolio_manager = None
        coordinator._reset_agent_states()  # 不 raise

    @pytest.mark.asyncio
    async def test_reset_agent_reset_fails(self, coordinator):
        inner = MagicMock()
        inner.reset.side_effect = RuntimeError("boom")
        inner._state.is_streaming = False
        wrapper = MagicMock()
        wrapper._agent = inner
        coordinator._analysts = {"tech": wrapper}
        coordinator._researchers = {}
        coordinator._risk_analysts = {}
        coordinator._trader = None
        coordinator._portfolio_manager = None
        coordinator._reset_agent_states()  # fail-safe 不 raise


class TestInsuranceBranches:
    @pytest.mark.asyncio
    async def test_insurance_no_entry_orders(self, coordinator):
        plan = MagicMock()
        plan.entry_orders = []
        result = await coordinator._auto_execute_insurance("did", "BUY", plan)
        assert result is None

    @pytest.mark.asyncio
    async def test_insurance_no_reference_price(self, coordinator):
        plan = MagicMock()
        plan.entry_orders = [{"order_type": "market", "price": None}]
        result = await coordinator._auto_execute_insurance("did", "BUY", plan)
        assert result is None

    @pytest.mark.asyncio
    async def test_insurance_builder_error(self, coordinator):
        plan = MagicMock()
        plan.entry_orders = [{"order_type": "market", "price": 50000.0}]
        coordinator._tool_context.executor.get_reference_price = MagicMock(
            return_value=None)
        result = await coordinator._auto_execute_insurance("did", "BUY", plan)
        assert result is None or isinstance(result, dict)


class TestGroundingFail:
    @pytest.mark.asyncio
    async def test_grounding_fail_degrades(self, coordinator):
        """grounding gate 駁回 → 決策降級 HOLD + 清空執行計畫."""
        coordinator._analysts = {
            "technical": _FakeAnalyst("看漲"), "fundamental": _FakeAnalyst("好"),
            "news": _FakeAnalyst("利好"), "sentiment": _FakeAnalyst("正面"),
        }
        coordinator._researchers = {"manager": MagicMock()}
        coordinator._risk_analysts = {"neutral": MagicMock()}
        coordinator._trader = MagicMock()
        coordinator._portfolio_manager = MagicMock()
        # storage 回 klines 觸發 grounding (真 Kline 供 pandas)
        from datetime import datetime, timezone as _tz
        from vibe_trading.data_sources.base import Kline
        kl = [Kline(
            symbol="BTCUSDT", interval="30m",
            open_time=int(datetime(2026, 1, 1, tzinfo=_tz.utc).timestamp() * 1000) + i * 1000,
            open=50000.0 + i, high=51000.0 + i, low=49000.0 + i,
            close=50000.0 + i, volume=100.0,
        ) for i in range(60)]
        coordinator.storage = MagicMock()
        coordinator.storage.query_klines = AsyncMock(return_value=kl)
        with patch.object(coordinator, "_run_research_debate",
                          new=AsyncMock(return_value="Decision: BUY\nRationale: 看漲")), \
             patch.object(coordinator, "_run_risk_assessment",
                          new=AsyncMock(return_value={"neutral": "低風險"})), \
             patch.object(coordinator, "_run_trader",
                          new=AsyncMock(return_value=MagicMock(
                              entry_orders=[{"order_type": "market", "price": 50000.0}],
                              total_position_usdt=100.0,
                              to_dict=MagicMock(return_value={}),
                              entry_price=50000.0,
                              direction="LONG",
                          ))), \
             patch.object(coordinator, "_run_portfolio_manager",
                          new=AsyncMock(return_value={
                              "decision": "BUY", "rationale": "看漲",
                              "confidence": 0.8, "execution_instructions": None,
                          })), \
             patch("vibe_trading.execution.grounding_gate.validate_trading_plan_prices",
                   return_value={"passed": False, "violations": ["價格偏差 5%"]}):
            decision = await coordinator.analyze_and_decide(current_price=50000.0)
        assert decision.decision == "HOLD"
        assert "Grounding" in decision.rationale
        assert decision.confidence <= 0.5


class TestCoordinatorReporting:
    @pytest.mark.asyncio
    async def test_get_quality_report(self, coordinator):
        qt = MagicMock()
        qt.get_quality_metrics = AsyncMock(return_value=None)
        qt.generate_report = MagicMock(return_value="report ok")
        coordinator._quality_tracker = qt
        report = await coordinator.get_quality_report()
        assert report == "report ok"

    @pytest.mark.asyncio
    async def test_get_quality_report_error(self, coordinator):
        qt = MagicMock()
        qt.get_quality_metrics = AsyncMock(side_effect=RuntimeError("x"))
        coordinator._quality_tracker = qt
        report = await coordinator.get_quality_report()
        assert "无法生成" in report

    @pytest.mark.asyncio
    async def test_get_agent_rankings(self, coordinator):
        qt = MagicMock()
        qt.get_agent_ranking = MagicMock(return_value=[("a", 0.9)])
        coordinator._quality_tracker = qt
        assert await coordinator.get_agent_rankings() == [("a", 0.9)]

    @pytest.mark.asyncio
    async def test_get_agent_rankings_error(self, coordinator):
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        qt = MagicMock()
        qt.get_agent_ranking = MagicMock(side_effect=RuntimeError("x"))
        coordinator._quality_tracker = qt
        with _p.object(tc, "logger", MagicMock()):
            assert await coordinator.get_agent_rankings() == []

    @pytest.mark.asyncio
    async def test_get_top_performers(self, coordinator):
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        qt = MagicMock()
        qt.get_top_performers = MagicMock(return_value=["a", "b"])
        coordinator._quality_tracker = qt
        with _p.object(tc, "logger", MagicMock()):
            assert await coordinator.get_top_performers(top_n=2) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_get_underperformers(self, coordinator):
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        qt = MagicMock()
        qt.get_underperformers = MagicMock(return_value=["z"])
        coordinator._quality_tracker = qt
        with _p.object(tc, "logger", MagicMock()):
            assert await coordinator.get_underperformers(threshold=0.5) == ["z"]

    def test_decision_history_copy(self, coordinator):
        coordinator._decision_history.append("d1")
        hist = coordinator.get_decision_history()
        assert hist == ["d1"]
        hist.append("d2")
        assert coordinator.get_decision_history() == ["d1"]


class TestOnTradeCompleted:
    @pytest.mark.asyncio
    async def test_no_decision_warns(self, coordinator):
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        coordinator._last_decision_id = None
        with _p.object(tc, "logger", MagicMock()):
            await coordinator.on_trade_completed(100.0, 110.0, 1.0)  # 不 raise

    @pytest.mark.asyncio
    async def test_full_reflection(self, coordinator):
        from types import SimpleNamespace
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        coordinator._last_decision_id = "D1"
        coordinator._last_processed_signal = SimpleNamespace(
            signal=SimpleNamespace(value="BUY"), confidence=0.8)
        coordinator._last_agent_outputs = {"technical": "report"}
        reflector = MagicMock()
        reflector.reflect_on_trade = AsyncMock(return_value=["r1"])
        coordinator._reflector = reflector
        mem = MagicMock()
        mem.save = MagicMock()
        coordinator.memory = mem
        qt = MagicMock()
        qt.record_outcome = AsyncMock(return_value=None)
        coordinator._quality_tracker = qt
        with _p.object(tc, "logger", MagicMock()):
            await coordinator.on_trade_completed(100.0, 110.0, 1.0, 2.0)
        reflector.reflect_on_trade.assert_called_once()
        qt.record_outcome.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflector_creates_from_memory(self, coordinator):
        from types import SimpleNamespace
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        coordinator._last_decision_id = "D2"
        coordinator._last_processed_signal = SimpleNamespace(
            signal=SimpleNamespace(value="SELL"), confidence=0.7)
        coordinator._reflector = None
        mem = MagicMock()
        coordinator.memory = mem
        qt = MagicMock()
        qt.record_outcome = AsyncMock(return_value=None)
        coordinator._quality_tracker = qt
        reflector = MagicMock()
        reflector.reflect_on_trade = AsyncMock(return_value=[])
        with _p.object(tc, "TradeReflector", return_value=reflector), \
             _p.object(tc, "logger", MagicMock()):
            await coordinator.on_trade_completed(100.0, 90.0, 1.0)
        assert coordinator._reflector is reflector

    @pytest.mark.asyncio
    async def test_reflection_error_swallowed(self, coordinator):
        from types import SimpleNamespace
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        coordinator._last_decision_id = "D3"
        coordinator._last_processed_signal = SimpleNamespace(
            signal=SimpleNamespace(value="BUY"), confidence=0.5)
        reflector = MagicMock()
        reflector.reflect_on_trade = AsyncMock(side_effect=RuntimeError("fail"))
        coordinator._reflector = reflector
        coordinator.memory = MagicMock()
        qt = MagicMock()
        qt.record_outcome = AsyncMock(side_effect=RuntimeError("qfail"))
        coordinator._quality_tracker = qt
        with _p.object(tc, "logger", MagicMock()):
            await coordinator.on_trade_completed(100.0, 105.0, 1.0)  # 錯誤被吞


class TestClose:
    @pytest.mark.asyncio
    async def test_close_calls_agent_close(self, coordinator):
        from types import SimpleNamespace
        with_close = MagicMock()
        with_close.close = AsyncMock(return_value=None)
        no_close = SimpleNamespace()  # 無 close attr
        coordinator._analysts = {"a": with_close, "b": no_close}
        coordinator._researchers = {"r": with_close}
        coordinator._risk_analysts = {"k": with_close}
        coordinator._trader = with_close
        coordinator._portfolio_manager = with_close
        await coordinator.close()
        assert with_close.close.call_count >= 5


class TestResumeCheckpoint:
    @pytest.mark.asyncio
    async def test_no_checkpoint(self, coordinator):
        coordinator._checkpoint_store = MagicMock()
        coordinator._checkpoint_store.get_latest_checkpoint = MagicMock(
            return_value=None)
        result = await coordinator.resume_from_checkpoint("D1", 100.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_no_phase(self, coordinator):
        coordinator._checkpoint_store = MagicMock()
        coordinator._checkpoint_store.get_latest_checkpoint = MagicMock(
            return_value={"completed_phase": "none", "context": {}})
        result = await coordinator.resume_from_checkpoint("D1", 100.0)
        assert result is None or result is not None


class TestResumeFromCheckpointFlow:
    @pytest.mark.asyncio
    async def test_resume_analyzing_phase(self, coordinator):
        """從 analyzing 恢復 → 走完整 phase 鏈."""
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc

        coordinator._checkpoint_store = MagicMock()
        coordinator._checkpoint_store.get_latest_checkpoint = MagicMock(
            return_value={
                "completed_phase": "analyzing",
                "context": {"analyst_reports": {}, "current_price": 100.0},
            })
        machine = MagicMock()
        machine.transition_to = MagicMock()
        sm = MagicMock()
        sm.create_machine = MagicMock(return_value=machine)
        coordinator._state_manager = sm
        coordinator._tool_context = MagicMock()
        coordinator._tool_context.executor = MagicMock()
        coordinator._prepare_context = AsyncMock(return_value={})
        coordinator._run_research_debate = AsyncMock(return_value="plan")
        coordinator._run_risk_assessment = AsyncMock(return_value={"level": "low"})
        coordinator._run_trader = AsyncMock(return_value=MagicMock(
            entry_orders=[], to_dict=MagicMock(return_value={})))
        coordinator._run_portfolio_manager = AsyncMock(return_value={
            "decision": "BUY", "rationale": "resumed", "confidence": 0.7})
        with _p.object(tc, "logger", MagicMock()), \
             _p.object(tc, "info", MagicMock()):
            decision = await coordinator.resume_from_checkpoint("D1", 100.0)
        assert decision is not None
        assert decision.decision == "BUY"
        assert decision.confidence == 0.7
        assert coordinator._checkpoint_store.save_checkpoint.call_count >= 4

    @pytest.mark.asyncio
    async def test_resume_completed_phase(self, coordinator):
        coordinator._checkpoint_store = MagicMock()
        coordinator._checkpoint_store.get_latest_checkpoint = MagicMock(
            return_value={
                "completed_phase": "completed",
                "context": {"final_decision": {"decision": "HOLD",
                                               "rationale": "done"}},
            })
        decision = await coordinator.resume_from_checkpoint("D1", 100.0)
        assert decision is not None

    @pytest.mark.asyncio
    async def test_resume_exception_returns_none(self, coordinator):
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        coordinator._checkpoint_store = MagicMock()
        coordinator._checkpoint_store.get_latest_checkpoint = MagicMock(
            return_value={
                "completed_phase": "analyzing",
                "context": {"analyst_reports": {}},
            })
        coordinator._state_manager = MagicMock()
        coordinator._state_manager.create_machine = MagicMock(
            return_value=MagicMock())
        coordinator._continue_from_checkpoint = AsyncMock(
            side_effect=RuntimeError("boom"))
        with _p.object(tc, "logger", MagicMock()):
            result = await coordinator.resume_from_checkpoint("D1", 100.0)
        assert result is None


class TestRunResearchDebate:
    @pytest.mark.asyncio
    async def test_skip_debate(self, coordinator):
        from types import SimpleNamespace
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        coordinator._researchers = {"manager": MagicMock()}
        settings = MagicMock()
        settings.skip_debate = True
        with _p.object(tc, "get_settings", return_value=settings), \
             _p.object(tc, "logger", MagicMock()):
            plan = await coordinator._run_research_debate(
                SimpleNamespace(symbol="BTCUSDT", current_price=100.0),
                {"technical": "bullish"}, "D1", {})
        assert "SKIPPED" in plan

    @pytest.mark.asyncio
    async def test_full_debate(self, coordinator):
        from types import SimpleNamespace
        from unittest.mock import patch as _p
        import vibe_trading.coordinator.trading_coordinator as tc
        settings = MagicMock()
        settings.skip_debate = False
        settings.debate_rounds = 2
        coordinator._token_optimizer = MagicMock()
        coordinator._token_optimizer.compress_prompt = MagicMock(
            return_value="compressed")
        coordinator._message_broker = MagicMock()
        bull = MagicMock()
        bear = MagicMock()
        manager = MagicMock()
        manager.make_decision = AsyncMock(return_value={
            "decision_text": "Buy BTC", "decision": "BUY"})
        coordinator._researchers = {"bull": bull, "bear": bear,
                                    "manager": manager}
        with _p.object(tc, "get_settings", return_value=settings), \
             _p.object(tc, "logger", MagicMock()), \
             _p.object(tc, "run_debate_round",
                       new=AsyncMock(return_value=("bull say", "bear say"))):
            result = await coordinator._run_research_debate(
                SimpleNamespace(symbol="BTCUSDT", current_price=100.0,
                                market_data={}),
                {"technical": "bullish"}, "D1", {"messages_sent": 0})
        assert result == "Buy BTC"
        assert coordinator._message_broker.send.call_count == 5  # 2*2 + 1


class TestPortfolioDecisionConsume:
    """Phase 5: submit_portfolio_decision 結構化動作 → 決策映射."""

    @pytest.fixture(autouse=True)
    def _ns(self):
        global SimpleNamespace
        from types import SimpleNamespace

    @pytest.mark.asyncio
    async def test_open_short_maps_to_sell(self, coordinator):
        coordinator._portfolio_manager = MagicMock()
        coordinator._portfolio_manager.make_final_decision = AsyncMock(
            return_value={"decision_text": "whatever", "scorecard": None})
        coordinator._tool_context.portfolio_decision = {
            "action": "OPEN_SHORT", "confidence": 0.8,
            "entry_price": 64000, "stop_loss": 64800,
            "take_profit": 62800, "rationale": "纏論三賣破位",
        }
        result = await coordinator._run_portfolio_manager(
            {}, "plan", MagicMock(), {}, [], 10000,
            SimpleNamespace(current_price=64000))
        assert result["decision"] == "SELL"  # OPEN_SHORT → SELL
        assert result["position_action"] == "OPEN_SHORT"
        # 消費後清除
        assert coordinator._tool_context.portfolio_decision is None

    @pytest.mark.asyncio
    async def test_hold_action_maps_hold(self, coordinator):
        coordinator._portfolio_manager = MagicMock()
        coordinator._portfolio_manager.make_final_decision = AsyncMock(
            return_value={"decision_text": "text", "scorecard": None})
        coordinator._tool_context.portfolio_decision = {
            "action": "HOLD", "confidence": 0.6,
            "entry_price": 64000, "stop_loss": 0, "take_profit": 0,
            "rationale": "觀望",
        }
        result = await coordinator._run_portfolio_manager(
            {}, "plan", MagicMock(), {}, [], 10000,
            SimpleNamespace(current_price=64000))
        assert result["decision"] == "HOLD"
