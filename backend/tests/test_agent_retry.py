"""
Unit tests for Fix 1c: agent-level empty-response / LLM-error retry logic.

Covers BaseAnalystAgent.analyze(), TechnicalAnalystAgent (all 3 methods),
and ResearcherAgent.respond() — the silent `stop=error` + empty-content
path that produced UNKNOWN(0.30) bars on 2026-08-04 03:00-04:00.

Each agent should:
  - retry up to 3 times when the LLM returns an empty response
  - retry when agent state carries an error
  - return the response on the first non-empty result
  - raise RuntimeError after 3 consecutive failures (visible failure,
    instead of a silent empty report)
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from pi_ai import AssistantMessage, TextContent

from vibe_trading.agents.analysts.base_analyst import BaseAnalystAgent
from vibe_trading.agents.analysts.technical_analyst import TechnicalAnalystAgent
from vibe_trading.agents.researchers.researcher_agents import ResearcherAgent
from vibe_trading.config.agent_config import AgentConfig, AgentRole

# Silence the 1s/2s backoff sleeps between retries.
_SLEEP_PATCH = patch("asyncio.sleep", new=AsyncMock(return_value=None))


class FakeState:
    def __init__(self, error=None):
        self.messages = []
        # 真实 AgentState 的字段是 error_message（state.error 不存在）
        self.error_message = error


class FakeAgent:
    """Fake pi_agent_core Agent: each prompt() call pops the next response."""

    def __init__(self, responses, error=None):
        self._responses = list(responses)
        self.state = FakeState(error=error)
        self.prompt_calls = 0

    def reset(self):
        """P1: 重試時重置 state（清 messages）。"""
        self.state.messages = []
        self.state.error_message = None

    async def prompt(self, prompt):
        self.prompt_calls += 1
        if self._responses:
            content = self._responses.pop(0)
            self.state.messages.append(AssistantMessage(role="assistant", content=content))


# ---------------------------------------------------------------------------
# BaseAnalystAgent.analyze()
# ---------------------------------------------------------------------------


def make_news_analyst(fake_agent) -> BaseAnalystAgent:
    config = AgentConfig(name="News Analyst", role=AgentRole.NEWS_ANALYST)
    analyst = BaseAnalystAgent(config)
    analyst._agent = fake_agent
    analyst._tool_context = SimpleNamespace(symbol="BTCUSDT", interval="30m")
    return analyst


async def test_analyze_returns_content_on_success():
    fake = FakeAgent(responses=[[TextContent(text="Good analysis")]])
    analyst = make_news_analyst(fake)
    with _SLEEP_PATCH:
        result = await analyst.analyze({})
    assert result == "Good analysis"
    assert fake.prompt_calls == 1


async def test_analyze_retries_on_empty_then_raises():
    fake = FakeAgent(responses=[[], [], []])
    analyst = make_news_analyst(fake)
    with _SLEEP_PATCH:
        with pytest.raises(RuntimeError, match="連續 3 次失敗"):
            await analyst.analyze({})
    assert fake.prompt_calls == 3  # exactly max_attempts


async def test_analyze_recovers_after_empty():
    fake = FakeAgent(responses=[[], [TextContent(text="Recovered report")]])
    analyst = make_news_analyst(fake)
    with _SLEEP_PATCH:
        result = await analyst.analyze({})
    assert result == "Recovered report"
    assert fake.prompt_calls == 2


async def test_analyze_retries_on_state_error_then_raises():
    fake = FakeAgent(responses=[[TextContent(text="partial")]], error="LLM stream failed")
    analyst = make_news_analyst(fake)
    with _SLEEP_PATCH:
        with pytest.raises(RuntimeError, match="LLM stream failed"):
            await analyst.analyze({})
    assert fake.prompt_calls == 3


async def test_analyze_joins_multiple_text_blocks():
    fake = FakeAgent(responses=[[TextContent(text="A"), TextContent(text="B")]])
    analyst = make_news_analyst(fake)
    with _SLEEP_PATCH:
        result = await analyst.analyze({})
    assert result == "AB"


# ---------------------------------------------------------------------------
# TechnicalAnalystAgent — analyze() / analyze_with_tools() / analyze_with_indicators()
# ---------------------------------------------------------------------------


def make_technical(fake_agent) -> TechnicalAnalystAgent:
    analyst = TechnicalAnalystAgent()
    analyst._agent = fake_agent
    analyst._tool_context = SimpleNamespace(symbol="BTCUSDT", interval="30m")
    return analyst


async def test_technical_analyze_retries_then_raises():
    fake = FakeAgent(responses=[[], [], []])
    analyst = make_technical(fake)
    with _SLEEP_PATCH:
        with pytest.raises(RuntimeError, match="連續 3 次失敗"):
            await analyst.analyze({"current_price": 63000})
    assert fake.prompt_calls == 3


async def test_technical_analyze_with_tools_retries_then_raises():
    fake = FakeAgent(responses=[[], [], []])
    analyst = make_technical(fake)
    with _SLEEP_PATCH:
        with pytest.raises(RuntimeError, match="連續 3 次失敗"):
            await analyst.analyze_with_tools()
    assert fake.prompt_calls == 3


async def test_technical_analyze_with_indicators_retries_then_raises():
    fake = FakeAgent(responses=[[], [], []])
    analyst = make_technical(fake)
    with _SLEEP_PATCH:
        with pytest.raises(RuntimeError, match="連續 3 次失敗"):
            await analyst.analyze_with_indicators({"indicators": {}, "current_price": 63000})
    assert fake.prompt_calls == 3


async def test_technical_analyze_with_indicators_recovers():
    fake = FakeAgent(responses=[[], [TextContent(text="TA report")]])
    analyst = make_technical(fake)
    with _SLEEP_PATCH:
        result = await analyst.analyze_with_indicators({"indicators": {}, "current_price": 63000})
    assert result == "TA report"
    assert fake.prompt_calls == 2


# ---------------------------------------------------------------------------
# ResearcherAgent.respond()  (Bull/Bear debate)
# ---------------------------------------------------------------------------


def make_researcher(fake_agent) -> ResearcherAgent:
    config = AgentConfig(name="Bull Researcher", role=AgentRole.BULL_RESEARCHER)
    researcher = ResearcherAgent(config, system_prompt="test prompt")
    researcher._agent = fake_agent
    researcher._tool_context = SimpleNamespace(symbol="BTCUSDT")
    return researcher


async def test_respond_retries_then_raises():
    fake = FakeAgent(responses=[[], [], []])
    researcher = make_researcher(fake)
    with _SLEEP_PATCH:
        with pytest.raises(RuntimeError, match="連續 3 次失敗"):
            await researcher.respond("context", extract_arguments=False)
    assert fake.prompt_calls == 3


async def test_respond_returns_content_on_success():
    fake = FakeAgent(responses=[[TextContent(text="Bull argument")]])
    researcher = make_researcher(fake)
    with _SLEEP_PATCH:
        result = await researcher.respond("context", extract_arguments=False)
    assert result == "Bull argument"
    assert fake.prompt_calls == 1


async def test_respond_recovers_after_empty():
    fake = FakeAgent(responses=[[], [TextContent(text="Bear argument")]])
    researcher = make_researcher(fake)
    with _SLEEP_PATCH:
        result = await researcher.respond("context", extract_arguments=False)
    assert result == "Bear argument"
    assert fake.prompt_calls == 2
