"""Tests for LLMErrorHandler + BaseAnalystAgent + EmergencyHandler (Wave D)."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.agents.llm_error_handler import (
    LLMErrorHandler,
    LLMRetryConfig,
    StructuredOutputParser,
    get_llm_error_handler,
)


class TestLLMErrorHandler:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        h = LLMErrorHandler(config=LLMRetryConfig(max_retries=1, retry_delay=0.01))
        async def fn():
            return "ok"
        assert await h.execute_with_retry(fn) == "ok"

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        h = LLMErrorHandler(config=LLMRetryConfig(max_retries=2, retry_delay=0.01))
        calls = []

        async def fn():
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError("500 Internal server error")
            return "ok"

        assert await h.execute_with_retry(fn) == "ok"
        assert len(calls) == 2
        assert h.get_stats()["total_errors"] == 0  # 成功後重置

    @pytest.mark.asyncio
    async def test_fallback_used(self):
        h = LLMErrorHandler(config=LLMRetryConfig(max_retries=1, retry_delay=0.01))

        async def fn():
            raise RuntimeError("500")

        async def fallback():
            return "fallback"

        assert await h.execute_with_retry(fn, fallback_func=fallback) == "fallback"
        assert h.get_stats()["fallback_count"] == 1

    @pytest.mark.asyncio
    async def test_all_fail_raises(self):
        h = LLMErrorHandler(config=LLMRetryConfig(max_retries=1, retry_delay=0.01))

        async def fn():
            raise RuntimeError("500")

        with pytest.raises(RuntimeError):
            await h.execute_with_retry(fn)

    @pytest.mark.asyncio
    async def test_fallback_disabled(self):
        h = LLMErrorHandler(config=LLMRetryConfig(
            max_retries=0, retry_delay=0.01, fallback_enabled=False))

        async def fn():
            raise RuntimeError("500")

        async def fallback():
            return "fb"

        with pytest.raises(RuntimeError):
            await h.execute_with_retry(fn, fallback_func=fallback)

    @pytest.mark.asyncio
    async def test_fallback_also_fails(self):
        h = LLMErrorHandler(config=LLMRetryConfig(max_retries=0, retry_delay=0.01))

        async def fn():
            raise RuntimeError("500")

        async def fallback():
            raise RuntimeError("fb down")

        with pytest.raises(RuntimeError):
            await h.execute_with_retry(fn, fallback_func=fallback)

    def test_stats_reset(self):
        h = LLMErrorHandler()
        h._error_count = 5
        h._fallback_count = 2
        stats = h.get_stats()
        assert stats["total_errors"] == 5
        h.reset_stats()
        assert h.get_stats()["total_errors"] == 0


class TestStructuredOutputParser:
    @pytest.mark.asyncio
    async def test_parse_json(self):
        result = await StructuredOutputParser.parse_with_fallback(
            '{"action": "BUY"}', None)
        assert result == {"action": "BUY"}

    @pytest.mark.asyncio
    async def test_parse_with_schema(self):
        from pydantic import BaseModel
        class Schema(BaseModel):
            action: str
        result = await StructuredOutputParser.parse_with_fallback(
            '{"action": "BUY"}', Schema)
        assert result.action == "BUY"

    @pytest.mark.asyncio
    async def test_parse_failure_fallback(self):
        result = await StructuredOutputParser.parse_with_fallback(
            "not json", None, fallback_text="default")
        assert result["parsed"] is False
        assert result["text"] == "default"

    @pytest.mark.asyncio
    async def test_parse_failure_raw(self):
        result = await StructuredOutputParser.parse_with_fallback("bad", None)
        assert result["parsed"] is False
        assert result["text"] == "bad"

    def test_global_singleton(self):
        a = get_llm_error_handler()
        b = get_llm_error_handler()
        assert a is b


class TestBaseAnalyst:
    def _analyst(self, role: str):
        from vibe_trading.agents.analysts.base_analyst import BaseAnalystAgent
        from types import SimpleNamespace
        from vibe_trading.config.agent_config import AgentRole
        role_enum = {
            "technical_analyst": AgentRole.TECHNICAL_ANALYST,
            "fundamental_analyst": AgentRole.FUNDAMENTAL_ANALYST,
            "news_analyst": AgentRole.NEWS_ANALYST,
            "sentiment_analyst": AgentRole.SENTIMENT_ANALYST,
        }[role]
        cfg = SimpleNamespace(role=role_enum, name="test")
        a = BaseAnalystAgent.__new__(BaseAnalystAgent)
        a.config = cfg
        a._tool_context = SimpleNamespace(symbol="BTCUSDT")
        a._agent = None
        return a

    def test_prompt_builders(self):
        a = self._analyst("technical_analyst")
        prompt = a._build_prompt({"symbol": "BTCUSDT", "current_price": 50000})
        assert "BTCUSDT" in prompt

    def test_fundamental_prompt(self):
        a = self._analyst("fundamental_analyst")
        prompt = a._build_fundamental_prompt("BTCUSDT", {
            "funding_rate": {"funding_rate": 0.01},
            "long_short_ratio": {"long_short_ratio": 1.5},
            "open_interest": {"open_interest": 1000},
            "news": [{"title": "利好"}],
        })
        assert "BTCUSDT" in prompt

    def test_news_prompt(self):
        a = self._analyst("news_analyst")
        prompt = a._build_news_prompt("BTCUSDT", {
            "news": {"news": [{"title": "重大利好"}]},
        })
        assert "BTCUSDT" in prompt

    def test_sentiment_prompt(self):
        a = self._analyst("sentiment_analyst")
        prompt = a._build_sentiment_prompt("BTCUSDT", {
            "fear_greed": {"value": 60},
            "social_sentiment": {"sentiment_score": 0.5},
            "funding_rate": {"funding_rate": 0.01},
        })
        assert "BTCUSDT" in prompt


class TestEmergencyHandler:
    def test_emergency_action_to_dict(self):
        from vibe_trading.coordinator.emergency_handler import EmergencyAction
        from vibe_trading.agents.decision.emergency_agent import EmergencyDecision
        decision = EmergencyDecision(
            action="EXECUTE", decision_type="CLOSE_ALL",
            rationale="crash", confidence=0.9,
        )
        action = EmergencyAction(action="EXECUTED", decision=decision)
        d = action.to_dict()
        assert d["action"] == "EXECUTED"

    @pytest.mark.asyncio
    async def test_initialize(self):
        from vibe_trading.coordinator.emergency_handler import EmergencyHandler
        h = EmergencyHandler(
            thread_manager=MagicMock(), shared_state=MagicMock(),
            event_queue=MagicMock(), notifier=None,
        )
        await h.initialize(symbol="BTCUSDT")  # 不 raise
