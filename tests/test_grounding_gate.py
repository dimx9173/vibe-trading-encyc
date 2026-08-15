"""Tests for Grounding Gate (execution/grounding_gate.py) + coordinator degradation."""
from types import SimpleNamespace

import pytest

from vibe_trading.execution.grounding_gate import validate_trading_plan_prices


def _plan(entry=None, stop=None, take=None):
    return SimpleNamespace(
        entry_orders=[{"price": entry, "order_type": "limit", "pct": 100}] if entry else [],
        stop_loss_orders=[{"trigger_price": stop}] if stop else [],
        take_profit_orders=[{"price": take}] if take else [],
    )


class TestGate:
    def test_prices_within_band_pass(self):
        plan = _plan(entry=62892.0, stop=61000.0, take=65000.0)
        # bar 62850~63100: entry in ±2%, SL/TP in ±10%
        r = validate_trading_plan_prices(plan, 62850, 63100, 62892)
        assert r["passed"] is True
        assert r["violations"] == []
        assert r["checked_points"] == 3

    def test_entry_outside_band_fails(self):
        plan = _plan(entry=65000.0)
        r = validate_trading_plan_prices(plan, 62850, 63100, 62892)
        assert r["passed"] is False
        assert any("entry_1" in v for v in r["violations"])

    def test_no_ohlc_fails_open(self):
        plan = _plan(entry=99999.0)  # 即使離譜, 無證據也放行
        r = validate_trading_plan_prices(plan, 0, 0, 62892)
        assert r["passed"] is True
        assert r["reason"] == "no OHLC evidence available"
        assert r["checked_points"] == 0

    def test_market_order_none_price_skipped(self):
        plan = SimpleNamespace(
            entry_orders=[{"price": None, "order_type": "market", "pct": 100}],
            stop_loss_orders=[], take_profit_orders=[],
        )
        r = validate_trading_plan_prices(plan, 62850, 63100, 62892)
        assert r["passed"] is True
        assert r["checked_points"] == 0

    def test_stop_loss_beyond_bar_allowed(self):
        # 止損在 bar 外 5% (±2% 內會誤殺, ±10% 放寬通過)
        plan = _plan(entry=62892.0, stop=61000.0)
        r = validate_trading_plan_prices(plan, 62850, 63100, 62892)
        assert r["passed"] is True
        assert r["checked_points"] == 2

    def test_stop_loss_extreme_fails(self):
        # 止損離 bar 20% — 即使放寬也失敗
        plan = _plan(entry=62892.0, stop=50000.0)
        r = validate_trading_plan_prices(plan, 62850, 63100, 62892)
        assert r["passed"] is False
        assert any("stop_loss_1" in v for v in r["violations"])

    def test_band_multiplier_configurable(self):
        plan = _plan(entry=65000.0)
        r = validate_trading_plan_prices(plan, 62850, 63100, 62892, band_multiplier=0.05)
        # 65000 vs high 63100×1.05=66255 → 通過
        assert r["passed"] is True


class TestCoordinatorDegradation:
    @pytest.mark.asyncio
    async def test_degrades_to_hold(self):
        """Gate 違規 → final_decision 降級 HOLD, execution_plan None."""
        # 模擬 coordinator 插入點邏輯 (不啟動完整 coordinator)
        final_decision = {
            "decision": "BUY",
            "rationale": "Strong momentum",
            "confidence": 0.8,
            "execution_plan": SimpleNamespace(total_position_usdt=100),
        }
        trading_plan = _plan(entry=65000.0)

        # 直接執行 gate 段落邏輯 (模擬 coordinator 插入點)
        from vibe_trading.execution.grounding_gate import validate_trading_plan_prices

        grounding_result = validate_trading_plan_prices(
            trading_plan, bar_low=62850.0, bar_high=63100.0, current_price=62892.0
        )
        if not grounding_result["passed"]:
            final_decision = {
                "decision": "HOLD",
                "rationale": f"[Grounding 駁回] {final_decision['rationale']}\n"
                             f"違規: {'; '.join(grounding_result['violations'])}",
                "confidence": min(final_decision["confidence"], 0.5),
                "execution_plan": None,
            }
            trading_plan = None

        assert final_decision["decision"] == "HOLD"
        assert final_decision["execution_plan"] is None
        assert final_decision["confidence"] == 0.5
        assert "Grounding 駁回" in final_decision["rationale"]
        assert trading_plan is None

    def test_decision_metadata_records_grounding(self):
        """TradingDecision.metadata 記錄 grounding 結果."""
        from vibe_trading.coordinator.trading_coordinator import TradingDecision

        d = TradingDecision(
            symbol="BTCUSDT",
            timestamp=1786735800000,
            decision="HOLD",
            rationale="test",
            metadata={"grounding": {"passed": False, "violations": ["entry_1 65000 超出"]}},
        )
        assert d.metadata["grounding"]["passed"] is False

    def test_legacy_decision_without_metadata(self):
        """舊記錄無 metadata 欄位 → getattr fallback 不崩潰."""
        from vibe_trading.coordinator.trading_coordinator import TradingDecision

        d = TradingDecision(
            symbol="BTCUSDT", timestamp=1, decision="BUY", rationale="old"
        )
        meta = getattr(d, "metadata", None) or {}
        assert meta == {}

    def test_tg_display_grounding_rejected(self):
        """format_last_decision 顯示 Grounding 駁回行."""
        from datetime import datetime, timezone
        from vibe_trading.notifications.commands import format_last_decision

        decision = SimpleNamespace(
            timestamp=int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp() * 1000),
            decision="HOLD",
            confidence=0.5,
            rationale="[Grounding 駁回] strong momentum",
            agent_outputs={},
            metadata={"grounding": {"passed": False, "violations": ["entry_1 65000 超出"]}},
        )
        coordinator = SimpleNamespace(get_decision_history=lambda: [decision])
        onbar = SimpleNamespace(_coordinator=coordinator)
        system = SimpleNamespace(onbar_thread=onbar)

        async def run():
            return await format_last_decision(system)

        import asyncio
        text = asyncio.run(run())
        assert "Grounding 駁回" in text
        assert "65000" in text
