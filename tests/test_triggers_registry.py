"""Tests for triggers/registry (Wave C — coverage 85% plan)."""
import asyncio
from datetime import datetime, timedelta

import pytest

from vibe_trading.triggers.base_trigger import (
    BaseTrigger,
    ConfirmationTracker,
    TriggerConfirmation,
    TriggerContext,
    TriggerEvent,
    TriggerPriority,
    TriggerSeverity,
    VolatilitySpikeTrigger,
)
from vibe_trading.triggers.trigger_registry import TriggerRegistry


def _event(name: str = "test", severity: TriggerSeverity = TriggerSeverity.MEDIUM) -> TriggerEvent:
    return TriggerEvent(
        event_id="", trigger_name=name, severity=severity,
        data={"k": "v"}, timestamp=123, symbol="BTCUSDT",
    )


def _context(price: float = 100.0, prev: float = 100.0, **extra) -> TriggerContext:
    return TriggerContext(
        symbol="BTCUSDT", current_price=price, previous_price=prev,
        timestamp=123, additional_data=extra,
    )


class TestTriggerContext:
    def test_get_set(self):
        ctx = _context()
        assert ctx.get("missing", "dflt") == "dflt"
        ctx.set("key", "val")
        assert ctx.get("key") == "val"

    def test_defaults(self):
        ctx = _context()
        assert ctx.positions == []
        assert ctx.account_balance == 0.0


class TestTriggerEvent:
    def test_auto_event_id(self):
        e = TriggerEvent(event_id="", trigger_name="t", severity=TriggerSeverity.LOW,
                         data={}, timestamp=1)
        assert e.event_id.startswith("evt_")

    def test_roundtrip(self):
        e = _event()
        d = e.to_dict()
        assert TriggerEvent.from_dict(d) == e

    def test_severity_enum(self):
        # str Enum — 比較 value 字面量 (非大小)
        assert TriggerSeverity.HIGH.value == "high"
        assert TriggerSeverity.CRITICAL.value == "critical"


class TestTriggerConfirmation:
    def test_requires_3_confirmations(self):
        c = TriggerConfirmation(trigger_name="t")
        assert c.required_confirmations == 3
        assert c.add_event(_event()) is False
        assert c.add_event(_event()) is False
        assert c.add_event(_event()) is True

    def test_reset(self):
        c = TriggerConfirmation(trigger_name="t")
        c.add_event(_event())
        c.reset()
        assert c.confirmation_count == 0
        assert c.events == []
        assert c.first_seen_at is None

    def test_is_stale_no_first_seen(self):
        assert TriggerConfirmation(trigger_name="t").is_stale() is True

    def test_is_stale_old(self):
        c = TriggerConfirmation(trigger_name="t")
        c.first_seen_at = datetime.now() - timedelta(seconds=600)
        assert c.is_stale(max_age_seconds=300) is True


class TestConfirmationTracker:
    @pytest.mark.asyncio
    async def test_confirm_after_3(self):
        t = ConfirmationTracker(required_confirmations=3)
        for i in range(2):
            confirmed, _ = await t.add_event(_event())
            assert confirmed is False
        confirmed, conf = await t.add_event(_event())
        assert confirmed is True
        assert conf.confirmed is True

    @pytest.mark.asyncio
    async def test_get_reset(self):
        t = ConfirmationTracker(required_confirmations=3)
        await t.add_event(_event())
        got = await t.get_confirmation("test")
        assert got is not None and got.confirmation_count == 1
        await t.reset_confirmation("test")
        got = await t.get_confirmation("test")
        assert got.confirmation_count == 0

    @pytest.mark.asyncio
    async def test_cleanup_stale(self):
        t = ConfirmationTracker(required_confirmations=3, max_age_seconds=0)
        await t.add_event(_event())
        await t.cleanup_stale()
        assert await t.get_confirmation("test") is None

    @pytest.mark.asyncio
    async def test_stats(self):
        t = ConfirmationTracker(required_confirmations=2)
        await t.add_event(_event())
        stats = t.get_statistics()
        assert stats["total_confirmations"] == 1
        assert stats["pending_count"] == 1
        assert stats["required_confirmations"] == 2

    @pytest.mark.asyncio
    async def test_cleanup_task_lifecycle(self):
        t = ConfirmationTracker(cleanup_interval=3600)
        await t.start_cleanup_task()
        await t.start_cleanup_task()  # idempotent
        await t.stop_cleanup_task()
        assert t._cleanup_task is None


