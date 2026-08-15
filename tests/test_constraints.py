"""Tests for Prime constraints (safety/operational/resource) — Wave D102."""
from datetime import datetime, timedelta

import pytest

from vibe_trading.agents.messaging import AgentMessage, MessageType
from vibe_trading.prime.constraints.operational import OperationalConstraint
from vibe_trading.prime.constraints.resource import ResourceConstraint
from vibe_trading.prime.constraints.safety import SafetyConstraint


def _msg(content, msg_type=MessageType.INFO):
    return AgentMessage(
        message_id="m1", correlation_id="c1",
        sender="analyst", receiver="prime",
        message_type=msg_type, content=content,
        timestamp=datetime.now(),
    )


class TestSafetyConstraint:
    @pytest.mark.asyncio
    async def test_pass(self):
        c = SafetyConstraint(max_single_trade=1000, max_total_position=0.3,
                             max_leverage=5, margin_threshold=0.8)
        r = await c.check(_msg({"trade_amount": 100, "position_change": 0.05,
                                "leverage": 3}))
        assert r.passed

    @pytest.mark.asyncio
    async def test_trade_amount_over(self):
        c = SafetyConstraint(max_single_trade=1000)
        r = await c.check(_msg({"trade_amount": 5000}))
        assert not r.passed
        assert "超限" in r.reason

    @pytest.mark.asyncio
    async def test_position_over(self):
        c = SafetyConstraint(max_single_trade=1000, max_total_position=0.3)
        c.update_state(total_position=5000, account_balance=10000)
        r = await c.check(_msg({"position_change": 0.5}))
        assert not r.passed
        assert "总仓位超限" in r.reason

    @pytest.mark.asyncio
    async def test_leverage_over(self):
        c = SafetyConstraint(max_leverage=5)
        r = await c.check(_msg({"leverage": 10}))
        assert not r.passed
        assert "杠杆超限" in r.reason

    @pytest.mark.asyncio
    async def test_margin_insufficient(self):
        c = SafetyConstraint(margin_threshold=0.8)
        c.update_state(margin_ratio=0.9)
        r = await c.check(_msg({}))
        assert not r.passed
        assert "保证金不足" in r.reason

    def test_update_state_partial(self):
        c = SafetyConstraint()
        c.update_state(total_position=1.0)
        assert c._current_total_position == 1.0
        assert c._account_balance == 10000.0  # 未動


class TestOperationalConstraint:
    @pytest.mark.asyncio
    async def test_pass(self):
        c = OperationalConstraint(min_trade_interval=60, max_direction_changes=3,
                                  max_daily_trades=20)
        r = await c.check(_msg({"trade_action": "buy", "direction": "long"}))
        assert r.passed
        assert c._daily_trade_count == 1

    @pytest.mark.asyncio
    async def test_frequency_too_high(self):
        c = OperationalConstraint(min_trade_interval=60)
        c._last_trade_time = datetime.now() - timedelta(seconds=5)
        r = await c.check(_msg({"trade_action": "buy"}))
        assert not r.passed
        assert "交易频率过高" in r.reason

    @pytest.mark.asyncio
    async def test_direction_changes_too_many(self):
        c = OperationalConstraint(max_direction_changes=2)
        c._trade_directions.extend(["long", "short", "long", "short"])
        r = await c.check(_msg({"direction": "long"}))
        assert not r.passed
        assert "方向改变过于频繁" in r.reason

    @pytest.mark.asyncio
    async def test_daily_limit(self):
        c = OperationalConstraint(max_daily_trades=2)
        c._daily_trade_count = 2
        r = await c.check(_msg({"trade_action": "buy"}))
        assert not r.passed
        assert "每日交易次数已达上限" in r.reason

    @pytest.mark.asyncio
    async def test_reset_daily(self):
        c = OperationalConstraint()
        c._daily_trade_count = 5
        c._last_reset_date = datetime.now().date() - timedelta(days=1)
        c._reset_daily_if_needed()
        assert c._daily_trade_count == 0

    @pytest.mark.asyncio
    async def test_get_status(self):
        c = OperationalConstraint(max_daily_trades=10)
        c._daily_trade_count = 10
        s = await c.get_status()
        assert s.status == "error"
        c._daily_trade_count = 8
        s = await c.get_status()
        assert s.status == "warning"
        c._daily_trade_count = 1
        s = await c.get_status()
        assert s.status == "ok"


class TestResourceConstraint:
    @pytest.mark.asyncio
    async def test_pass(self):
        c = ResourceConstraint(max_llm_calls_per_day=1000, max_daily_cost=10.0,
                               max_tokens_per_message=8000, max_calls_per_minute=60)
        r = await c.check(_msg({"llm_call": True, "estimated_cost": 0.1,
                                "token_count": 1000}))
        assert r.passed
        assert c._llm_calls_today == 1

    @pytest.mark.asyncio
    async def test_per_minute_limit(self):
        c = ResourceConstraint(max_calls_per_minute=2)
        c._calls_in_last_minute = [datetime.now(), datetime.now()]
        r = await c.check(_msg({"llm_call": True}))
        assert not r.passed
        assert "调用频率过高" in r.reason

    @pytest.mark.asyncio
    async def test_daily_limit(self):
        c = ResourceConstraint(max_llm_calls_per_day=3)
        c._llm_calls_today = 3
        r = await c.check(_msg({"llm_call": True}))
        assert not r.passed
        assert "每日LLM调用次数已达上限" in r.reason

    @pytest.mark.asyncio
    async def test_cost_over(self):
        c = ResourceConstraint(max_daily_cost=10.0)
        c._cost_today = 9.5
        r = await c.check(_msg({"estimated_cost": 1.0}))
        assert not r.passed
        assert "每日成本超限" in r.reason

    @pytest.mark.asyncio
    async def test_token_over(self):
        c = ResourceConstraint(max_tokens_per_message=8000)
        r = await c.check(_msg({"token_count": 9000}))
        assert not r.passed
        assert "Token数量超限" in r.reason

    @pytest.mark.asyncio
    async def test_cleanup_old_calls(self):
        c = ResourceConstraint()
        c._calls_in_last_minute = [
            datetime.now() - timedelta(minutes=5), datetime.now(),
        ]
        await c._cleanup_old_calls()
        assert len(c._calls_in_last_minute) == 1

    @pytest.mark.asyncio
    async def test_record_llm_call(self):
        c = ResourceConstraint()
        c.record_llm_call(tokens=100, cost=0.01)
        assert c._llm_calls_today == 1
        assert c._cost_today == 0.01

    @pytest.mark.asyncio
    async def test_get_status(self):
        c = ResourceConstraint(max_llm_calls_per_day=100, max_daily_cost=10)
        c._llm_calls_today = 95
        s = await c.get_status()
        assert s.status == "error"
        c._llm_calls_today = 75
        s = await c.get_status()
        assert s.status == "warning"
        c._llm_calls_today = 10
        s = await c.get_status()
        assert s.status == "ok"

    @pytest.mark.asyncio
    async def test_reset_daily(self):
        c = ResourceConstraint()
        c._llm_calls_today = 10
        c._cost_today = 5.0
        c._last_reset_date = datetime.now().date() - timedelta(days=1)
        c._reset_daily_if_needed()
        assert c._llm_calls_today == 0
        assert c._cost_today == 0.0
