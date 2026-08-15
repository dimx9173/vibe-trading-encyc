"""Tests for shared_state + message_channel (Wave D — coverage 85% plan)."""
import asyncio
from datetime import datetime, timedelta

from unittest.mock import AsyncMock, MagicMock

import pytest

from vibe_trading.coordinator.shared_state import SharedStateManager
from vibe_trading.prime.message_channel import MessageChannel, PriorityMessage


# ===================== SharedStateManager =====================

@pytest.fixture
def state():
    return SharedStateManager()


class TestSharedState:
    @pytest.mark.asyncio
    async def test_get_default(self, state):
        assert await state.get("missing", "dflt") == "dflt"

    @pytest.mark.asyncio
    async def test_set_get(self, state):
        assert await state.set("key", 42) is True
        assert await state.get("key") == 42

    @pytest.mark.asyncio
    async def test_get_expired_returns_default(self):
        s = SharedStateManager()
        await s.set("k", 1, ttl_seconds=-1)  # 立即過期
        assert await s.get("k", "gone") == "gone"

    @pytest.mark.asyncio
    async def test_delete(self, state):
        await state.set("k", 1)
        assert await state.delete("k") is True
        assert await state.delete("k") is False  # 不存在

    @pytest.mark.asyncio
    async def test_exists(self, state):
        await state.set("k", 1)
        assert await state.exists("k") is True
        assert await state.exists("nope") is False

    @pytest.mark.asyncio
    async def test_get_all(self, state):
        await state.set("a", 1)
        await state.set("b", 2)
        all_v = await state.get_all()
        assert all_v == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_clear(self, state):
        await state.set("a", 1)
        await state.clear()
        assert await state.get_all() == {}

    @pytest.mark.asyncio
    async def test_subscribe_notified(self, state):
        events = []
        state.subscribe("k", lambda ev: events.append((ev.key, ev.old_value, ev.new_value)))
        await state.set("k", 10)
        await state.set("k", 20)
        assert events == [("k", None, 10), ("k", 10, 20)]

    @pytest.mark.asyncio
    async def test_subscribe_same_value_no_notify(self, state):
        events = []
        state.subscribe("k", lambda ev: events.append(ev.new_value))
        await state.set("k", 5)
        await state.set("k", 5)  # 同值 → 不通知
        assert events == [5]

    @pytest.mark.asyncio
    async def test_unsubscribe(self, state):
        events = []

        def cb(ev):
            events.append(ev.new_value)

        state.subscribe("k", cb)
        await state.set("k", 1)
        state.unsubscribe("k", cb)
        await state.set("k", 2)
        assert events == [1]

    @pytest.mark.asyncio
    async def test_history(self):
        s = SharedStateManager(enable_history=True)
        await s.set("k", 1)
        await s.set("k", 2)
        hist = await s.get_history("k")
        assert len(hist) == 2
        assert hist[-1]["value"] == 2

    @pytest.mark.asyncio
    async def test_history_disabled(self, state):
        assert await state.get_history("k") == []

    @pytest.mark.asyncio
    async def test_statistics(self, state):
        await state.set("a", 1)
        stats = await state.get_statistics()
        assert stats["total_keys"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_task(self, state):
        await state.start_cleanup_task(interval_seconds=3600)
        await state.stop_cleanup_task()
        assert state._cleanup_task is None

    def test_repr(self, state):
        assert "SharedStateManager" in repr(state)

    @pytest.mark.asyncio
    async def test_state_entry_expired(self):
        from vibe_trading.coordinator.shared_state import StateEntry
        e = StateEntry(value=1, expires_at=datetime.now() - timedelta(seconds=1))
        assert e.is_expired() is True
        e2 = StateEntry(value=1, expires_at=None)
        assert e2.is_expired() is False


# ===================== MessageChannel =====================

def _msg(sender: str = "analyst", mtype=None, mid: str = "m1"):
    from unittest.mock import MagicMock
    from vibe_trading.agents.messaging import MessageType
    m = MagicMock()
    m.sender = sender
    m.message_type = mtype or MessageType.ANALYSIS_REPORT
    m.message_id = mid
    m.content = {}
    m.metadata = {}
    return m


@pytest.fixture
def channel():
    return MessageChannel(maxsize=10, enable_dedup=False)


class TestMessageChannel:
    @pytest.mark.asyncio
    async def test_put_get_roundtrip(self, channel):
        msg = _msg()
        assert await channel.put(msg) is True
        got = await channel.get(timeout=1.0)
        assert got is msg

    @pytest.mark.asyncio
    async def test_get_timeout_returns_none(self, channel):
        assert await channel.get(timeout=0.1) is None

    @pytest.mark.asyncio
    async def test_dedup(self):
        ch = MessageChannel(maxsize=10, enable_dedup=True)
        msg = _msg(mid="dup")
        assert await ch.put(msg) is True
        assert await ch.put(msg) is False  # 重複被丟棄
        got = await ch.get(timeout=0.5)
        assert got is msg

    @pytest.mark.asyncio
    async def test_priority_order(self, channel):
        low = _msg(mid="low")
        high = _msg(mid="high")
        from vibe_trading.prime.models import MessagePriority
        await channel.put(low, priority=MessagePriority.NORMAL)
        await channel.put(high, priority=MessagePriority.HIGH)
        first = await channel.get(timeout=1.0)
        assert first is high  # 高優先級先出

    @pytest.mark.asyncio
    async def test_put_semaphore_released_on_get(self):
        ch = MessageChannel(maxsize=2, enable_dedup=False)
        assert await ch.put(_msg(mid="a")) is True
        assert await ch.put(_msg(mid="b")) is True  # maxsize=2 允許
        got1 = await ch.get(timeout=1.0)
        got2 = await ch.get(timeout=1.0)
        assert got1 is not None and got2 is not None

    @pytest.mark.asyncio
    async def test_get_filter_message_types(self, channel):
        from vibe_trading.agents.messaging import MessageType
        await channel.put(_msg(mid="report", mtype=MessageType.ANALYSIS_REPORT))
        from vibe_trading.agents.messaging import MessageType
        got = await channel.get(timeout=1.0, message_types=[MessageType.ANALYSIS_REPORT])
        assert got.message_id == "report"

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe(self, channel):
        from vibe_trading.agents.messaging import MessageType
        await channel.subscribe("agent1", [MessageType.ANALYSIS_REPORT])
        assert "agent1" in channel._subscriptions
        await channel.unsubscribe("agent1")
        assert "agent1" not in channel._subscriptions

    def test_priority_message_create(self):
        from vibe_trading.prime.models import MessagePriority
        pm = PriorityMessage.create(_msg(), MessagePriority.HIGH)
        assert pm.priority == 1  # HIGH → 1

    @pytest.mark.asyncio
    async def test_get_statistics(self, channel):
        stats = await channel.get_stats()
        assert stats is not None


class TestChannelExtras:
    @pytest.mark.asyncio
    async def test_unsubscribe_specific_types(self):
        from vibe_trading.agents.messaging import MessageType
        ch = MessageChannel(maxsize=10, enable_dedup=False)
        await ch.subscribe("a", [MessageType.ANALYSIS_REPORT,
                                 MessageType.MACRO_ANALYSIS])
        await ch.unsubscribe("a", [MessageType.ANALYSIS_REPORT])
        assert MessageType.MACRO_ANALYSIS in ch._subscriptions["a"]

    def test_get_subscribers(self):
        from vibe_trading.agents.messaging import MessageType
        ch = MessageChannel(maxsize=10, enable_dedup=False)
        ch._subscriptions = {
            "a": {MessageType.ANALYSIS_REPORT},
            "b": {MessageType.ANALYSIS_REPORT, MessageType.MACRO_ANALYSIS},
        }
        subs = ch.get_subscribers(MessageType.ANALYSIS_REPORT)
        assert subs == {"a", "b"}
        subs2 = ch.get_subscribers(MessageType.MACRO_ANALYSIS)
        assert subs2 == {"b"}

    @pytest.mark.asyncio
    async def test_size_and_clear(self):
        ch = MessageChannel(maxsize=10, enable_dedup=False)
        await ch.put(_msg(mid="a"))
        assert await ch.size() == 1
        await ch.clear()
        assert await ch.size() == 0

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        ch = MessageChannel(maxsize=10, enable_dedup=False)
        await ch.put(_msg(mid="a"))
        await ch.get(timeout=1.0)
        stats_before = await ch.get_stats()
        assert stats_before.total_messages >= 1
        await ch.reset_stats()
        stats_after = await ch.get_stats()
        assert stats_after.total_messages == 0

    @pytest.mark.asyncio
    async def test_cleanup_dedup(self):
        ch = MessageChannel(maxsize=10, enable_dedup=True)
        msg = _msg(mid="old")
        from vibe_trading.prime.models import MessagePriority
        # 直接塞入過期記錄
        import time as _t
        ch._seen_messages["hash_old"] = _t.time() - 9999
        await ch._cleanup_dedup()
        assert "hash_old" not in ch._seen_messages

    @pytest.mark.asyncio
    async def test_put_queue_full_removes_low(self):
        from vibe_trading.prime.message_channel import PriorityMessage
        from vibe_trading.prime.models import MessagePriority
        ch = MessageChannel(maxsize=2, enable_dedup=False)
        # 直接操作 queue 塞滿 (繞過 semaphore)
        pm1 = PriorityMessage.create(_msg(mid="low1"), MessagePriority.LOW)
        pm2 = PriorityMessage.create(_msg(mid="low2"), MessagePriority.LOW)
        ch._queue.extend([pm1, pm2])
        ch._semaphore = MagicMock()
        ch._semaphore.acquire = AsyncMock(return_value=True)
        ch._semaphore.release = MagicMock()
        assert await ch.put(_msg(mid="new"), MessagePriority.HIGH) is True
        ids = [pm.message.message_id for pm in ch._queue]
        assert "new" in ids
        assert len(ids) <= 2