class _FakeTrigger(BaseTrigger):
    """可控觸發器."""

    def __init__(self, fire: bool = True, name: str = "fake", **kwargs):
        super().__init__(name=name, **kwargs)
        self._fire = fire

    async def check(self, context: TriggerContext) -> TriggerEvent | None:
        if not self._fire:
            return None
        return _event(name=self.name, severity=self.severity)


class TestBaseTrigger:
    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        t = _FakeTrigger(enabled=False)
        assert await t.evaluate(_context()) is None

    @pytest.mark.asyncio
    async def test_fire_and_cooldown(self):
        t = _FakeTrigger(cooldown_seconds=300)
        event = await t.evaluate(_context())
        assert event is not None
        assert t._trigger_count == 1
        # cooldown 內不再觸發
        assert await t.evaluate(_context()) is None

    @pytest.mark.asyncio
    async def test_no_fire(self):
        t = _FakeTrigger(fire=False)
        assert await t.evaluate(_context()) is None
        assert t._trigger_count == 0

    @pytest.mark.asyncio
    async def test_reset_cooldown(self):
        t = _FakeTrigger(cooldown_seconds=300)
        await t.evaluate(_context())
        await t.reset_cooldown()
        assert await t.evaluate(_context()) is not None

    @pytest.mark.asyncio
    async def test_enable_disable(self):
        t = _FakeTrigger()
        await t.disable()
        assert t.enabled is False
        await t.enable()
        assert t.enabled is True

    def test_stats(self):
        t = _FakeTrigger()
        stats = t.get_statistics()
        assert stats["name"] == "fake"
        assert stats["enabled"] is True
        assert stats["trigger_count"] == 0

    def test_equality_hash(self):
        a, b = _FakeTrigger(), _FakeTrigger()
        assert a == b  # 同名
        assert hash(a) == hash(b)
        assert a != "not_a_trigger"


class TestPriceDropTrigger:
    @pytest.mark.asyncio
    async def test_drop_fires(self):
        from vibe_trading.triggers.price_triggers import PriceDropTrigger
        t = PriceDropTrigger(threshold_pct=0.03)
        event = await t.check(_context(price=95.0, prev=100.0))  # 5% drop
        assert event is not None
        assert event.data["drop_pct"] == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_no_drop(self):
        from vibe_trading.triggers.price_triggers import PriceDropTrigger
        t = PriceDropTrigger(threshold_pct=0.03)
        assert await t.check(_context(price=99.0, prev=100.0)) is None

    @pytest.mark.asyncio
    async def test_zero_prev(self):
        from vibe_trading.triggers.price_triggers import PriceDropTrigger
        t = PriceDropTrigger()
        assert await t.check(_context(price=95.0, prev=0.0)) is None


class TestPriceSpikeTrigger:
    @pytest.mark.asyncio
    async def test_spike_fires(self):
        from vibe_trading.triggers.price_triggers import PriceSpikeTrigger
        t = PriceSpikeTrigger(threshold_pct=0.05)
        event = await t.check(_context(price=110.0, prev=100.0))  # 10% up
        assert event is not None

    @pytest.mark.asyncio
    async def test_no_spike(self):
        from vibe_trading.triggers.price_triggers import PriceSpikeTrigger
        t = PriceSpikeTrigger(threshold_pct=0.05)
        assert await t.check(_context(price=102.0, prev=100.0)) is None


