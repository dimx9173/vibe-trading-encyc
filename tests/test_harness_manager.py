"""Tests for HarnessManager — Wave D103."""
from datetime import datetime

import pytest

from vibe_trading.agents.messaging import AgentMessage, MessageType
from vibe_trading.prime.harness_manager import HarnessManager
from vibe_trading.prime.models import HarnessConfig


def _msg(content, msg_type=MessageType.INFO):
    return AgentMessage(
        message_id="m1", correlation_id="c1",
        sender="analyst", receiver="prime",
        message_type=msg_type, content=content,
        timestamp=datetime.now(),
    )


class TestHarnessInit:
    def test_init_all_enabled(self):
        hm = HarnessManager(HarnessConfig())
        assert set(hm.constraints) == {"safety", "operational", "behavioral", "resource"}

    def test_init_all_disabled(self):
        hm = HarnessManager(HarnessConfig(
            enable_safety_constraint=False, enable_operational_constraint=False,
            enable_behavioral_constraint=False, enable_resource_constraint=False))
        assert hm.constraints == {}


class TestCheckAll:
    @pytest.mark.asyncio
    async def test_pass(self):
        hm = HarnessManager(HarnessConfig())
        r = await hm.check_all_constraints(_msg({"trade_amount": 100}))
        assert r is True

    @pytest.mark.asyncio
    async def test_block_on_violation(self):
        hm = HarnessManager(HarnessConfig(violation_action="block"))
        r = await hm.check_all_constraints(_msg({"trade_amount": 999999}))
        assert r is False

    @pytest.mark.asyncio
    async def test_warn_continues(self):
        hm = HarnessManager(HarnessConfig(violation_action="warn"))
        r = await hm.check_all_constraints(_msg({"trade_amount": 999999}))
        assert r is True  # warn → 繼續

    @pytest.mark.asyncio
    async def test_log_continues(self):
        hm = HarnessManager(HarnessConfig(violation_action="log"))
        r = await hm.check_all_constraints(_msg({"trade_amount": 999999}))
        assert r is True


class TestCheckSingle:
    @pytest.mark.asyncio
    async def test_unknown_constraint(self):
        hm = HarnessManager(HarnessConfig())
        result = await hm.check_constraint("nope", _msg({}))
        assert result.passed is False
        assert "约束不存在" in result.reason

    @pytest.mark.asyncio
    async def test_known_constraint(self):
        hm = HarnessManager(HarnessConfig())
        result = await hm.check_constraint("safety", _msg({}))
        assert result.passed is True


class TestStatus:
    @pytest.mark.asyncio
    async def test_get_constraint_status_ok(self):
        hm = HarnessManager(HarnessConfig())
        s = await hm.get_constraint_status("safety")
        assert s.name == "safety_constraint"

    @pytest.mark.asyncio
    async def test_get_constraint_status_missing(self):
        hm = HarnessManager(HarnessConfig())
        with pytest.raises(ValueError):
            await hm.get_constraint_status("nope")

    @pytest.mark.asyncio
    async def test_get_all_statuses(self):
        hm = HarnessManager(HarnessConfig())
        statuses = await hm.get_all_constraint_statuses()
        assert len(statuses) == 4

    def test_get_constraint(self):
        hm = HarnessManager(HarnessConfig())
        assert hm.get_constraint("safety") is not None

    def test_get_constraint_missing(self):
        hm = HarnessManager(HarnessConfig())
        with pytest.raises(ValueError):
            hm.get_constraint("nope")


class TestMisc:
    def test_update_safety_state(self):
        hm = HarnessManager(HarnessConfig())
        hm.update_safety_state(total_position=100, account_balance=10000,
                               margin_ratio=0.5)
        c = hm.constraints["safety"]
        assert c._current_total_position == 100
        assert c._current_margin_ratio == 0.5

    def test_update_safety_state_no_safety(self):
        hm = HarnessManager(HarnessConfig(enable_safety_constraint=False))
        hm.update_safety_state(total_position=100)  # 不 crash

    def test_reset_daily_stats(self):
        hm = HarnessManager(HarnessConfig())
        hm.constraints["safety"].violations_today = 5
        hm.reset_daily_stats()
        assert hm.constraints["safety"].violations_today == 0

    @pytest.mark.asyncio
    async def test_get_violation_summary(self):
        hm = HarnessManager(HarnessConfig())
        hm.constraints["safety"].violations_today = 3
        summary = await hm.get_violation_summary()
        assert summary["safety"] == 3

    def test_enable_disable(self):
        hm = HarnessManager(HarnessConfig())
        hm.disable_constraint("safety")
        assert hm.is_constraint_enabled("safety") is False
        hm.enable_constraint("safety")
        assert hm.is_constraint_enabled("safety") is True

    def test_disable_unknown_noop(self):
        hm = HarnessManager(HarnessConfig())
        hm.disable_constraint("nope")  # 不 crash
        hm.enable_constraint("nope")  # 不 crash

    def test_is_enabled_unknown(self):
        hm = HarnessManager(HarnessConfig())
        assert hm.is_constraint_enabled("nope") is False
