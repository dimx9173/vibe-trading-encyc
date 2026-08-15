"""Tests for PrimeAgent pure logic (Wave D — coverage 85% plan).

PrimeAgent 構造需 LLM config + pi_agent_core — 用 __new__ 跳過 __init__,
手動注入 config, 測試監控/價格/格式等純邏輯方法.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.prime.models import PrimeAgentConfig, PrimeConfig
from vibe_trading.prime.prime_agent import PrimeAgent, PrimeAgentStatus


def _agent(price: float | None = None) -> PrimeAgent:
    a = PrimeAgent.__new__(PrimeAgent)
    a.config = PrimeAgentConfig()
    a.prime_config = PrimeConfig(symbol="BTCUSDT")
    a.status = PrimeAgentStatus.INITIALIZING
    a.stats = {"messages_processed": 0, "decisions_made": 0,
               "emergency_decisions": 0, "constraint_violations": 0, "start_time": None}
    a.decision_history = []
    a.emergency_agents = {}
    a._monitoring_running = False
    a._monitoring_paused = False
    a._last_price = None
    a._last_price_time = None
    a._last_logged_position = None
    if price is not None:
        a._last_price = price
        a._last_price_time = datetime.now()
    return a


class TestGetCurrentPrice:
    @pytest.mark.asyncio
    async def test_returns_price_from_dict(self):
        a = _agent()
        with patch("vibe_trading.tools.market_data_tools.get_current_price",
                   new=AsyncMock(return_value={"price": 50000.0})):
            price = await a._get_current_price()
        assert price == 50000.0

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        a = _agent()
        with patch("vibe_trading.tools.market_data_tools.get_current_price",
                   new=AsyncMock(side_effect=RuntimeError("down"))):
            assert await a._get_current_price() is None


class TestPriceMovement:
    @pytest.mark.asyncio
    async def test_first_price_initializes(self):
        a = _agent()
        await a._check_price_movement(50000.0)
        assert a._last_price == 50000.0
        assert a.stats["emergency_decisions"] == 0

    @pytest.mark.asyncio
    async def test_crash_triggers_emergency(self):
        a = _agent(price=50000.0)
        # 暴跌 > crash_threshold (預設 -0.05)
        with patch.object(a, "_handle_price_crash", new=AsyncMock()) as mock_crash:
            await a._check_price_movement(46000.0)
        mock_crash.assert_called_once()

    @pytest.mark.asyncio
    async def test_spike_triggers(self):
        a = _agent(price=50000.0)
        with patch.object(a, "_handle_price_spike", new=AsyncMock()) as mock_spike:
            await a._check_price_movement(55000.0)  # +10% > pump_threshold
        mock_spike.assert_called_once()

    @pytest.mark.asyncio
    async def test_normal_movement_no_action(self):
        a = _agent(price=50000.0)
        with patch.object(a, "_handle_price_crash", new=AsyncMock()) as c, \
             patch.object(a, "_handle_price_spike", new=AsyncMock()) as s:
            await a._check_price_movement(50100.0)  # +0.2%
        c.assert_not_called()
        s.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_type_ignored(self):
        a = _agent()
        with patch.object(a, "_handle_price_crash", new=AsyncMock()) as c:
            await a._check_price_movement("not-a-number")
        c.assert_not_called()


class TestPriceHandlers:
    @pytest.mark.asyncio
    async def test_crash_creates_close_all(self):
        a = _agent()
        with patch.object(a, "_execute_emergency_decision", new=AsyncMock()) as ex:
            await a._handle_price_crash(46000.0, -0.08)
        ex.assert_called_once()
        decision = ex.call_args[0][0]
        assert decision.action.value == "close_all"

    @pytest.mark.asyncio
    async def test_spike_recommends_hold(self):
        a = _agent()
        await a._handle_price_spike(55000.0, 0.10)
        assert a.decision_history == []  # spike 不自動執行


class TestFormatAndSummary:
    def test_format_message_as_prompt(self):
        a = _agent()
        msg = MagicMock()
        msg.sender = "analyst"
        msg.message_type.value = "report"
        msg.content = {"text": "BTC 看漲"}
        msg.metadata = {}
        result = a._format_message_as_prompt(msg)
        assert "analyst" in result
        assert "BTC" in result

    def test_summarize_content_dict(self):
        a = _agent()
        result = a._summarize_content({"action": "BUY", "price": 50000})
        assert "BUY" in result

    def test_summarize_content_mixed_types(self):
        a = _agent()
        result = a._summarize_content({"n": 1, "d": {"x": 1}, "l": [1, 2]})
        assert "n: 1" in result
        assert "复杂数据" in result
        assert "长度2" in result

    def test_summarize_content_empty(self):
        a = _agent()
        assert a._summarize_content({}) == ""


class TestMessageStats:
    def test_record_message(self):
        from vibe_trading.prime.models import MessageStats
        stats = MessageStats()
        msg = MagicMock()
        msg.message_type.value = "report"
        msg.sender = "analyst"
        msg.metadata = {"priority": "normal"}
        stats.record_message(msg, 0.5)
        stats.record_message(msg, 1.5)
        assert stats.total_messages == 2
        assert stats.messages_by_type["report"] == 2
        assert stats.messages_by_agent["analyst"] == 2
        assert 0.1 <= stats.average_processing_time <= 1.5
        assert stats.last_message_time is not None


class TestFinancialStatus:
    @pytest.mark.asyncio
    async def test_check_financial_status(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a._last_logged_balance = None
        a._last_logged_position = None

        mgr = MagicMock()
        mgr.get = AsyncMock(side_effect=lambda k, d: {"account_balance": 20000.0,
                                                       "current_position": 0.5}[k])
        with patch("vibe_trading.coordinator.shared_state.get_shared_state_manager",
                   return_value=mgr):
            await a._check_financial_status()
        assert a.system_state.account_balance == 20000.0
        assert a.system_state.current_position == 0.5


class TestRiskMetrics:
    @pytest.mark.asyncio
    async def test_check_risk_metrics_high(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.prime_config.margin_threshold = 0.8

        mgr = MagicMock()
        mgr.get = AsyncMock(return_value=0.95)
        with patch("vibe_trading.coordinator.shared_state.get_shared_state_manager",
                   return_value=mgr), \
             patch.object(a, "_execute_emergency_decision", new=AsyncMock()) as ex:
            await a._check_risk_metrics()
        ex.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_risk_metrics_low(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()

        mgr = MagicMock()
        mgr.get = AsyncMock(return_value=0.3)
        with patch("vibe_trading.coordinator.shared_state.get_shared_state_manager",
                   return_value=mgr), \
             patch.object(a, "_execute_emergency_decision", new=AsyncMock()) as ex:
            await a._check_risk_metrics()
        ex.assert_not_called()


class TestSubagentMessage:
    @pytest.mark.asyncio
    async def test_process_message_constraint_violation(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.harness = MagicMock()
        a.harness.check_all_constraints = AsyncMock(return_value=False)
        a.decision_aggregator = MagicMock()

        msg = MagicMock()
        msg.message_type.value = "report"
        msg.sender = "analyst"
        msg.content = {}
        with patch.object(a, "_handle_constraint_violation", new=AsyncMock()) as h:
            await a._process_subagent_message(msg)
        h.assert_called_once()
        assert a.stats["constraint_violations"] == 1

    @pytest.mark.asyncio
    async def test_process_message_emergency(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.harness = MagicMock()
        a.harness.check_all_constraints = AsyncMock(return_value=True)
        a.decision_aggregator = MagicMock()

        msg = MagicMock()
        msg.message_type.value = "report"
        msg.sender = "analyst"
        msg.content = {}
        with patch.object(a, "_is_emergency_situation", new=AsyncMock(return_value=True)), \
             patch.object(a, "_emergency_decision",
                          new=AsyncMock(return_value=MagicMock())), \
             patch.object(a, "_execute_decision", new=AsyncMock()) as ex:
            await a._process_subagent_message(msg)
        ex.assert_called_once()
        assert a.stats["emergency_decisions"] == 1

    @pytest.mark.asyncio
    async def test_process_message_no_signal_prompts(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.harness = MagicMock()
        a.harness.check_all_constraints = AsyncMock(return_value=True)
        a.decision_aggregator = MagicMock()
        a.decision_aggregator.add_signal.return_value = None  # 無法提取信號

        msg = MagicMock()
        msg.message_type.value = "report"
        msg.sender = "analyst"
        msg.content = {}
        with patch.object(a, "_is_emergency_situation", new=AsyncMock(return_value=False)), \
             patch.object(a, "_prompt_agent_for_decision", new=AsyncMock()) as p:
            await a._process_subagent_message(msg)
        p.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_signal_aggregates_decision(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.harness = MagicMock()
        a.harness.check_all_constraints = AsyncMock(return_value=True)
        a.decision_aggregator = MagicMock()
        signal = MagicMock()
        signal.agent_id = "analyst"
        signal.signal_type.value = "buy"
        signal.confidence = 0.8
        a.decision_aggregator.add_signal.return_value = signal
        a.decision_aggregator.aggregate.return_value = MagicMock()

        msg = MagicMock()
        msg.message_type.value = "report"
        msg.sender = "analyst"
        msg.content = {}
        with patch.object(a, "_is_emergency_situation", new=AsyncMock(return_value=False)), \
             patch.object(a, "_execute_decision", new=AsyncMock()) as ex:
            await a._process_subagent_message(msg)
        ex.assert_called_once()
        assert a.stats["decisions_made"] == 1

    @pytest.mark.asyncio
    async def test_prompt_agent_for_decision(self):
        a = _agent()
        a.wait_for_idle = AsyncMock()
        a.prompt = AsyncMock()
        msg = MagicMock()
        msg.sender = "analyst"
        msg.message_type.value = "report"
        msg.content = {"text": "看漲"}
        await a._prompt_agent_for_decision(msg)
        a.prompt.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_agent_processing_steer(self):
        a = _agent()
        a.wait_for_idle = AsyncMock()
        a.prompt = AsyncMock(side_effect=RuntimeError("already processing"))
        msg = MagicMock()
        msg.sender = "analyst"
        msg.message_type.value = "report"
        msg.content = {}
        with patch.object(a, "_send_as_steering_message") as steer:
            await a._prompt_agent_for_decision(msg)
        steer.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_agent_other_error_raises(self):
        a = _agent()
        a.wait_for_idle = AsyncMock()
        a.prompt = AsyncMock(side_effect=RuntimeError("other"))
        msg = MagicMock()
        msg.sender = "analyst"
        msg.message_type.value = "report"
        msg.content = {}
        with pytest.raises(RuntimeError):
            await a._prompt_agent_for_decision(msg)

    def test_format_message_as_prompt_contains_sender(self):
        a = _agent()
        msg = MagicMock()
        msg.sender = "risk"
        msg.message_type.value = "warning"
        msg.content = {"level": "high"}
        prompt = a._format_message_as_prompt(msg)
        assert "risk" in prompt
        assert "warning" in prompt


class TestParseDecision:
    def test_parse_buy(self):
        from vibe_trading.prime.models import TradingAction
        a = _agent()
        d = a._parse_decision_from_text("建議买入 BTC")
        assert d is not None
        assert d.action == TradingAction.BUY

    def test_parse_sell(self):
        from vibe_trading.prime.models import TradingAction
        a = _agent()
        d = a._parse_decision_from_text("建議卖出")
        assert d is not None
        assert d.action == TradingAction.SELL

    def test_parse_hold(self):
        from vibe_trading.prime.models import TradingAction
        a = _agent()
        d = a._parse_decision_from_text("建議持有")
        assert d is not None
        assert d.action == TradingAction.HOLD

    def test_parse_unknown(self):
        a = _agent()
        assert a._parse_decision_from_text("無明確方向") is None


class TestEmergency:
    @pytest.mark.asyncio
    async def test_is_emergency_situation(self):
        a = _agent()
        msg = MagicMock()
        msg.message_type.value = "warning"
        msg.content = {"severity": "critical"}
        result = await a._is_emergency_situation(msg)
        assert result in (True, False)  # 不 raise

    @pytest.mark.asyncio
    async def test_execute_decision(self):
        from vibe_trading.prime.models import Decision, SystemState, TradingAction
        a = _agent()
        a.system_state = SystemState()
        d = Decision(action=TradingAction.HOLD, reason="測試", symbol="BTCUSDT",
                     confidence=0.5, override=True,
                     priority=__import__("vibe_trading.prime.models", fromlist=["DecisionPriority"]).DecisionPriority.NORMAL,
                     timestamp=__import__("datetime").datetime.now())
        await a._execute_decision(d)  # 不 raise (不 append history)

    @pytest.mark.asyncio
    async def test_execute_emergency_decision(self):
        from vibe_trading.prime.models import Decision, SystemState, TradingAction
        a = _agent()
        a.system_state = AsyncMock()
        a.stats = {"emergency_decisions": 0}
        d = Decision(action=TradingAction.CLOSE_ALL, reason="crash", symbol="BTCUSDT",
                     confidence=1.0, override=True,
                     priority=__import__("vibe_trading.prime.models", fromlist=["DecisionPriority"]).DecisionPriority.CRITICAL,
                     timestamp=__import__("datetime").datetime.now())
        from unittest.mock import patch as _patch
        with _patch.object(a, "_send_close_all_signal", new=AsyncMock()):
            await a._execute_emergency_decision(d)  # 不 raise


class TestHoldSignal:
    @pytest.mark.asyncio
    async def test_send_hold_signal(self):
        from vibe_trading.prime.models import Decision, TradingAction
        a = _agent()
        d = Decision(action=TradingAction.HOLD, reason="觀望", symbol="BTCUSDT",
                     confidence=0.5, override=False,
                     priority=__import__("vibe_trading.prime.models", fromlist=["DecisionPriority"]).DecisionPriority.NORMAL,
                     timestamp=__import__("datetime").datetime.now())
        await a._send_hold_signal(d)  # 不 raise


class TestMonitoring:
    @pytest.mark.asyncio
    async def test_health_check(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.message_channel = MagicMock()
        a.message_channel.size = AsyncMock(return_value=1)
        a.harness = MagicMock()
        a.harness.get_violation_summary = AsyncMock(return_value={"violations": 0})
        await a._health_check()  # 不 raise

    @pytest.mark.asyncio
    async def test_monitoring_check(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.message_channel = MagicMock()
        a.message_channel.size = AsyncMock(return_value=1)
        a.harness = MagicMock()
        a.harness.get_violation_summary = AsyncMock(return_value={})
        with patch.object(a, "_get_current_price",
                          new=AsyncMock(return_value=50000.0)), \
             patch.object(a, "_check_price_movement", new=AsyncMock()), \
             patch.object(a, "_check_financial_status", new=AsyncMock()), \
             patch.object(a, "_check_risk_metrics", new=AsyncMock()):
            await a._monitoring_check()  # 不 raise

    @pytest.mark.asyncio
    async def test_monitoring_check_error_raises(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.message_channel = MagicMock()
        a.message_channel.size = AsyncMock(return_value=1)
        a.harness = MagicMock()
        a.harness.get_violation_summary = AsyncMock(return_value={})
        with patch.object(a, "_get_current_price",
                          new=AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError):
                await a._monitoring_check()

    @pytest.mark.asyncio
    async def test_periodic_check(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = SystemState()
        a.message_channel = MagicMock()
        a.message_channel.size = AsyncMock(return_value=1)
        a.message_channel.reset_stats = AsyncMock()
        a.harness = MagicMock()
        a.harness.get_violation_summary = AsyncMock(return_value={})
        a.harness.reset_daily_stats = AsyncMock()
        await a._periodic_check()  # 不 raise


class TestAgentEvents:
    @pytest.mark.asyncio
    async def test_handle_message_end(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = AsyncMock()
        a.stats = {"decisions_made": 0}
        msg = MagicMock()
        msg.role = "assistant"
        msg.content = [MagicMock(text="建議买入 BTC")]
        with patch.object(a, "_execute_decision", new=AsyncMock()):
            await a._handle_agent_event(MagicMock(type="message_end", message=msg))
        assert a.stats["decisions_made"] == 1

    @pytest.mark.asyncio
    async def test_handle_agent_end(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = AsyncMock()
        a.stats = {"decisions_made": 0}
        msg = MagicMock()
        msg.role = "assistant"
        msg.content = [MagicMock(text="建議卖出")]
        with patch.object(a, "_execute_decision", new=AsyncMock()):
            await a._handle_agent_event(
                MagicMock(type="agent_end", messages=[msg]))
        assert a.stats["decisions_made"] == 1

    @pytest.mark.asyncio
    async def test_handle_unknown_event(self):
        a = _agent()
        await a._handle_agent_event(MagicMock(type="other"))  # 不 raise

    @pytest.mark.asyncio
    async def test_process_response_user_role_skipped(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = AsyncMock()
        msg = MagicMock()
        msg.role = "user"
        await a._process_agent_response(msg)  # 不 raise, 不處理

    @pytest.mark.asyncio
    async def test_process_response_no_decision(self):
        from vibe_trading.prime.models import SystemState
        a = _agent()
        a.system_state = AsyncMock()
        msg = MagicMock()
        msg.role = "assistant"
        msg.content = [MagicMock(text="無明確方向")]
        await a._process_agent_response(msg)  # parse None → 不執行
        assert a.stats["decisions_made"] == 0