class TestVolatilitySpike:
    @pytest.mark.asyncio
    async def test_spike(self):
        t = VolatilitySpikeTrigger(threshold_std=2.0)
        prices = [100.0 + (i % 5) for i in range(25)]  # 有變動
        ctx = _context(price=115.0)
        ctx.set("recent_prices", prices)
        event = await t.check(ctx)
        assert event is not None

    @pytest.mark.asyncio
    async def test_insufficient_data(self):
        t = VolatilitySpikeTrigger()
        ctx = _context(price=100.0)
        ctx.set("recent_prices", [1.0, 2.0])
        assert await t.check(ctx) is None


class TestRiskTriggers:
    @pytest.mark.asyncio
    async def test_risk_trigger_fires(self):
        from vibe_trading.triggers.risk_triggers import VaRTrigger
        t = VaRTrigger(threshold_var=0.05)
        ctx = _context()
        ctx.set("var_95", 0.08)
        event = await t.check(ctx)
        assert event is not None
        assert event.data["current_var"] == pytest.approx(0.08)

    @pytest.mark.asyncio
    async def test_risk_trigger_no_fire(self):
        from vibe_trading.triggers.risk_triggers import VaRTrigger
        t = VaRTrigger(threshold_var=0.05)
        ctx = _context()
        ctx.set("var_95", 0.01)
        assert await t.check(ctx) is None

    @pytest.mark.asyncio
    async def test_var_99_selection(self):
        from vibe_trading.triggers.risk_triggers import VaRTrigger
        t = VaRTrigger(threshold_var=0.05, confidence_level=0.99)
        ctx = _context()
        ctx.set("var_95", 0.01)
        ctx.set("var_99", 0.08)
        event = await t.check(ctx)
        assert event is not None  # 用 var_99

    @pytest.mark.asyncio
    async def test_consecutive_loss(self):
        from vibe_trading.triggers.risk_triggers import ConsecutiveLossTrigger
        t = ConsecutiveLossTrigger(threshold_losses=3)
        ctx = _context()
        ctx.set("consecutive_losses", 4)
        event = await t.check(ctx)
        assert event is not None

    @pytest.mark.asyncio
    async def test_drawdown(self):
        from vibe_trading.triggers.risk_triggers import DrawdownTrigger
        t = DrawdownTrigger(threshold_drawdown=0.2)
        ctx = _context()
        ctx.set("current_drawdown", 0.25)
        ctx.set("peak_balance", 10000.0)
        event = await t.check(ctx)
        assert event is not None
        assert event.data["peak_balance"] == 10000.0
        # 未達閾值 → None
        ctx.set("current_drawdown", 0.1)
        assert await t.check(ctx) is None

    @pytest.mark.asyncio
    async def test_position_size(self):
        from vibe_trading.triggers.risk_triggers import PositionSizeTrigger
        t = PositionSizeTrigger(threshold_size_usdt=1000.0)
        ctx = _context()
        ctx.set("total_position_size", 5000.0)
        event = await t.check(ctx)
        assert event is not None
        ctx.set("total_position_size", 100.0)
        assert await t.check(ctx) is None

    @pytest.mark.asyncio
    async def test_liquidation_risk(self):
        from vibe_trading.triggers.risk_triggers import LiquidationRiskTrigger
        t = LiquidationRiskTrigger(buffer_pct=0.05)
        ctx = TriggerContext(
            symbol="BTCUSDT", current_price=100.0, previous_price=100.0,
            timestamp=123,
            positions=[{"symbol": "BTCUSDT", "side": "LONG",
                        "entry_price": 100.0, "liquidation_price": 97.0}],
        )
        event = await t.check(ctx)
        assert event is not None

    @pytest.mark.asyncio
    async def test_liquidation_risk_safe(self):
        from vibe_trading.triggers.risk_triggers import LiquidationRiskTrigger
        t = LiquidationRiskTrigger(buffer_pct=0.05)
        ctx = TriggerContext(
            symbol="BTCUSDT", current_price=100.0, previous_price=100.0,
            timestamp=123,
            positions=[{"symbol": "BTCUSDT", "side": "LONG",
                        "entry_price": 100.0, "liquidation_price": 80.0}],
        )
        assert await t.check(ctx) is None

    @pytest.mark.asyncio
    async def test_liquidation_risk_invalid(self):
        from vibe_trading.triggers.risk_triggers import LiquidationRiskTrigger
        t = LiquidationRiskTrigger()
        ctx = TriggerContext(
            symbol="BTCUSDT", current_price=100.0, previous_price=100.0,
            timestamp=123,
            positions=[{"symbol": "BTCUSDT", "side": "LONG",
                        "entry_price": 0.0, "liquidation_price": 0.0}],
        )
        assert await t.check(ctx) is None

    @pytest.mark.asyncio
    async def test_margin_ratio(self):
        from vibe_trading.triggers.risk_triggers import MarginRatioTrigger
        t = MarginRatioTrigger(threshold_ratio=0.5)
        ctx = _context()
        ctx.set("margin_ratio", 0.7)
        event = await t.check(ctx)
        assert event is not None
        ctx.set("margin_ratio", 0.1)
        assert await t.check(ctx) is None


