"""Tests for agent_replay helpers (Wave D — coverage 85% plan)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.backtest import agent_replay
from vibe_trading.backtest.agent_models import AgentReplayConfig
from vibe_trading.data_sources.kline_storage import Kline


class TestToKline:
    def test_builds_kline(self):
        k = agent_replay._to_kline("BTCUSDT", "30m", [1700000000000, 100, 105, 95, 102, 1000])
        assert k.symbol == "BTCUSDT"
        assert k.open == 100.0
        assert k.close == 102.0
        assert k.volume == 1000.0
        assert k.is_final is True
        assert k.taker_buy_base == 0.0

    def test_close_time_computed(self):
        k = agent_replay._to_kline("X", "30m", [1700000000000, 1, 2, 1, 1.5, 10])
        assert k.close_time == 1700000000000 + 30 * 60 * 1000 - 1


class TestAccountState:
    @pytest.mark.asyncio
    async def test_dict_balance(self):
        ex = MagicMock()
        ex.get_balance = AsyncMock(return_value={"USDT": {"available": 5000.0}})
        ex.get_positions = AsyncMock(return_value=[])
        bal, pos = await agent_replay._account_state(ex)
        assert bal == 5000.0
        assert pos == []

    @pytest.mark.asyncio
    async def test_float_balance(self):
        ex = MagicMock()
        ex.get_balance = AsyncMock(return_value={"USDT": 3000.0})
        ex.get_positions = AsyncMock(return_value=[])
        bal, _ = await agent_replay._account_state(ex)
        assert bal == 3000.0

    @pytest.mark.asyncio
    async def test_missing_balance_default(self):
        ex = MagicMock()
        ex.get_balance = AsyncMock(return_value={})
        ex.get_positions = AsyncMock(return_value=[])
        bal, _ = await agent_replay._account_state(ex)
        assert bal == 0.0

    @pytest.mark.asyncio
    async def test_positions_converted(self):
        ex = MagicMock()
        ex.get_balance = AsyncMock(return_value={"USDT": 10000.0})
        p = MagicMock()
        p.symbol = "BTCUSDT"
        p.position_side.value = "LONG"
        p.position_amount = 0.1
        p.entry_price = 48000.0
        p.mark_price = 50000.0
        p.unrealized_profit = 200.0
        p.leverage = 5
        ex.get_positions = AsyncMock(return_value=[p])
        _, pos = await agent_replay._account_state(ex)
        assert pos[0]["symbol"] == "BTCUSDT"
        assert pos[0]["position_side"] == "LONG"


class TestAssistantText:
    def test_read_text_content(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=[
            SimpleNamespace(role="user", content="hi"),
            SimpleNamespace(role="assistant", content=[]),
            SimpleNamespace(role="assistant", content=[]),
        ]))
        # content list 空 → ""
        assert agent_replay._read_last_assistant_text(agent) == ""

    def test_read_string_content(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=[
            SimpleNamespace(role="assistant", content="決策: BUY"),
        ]))
        assert agent_replay._read_last_assistant_text(agent) == "決策: BUY"

    def test_no_messages(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
        assert agent_replay._read_last_assistant_text(agent) == ""

    def test_no_state(self):
        assert agent_replay._read_last_assistant_text(object()) == ""


class TestInjectCachedResponse:
    def test_injects_message(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
        agent_replay._inject_cached_response(agent, "cached text")
        assert len(agent.state.messages) == 1
        assert agent.state.messages[0].role == "assistant"

    def test_no_messages_returns(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=None))
        agent_replay._inject_cached_response(agent, "text")  # 不 raise


class TestIterAgents:
    def test_iterates_all(self):
        coord = MagicMock()
        coord._analysts = {"tech": object()}
        coord._researchers = {"bull": object()}
        coord._risk_analysts = {"neutral": object()}
        coord._trader = object()
        coord._portfolio_manager = object()
        roles = [r for r, _ in agent_replay._iter_coordinator_agents(coord)]
        assert "analyst:tech" in roles
        assert "researcher:bull" in roles
        assert "risk:neutral" in roles
        assert "trader" in roles
        assert "portfolio_manager" in roles

    def test_empty_coordinator(self):
        coord = MagicMock()
        coord._analysts = {}
        coord._researchers = {}
        coord._risk_analysts = {}
        coord._trader = None
        coord._portfolio_manager = None
        assert list(agent_replay._iter_coordinator_agents(coord)) == []


class TestEstimateCost:
    @pytest.mark.asyncio
    async def test_ledger_used(self):
        cfg = AgentReplayConfig()
        with patch("vibe_trading.monitoring.usage_ledger.UsageLedger") as mock_ledger:
            ledger = MagicMock()
            ledger.get_summary = AsyncMock(return_value=MagicMock(
                total_requests=100, total_cost_usd=5.0))
            mock_ledger.return_value = ledger
            avg = await agent_replay._estimate_avg_cost_usd(cfg)
        assert avg == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_ledger_error_fallback(self):
        cfg = AgentReplayConfig()
        with patch("vibe_trading.monitoring.usage_ledger.UsageLedger",
                  side_effect=RuntimeError("down")):
            avg = await agent_replay._estimate_avg_cost_usd(cfg)
        assert avg == pytest.approx(0.0003)

    @pytest.mark.asyncio
    async def test_empty_summary_fallback(self):
        cfg = AgentReplayConfig()
        with patch("vibe_trading.monitoring.usage_ledger.UsageLedger") as mock_ledger:
            ledger = MagicMock()
            ledger.get_summary = AsyncMock(return_value=MagicMock(total_requests=0))
            mock_ledger.return_value = ledger
            avg = await agent_replay._estimate_avg_cost_usd(cfg)
        assert avg == pytest.approx(0.0003)


class TestConfirmRun:
    @pytest.mark.asyncio
    async def test_yes_flag(self):
        cfg = AgentReplayConfig(yes=True)
        assert await agent_replay._confirm_run(cfg, 10) is True

    @pytest.mark.asyncio
    async def test_input_yes(self):
        cfg = AgentReplayConfig(yes=False)
        with patch("builtins.input", return_value="y"), \
             patch.object(agent_replay, "_estimate_avg_cost_usd",
                          new=AsyncMock(return_value=0.0003)):
            assert await agent_replay._confirm_run(cfg, 10) is True

    @pytest.mark.asyncio
    async def test_input_no(self):
        cfg = AgentReplayConfig(yes=False)
        with patch("builtins.input", return_value="n"), \
             patch.object(agent_replay, "_estimate_avg_cost_usd",
                          new=AsyncMock(return_value=0.0003)):
            assert await agent_replay._confirm_run(cfg, 10) is False


class TestInstallCacheWrapper:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=[]))

        async def fake_prompt(prompt):
            return True

        agent.prompt = fake_prompt
        cache = MagicMock()
        cache.get = AsyncMock(return_value="serialized")
        with patch.object(agent_replay, "deserialize_response",
                          return_value="cached reply"):
            agent_replay.install_cache_wrapper(agent, "tech", cache, "model")
            ok = await agent.prompt("prompt text")
        assert ok is True
        assert agent.state.messages[-1].role == "assistant"

    @pytest.mark.asyncio
    async def test_cache_miss_then_put(self):
        agent = SimpleNamespace(state=SimpleNamespace(messages=[]))
        calls = []

        async def fake_prompt(prompt):
            calls.append(prompt)
            from pi_agent_core.types import TextContent
            agent.state.messages.append(SimpleNamespace(
                role="assistant", content=[TextContent(text="real reply")]))
            return True

        agent.prompt = fake_prompt
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.put = AsyncMock()
        with patch.object(agent_replay, "deserialize_response"), \
             patch.object(agent_replay, "serialize_response", return_value="ser"):
            agent_replay.install_cache_wrapper(agent, "tech", cache, "model")
            ok = await agent.prompt("prompt text")
        assert ok is True
        cache.put.assert_called_once()
        assert calls == ["prompt text"]
