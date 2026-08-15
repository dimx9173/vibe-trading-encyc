"""Tests for ParallelExecutor (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.coordinator.parallel_executor import (
    ExecutionResult,
    ParallelExecutor,
    SequentialExecutor,
)


class _FakeAgent:
    def __init__(self, name: str, result="ok", fail: bool = False, slow: bool = False):
        self.name = name
        self._result = result
        self._fail = fail
        self._slow = slow

    async def analyze(self, context):
        if self._fail:
            raise RuntimeError("agent down")
        if self._slow:
            import asyncio
            await asyncio.sleep(5)
        return self._result


class TestRunPhase1:
    @pytest.mark.asyncio
    async def test_all_success(self):
        ex = ParallelExecutor()
        summary = await ex.run_phase_1_analysts(
            [_FakeAgent("tech"), _FakeAgent("fund")], {}, timeout_per_agent=2.0)
        assert summary.total_agents == 2
        assert summary.successful == 2
        assert summary.failed == 0
        assert len(summary.results) == 2
        assert summary.results[0].success is True

    @pytest.mark.asyncio
    async def test_with_failure(self):
        ex = ParallelExecutor()
        summary = await ex.run_phase_1_analysts(
            [_FakeAgent("tech"), _FakeAgent("bad", fail=True)], {},
            timeout_per_agent=2.0)
        assert summary.successful == 1
        assert summary.failed == 1
        assert summary.results[1].success is False
        assert "agent down" in summary.results[1].error

    @pytest.mark.asyncio
    async def test_empty_analysts(self):
        ex = ParallelExecutor()
        summary = await ex.run_phase_1_analysts([], {}, timeout_per_agent=1.0)
        assert summary.total_agents == 0

    @pytest.mark.asyncio
    async def test_speedup_recorded(self):
        ex = ParallelExecutor()
        summary = await ex.run_phase_1_analysts(
            [_FakeAgent("a"), _FakeAgent("b")], {}, timeout_per_agent=1.0)
        assert summary.parallel_speedup > 0
        assert len(ex.execution_history) == 1


class TestRunAgentWithTimeout:
    @pytest.mark.asyncio
    async def test_analyze_method(self):
        ex = ParallelExecutor()
        agent = _FakeAgent("tech")
        result = await ex._run_agent_with_timeout(agent, "tech", {}, 1.0)
        assert result.success is True
        assert result.result == "ok"

    @pytest.mark.asyncio
    async def test_respond_method(self):
        ex = ParallelExecutor()
        agent = _FakeAgent("resp")

        async def respond(context):
            return "responded"

        agent.respond = respond
        result = await ex._run_agent_with_timeout(agent, "resp", {}, 1.0)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_assess_method(self):
        ex = ParallelExecutor()
        agent = _FakeAgent("assessor")

        async def assess(context):
            return "assessed"

        agent.assess = assess
        result = await ex._run_agent_with_timeout(agent, "assessor", {}, 1.0)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_method(self):
        ex = ParallelExecutor()
        agent = object()  # 無 analyze/respond/assess
        result = await ex._run_agent_with_timeout(agent, "none", {}, 1.0)
        assert result.success is False
        assert "no callable method" in result.error

    @pytest.mark.asyncio
    async def test_timeout(self):
        ex = ParallelExecutor()
        agent = _FakeAgent("slow", slow=True)
        result = await ex._run_agent_with_timeout(agent, "slow", {}, 0.1)
        assert result.success is False
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_exception(self):
        ex = ParallelExecutor()
        agent = _FakeAgent("bad", fail=True)
        result = await ex._run_agent_with_timeout(agent, "bad", {}, 1.0)
        assert result.success is False
        assert "agent down" in result.error


class TestRunFunctionWithTimeout:
    @pytest.mark.asyncio
    async def test_success(self):
        ex = ParallelExecutor()
        async def fn(context):
            return "done"
        result = await ex._run_function_with_timeout(fn, "task", {}, 1.0)
        assert result.success is True
        assert result.result == "done"

    @pytest.mark.asyncio
    async def test_timeout(self):
        ex = ParallelExecutor()
        async def fn(context):
            import asyncio
            await asyncio.sleep(5)
        result = await ex._run_function_with_timeout(fn, "task", {}, 0.1)
        assert result.success is False
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_exception(self):
        ex = ParallelExecutor()
        async def fn(context):
            raise ValueError("bad")
        result = await ex._run_function_with_timeout(fn, "task", {}, 1.0)
        assert result.success is False
        assert "bad" in result.error


class TestStats:
    def test_empty_stats(self):
        ex = ParallelExecutor()
        assert ex.get_performance_stats() == {}

    @pytest.mark.asyncio
    async def test_stats_after_run(self):
        ex = ParallelExecutor()
        await ex.run_phase_1_analysts([_FakeAgent("a")], {}, 1.0)
        stats = ex.get_performance_stats()
        assert stats["total_phases"] == 1
        assert stats["total_agents"] == 1
        assert stats["success_rate"] == 1.0

    def test_execution_result_dataclass(self):
        r = ExecutionResult(agent_name="a", success=True, result="x")
        assert r.agent_name == "a"
        assert r.error is None


class TestSequentialExecutor:
    @pytest.mark.asyncio
    async def test_run_sequential(self):
        ex = SequentialExecutor()
        summary = await ex.run_sequential(
            [_FakeAgent("a"), _FakeAgent("b")], {})
        assert summary.total_agents == 2
        assert summary.successful == 2