class TestRegistry:
    def test_register_and_get(self):
        r = TriggerRegistry(enable_confirmation=False)
        t = _FakeTrigger()
        assert r.register(t) is True
        assert r.register(t) is False  # 重複
        assert r.get("fake") is t
        assert "fake" in r
        assert len(r) == 1

    def test_register_type_error(self):
        r = TriggerRegistry()
        with pytest.raises(TypeError):
            r.register("not_a_trigger")

    def test_unregister(self):
        r = TriggerRegistry()
        r.register(_FakeTrigger())
        assert r.unregister("fake") is True
        assert r.unregister("fake") is False

    def test_get_all_copy(self):
        r = TriggerRegistry()
        r.register(_FakeTrigger())
        all_t = r.get_all()
        assert all_t == {"fake": r.get("fake")}

    def test_get_enabled_sorted(self):
        r = TriggerRegistry()
        r.register(_FakeTrigger(name='low', priority=TriggerPriority.LOW, severity=TriggerSeverity.LOW))
        r.register(_FakeTrigger(name='high', priority=TriggerPriority.HIGH, severity=TriggerSeverity.HIGH))
        enabled = r.get_enabled_triggers()
        assert enabled[0].priority.value == TriggerPriority.HIGH.value  # 降序

    def test_get_by_priority_symbol(self):
        r = TriggerRegistry()
        r.register(_FakeTrigger(priority=TriggerPriority.HIGH))
        assert len(r.get_triggers_by_priority(TriggerPriority.HIGH)) == 1
        assert len(r.get_triggers_by_symbol("BTCUSDT")) == 1

    @pytest.mark.asyncio
    async def test_enable_disable_missing(self):
        r = TriggerRegistry()
        assert await r.enable("nope") is False
        assert await r.disable("nope") is False

    @pytest.mark.asyncio
    async def test_evaluate_all_no_confirmation(self):
        r = TriggerRegistry(enable_confirmation=False)
        r.register(_FakeTrigger())
        events = await r.evaluate_all(_context())
        assert len(events) == 1
        assert events[0].trigger_name == "fake"

    @pytest.mark.asyncio
    async def test_evaluate_all_disabled_skipped(self):
        r = TriggerRegistry(enable_confirmation=False)
        r.register(_FakeTrigger(enabled=False))
        assert await r.evaluate_all(_context()) == []

    @pytest.mark.asyncio
    async def test_evaluate_trigger_missing(self):
        r = TriggerRegistry()
        assert await r.evaluate_trigger("nope", _context()) is None

    @pytest.mark.asyncio
    async def test_event_handler_notified(self):
        r = TriggerRegistry(enable_confirmation=False)
        r.register(_FakeTrigger())
        received = []

        async def handler(event):
            received.append(event)

        r.add_event_handler(handler)
        await r.evaluate_all(_context())
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_stats_and_clear(self):
        r = TriggerRegistry()
        r.register(_FakeTrigger())
        stats = r.get_statistics()
        assert stats.total_triggers == 1
        r.clear()
        assert len(r) == 0

    def test_repr(self):
        r = TriggerRegistry()
        r.register(_FakeTrigger())
        assert "triggers=1" in repr(r)

    @pytest.mark.asyncio
    async def test_confirmation_tracker_lifecycle(self):
        r = TriggerRegistry(enable_confirmation=True)
        await r.start_confirmation_tracker()
        await r.stop_confirmation_tracker()
        stats = r.get_confirmation_statistics()
        assert stats is not None


class TestRegistryExtras:
    @pytest.mark.asyncio
    async def test_enable_disable_success(self):
        r = TriggerRegistry()
        t = _FakeTrigger()
        r.register(t)
        assert await r.disable("fake") is True
        assert t.enabled is False
        assert await r.enable("fake") is True
        assert t.enabled is True

    @pytest.mark.asyncio
    async def test_evaluate_all_confirmation_pending(self):
        r = TriggerRegistry(enable_confirmation=True)
        # required=3, 第一次觸發 → pending
        r.register(_FakeTrigger(cooldown_seconds=0))
        events = await r.evaluate_all(_context())
        assert events == []
        await r.evaluate_all(_context())
        events3 = await r.evaluate_all(_context())  # 第 3 次 → 達 3 確認
        assert len(events3) == 1

    @pytest.mark.asyncio
    async def test_evaluate_trigger_ok_and_handler(self):
        r = TriggerRegistry(enable_confirmation=False)
        t = _FakeTrigger()
        r.register(t)
        seen = []
        r.add_event_handler(lambda e: seen.append(e))
        event = await r.evaluate_trigger("fake", _context())
        assert event is not None
        assert seen == [event]

    @pytest.mark.asyncio
    async def test_evaluate_trigger_error(self):
        from unittest.mock import AsyncMock
        r = TriggerRegistry()
        t = _FakeTrigger()
        t.evaluate = AsyncMock(side_effect=RuntimeError("boom"))
        r.register(t)
        assert await r.evaluate_trigger("fake", _context()) is None

    @pytest.mark.asyncio
    async def test_evaluate_all_handler_async(self):
        r = TriggerRegistry(enable_confirmation=False)
        r.register(_FakeTrigger())
        seen = []

        async def handler(event):
            seen.append(event)

        r.add_event_handler(handler)
        await r.evaluate_all(_context())
        assert len(seen) == 1

    def test_remove_event_handler(self):
        r = TriggerRegistry()

        def handler(e):
            pass

        r.add_event_handler(handler)
        r.remove_event_handler(handler)
        assert handler not in r._event_handlers
        r.remove_event_handler(handler)  # 不再在 → 不 raise

    def test_register_trigger_decorator_class(self):
        from vibe_trading.triggers.trigger_registry import register_trigger
        reg = TriggerRegistry(enable_confirmation=False)
        from vibe_trading.triggers.base_trigger import BaseTrigger

        @register_trigger(registry=reg)
        class DecoratedTrigger(BaseTrigger):
            def __init__(self):
                super().__init__(name="decorated_trigger")

            async def check(self, context):
                return None

        assert "decorated_trigger" in reg._triggers

    def test_register_trigger_decorator_class_hit(self):
        # decorator 也可直接裝飾實例 (非 class)
        from vibe_trading.triggers.trigger_registry import register_trigger
        reg = TriggerRegistry(enable_confirmation=False)
        inst = _FakeTrigger(name="inst2")
        returned = register_trigger(registry=reg)(inst)
        assert returned is inst
        assert reg.get("inst2") is inst
