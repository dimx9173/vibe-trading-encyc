"""Tests for DecisionAggregator (Wave D — coverage 85% plan)."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from vibe_trading.prime.decision_aggregator import (
    DecisionAggregator,
    SignalType,
    SubagentSignal,
)


def _msg(sender: str, content: dict, mtype=None):
    from vibe_trading.agents.messaging import MessageType
    m = MagicMock()
    m.sender = sender
    m.content = content
    m.message_type = mtype or MessageType.ANALYSIS_REPORT
    m.timestamp = datetime.now()
    return m


class TestSignalType:
    def test_values(self):
        assert SignalType.BULLISH.value == "bullish"
        assert SignalType.HOLD.value == "hold"


class TestGetAgentType:
    def test_agent_types(self):
        a = DecisionAggregator()
        assert a._get_agent_type("technical_analyst") == "analyst"
        assert a._get_agent_type("bull_researcher") == "researcher"
        assert a._get_agent_type("risk_team") == "risk"
        assert a._get_agent_type("portfolio_manager") == "decision"
        assert a._get_agent_type("macro_team") == "macro"
        assert a._get_agent_type("unknown_thing") is None


class TestParseContent:
    def test_buy_signal_message_type(self):
        from vibe_trading.agents.messaging import MessageType
        a = DecisionAggregator()
        st, conf, reason = a._parse_content({"reason": "看涨"}, MessageType.BUY_SIGNAL)
        assert st == SignalType.BULLISH
        assert reason == "看涨"

    def test_sell_signal(self):
        from vibe_trading.agents.messaging import MessageType
        a = DecisionAggregator()
        st, _, _ = a._parse_content({}, MessageType.SELL_SIGNAL)
        assert st == SignalType.BEARISH

    def test_hold_signal(self):
        from vibe_trading.agents.messaging import MessageType
        a = DecisionAggregator()
        st, _, _ = a._parse_content({}, MessageType.HOLD_SIGNAL)
        assert st == SignalType.HOLD

    def test_confidence_clamped(self):
        from vibe_trading.agents.messaging import MessageType
        a = DecisionAggregator()
        _, conf, _ = a._parse_content({"confidence": 1.5}, MessageType.BUY_SIGNAL)
        assert conf == 1.0

    def test_confidence_default(self):
        from vibe_trading.agents.messaging import MessageType
        a = DecisionAggregator()
        _, conf, _ = a._parse_content({}, MessageType.ANALYSIS_REPORT)
        assert conf == 0.5


class TestAnalyzeSentiment:
    def test_bullish(self):
        a = DecisionAggregator()
        assert a._analyze_sentiment({"text": "看涨买入 long"}) == SignalType.BULLISH

    def test_bearish(self):
        a = DecisionAggregator()
        assert a._analyze_sentiment({"text": "看跌卖出 short"}) == SignalType.BEARISH

    def test_hold(self):
        a = DecisionAggregator()
        assert a._analyze_sentiment({"text": "中性觀望 hold"}) == SignalType.HOLD

    def test_neutral(self):
        a = DecisionAggregator()
        assert a._analyze_sentiment({"text": "無明顯信號"}) == SignalType.NEUTRAL


class TestAddSignal:
    def test_add_analyst_signal(self):
        a = DecisionAggregator()
        signal = a.add_signal(_msg("technical_analyst", {"confidence": 0.8, "reason": "看涨"}))
        assert signal is not None
        assert signal.agent_type == "analyst"
        assert len(a.signals) == 1

    def test_add_unknown_agent(self):
        a = DecisionAggregator()
        assert a.add_signal(_msg("mystery", {})) is None

    def test_extract_signal_no_type(self):
        a = DecisionAggregator()
        assert a._extract_signal(_msg("unknown_thing", {})) is None


class TestAggregate:
    def test_insufficient_signals(self):
        a = DecisionAggregator(min_signals=3)
        a.add_signal(_msg("technical_analyst", {"confidence": 0.8}))
        assert a.aggregate() is None

    def test_bullish_decision(self):
        a = DecisionAggregator(min_signals=3)
        for i in range(3):
            a.add_signal(_msg("technical_analyst", {"confidence": 0.8, "text": "看涨"}))
        decision = a.aggregate()
        assert decision is not None
        assert decision.action.value == "buy"
        assert len(a.signal_history) == 1

    def test_bearish_decision(self):
        a = DecisionAggregator(min_signals=3)
        for i in range(3):
            a.add_signal(_msg("technical_analyst", {"confidence": 0.8, "text": "看跌"}))
        decision = a.aggregate()
        assert decision.action.value == "sell"

    def test_conflict_forces_hold(self):
        a = DecisionAggregator(min_signals=4)
        for i in range(2):
            a.add_signal(_msg("technical_analyst", {"confidence": 0.8, "text": "看涨"}))
        for i in range(2):
            a.add_signal(_msg("risk_analyst", {"confidence": 0.8, "text": "看跌"}))
        decision = a.aggregate()
        # 多空衝突 → HOLD
        assert decision.action.value == "hold"
        assert decision.metadata.get("conflict") is True

    def test_weak_signal_hold(self):
        a = DecisionAggregator(min_signals=3)
        for i in range(3):
            a.add_signal(_msg("technical_analyst", {"confidence": 0.1, "text": "看涨"}))
        decision = a.aggregate()
        assert decision.action.value == "hold"  # score 低於 0.4

    def test_signals_cleared_after_aggregate(self):
        a = DecisionAggregator(min_signals=3)
        for i in range(3):
            a.add_signal(_msg("technical_analyst", {"confidence": 0.8, "text": "看涨"}))
        a.aggregate()
        assert a.signals == []


class TestSubagentSignal:
    def test_weight_property(self):
        s = SubagentSignal(
            agent_id="a", agent_type="analyst", signal_type=SignalType.BULLISH,
            confidence=0.8, reasoning="", timestamp=datetime.now(),
        )
        assert s.weight > 0

    def test_weight_unknown_type(self):
        s = SubagentSignal(
            agent_id="a", agent_type="mystery", signal_type=SignalType.BULLISH,
            confidence=0.8, reasoning="", timestamp=datetime.now(),
        )
        assert s.weight == 0.5


class TestStatus:
    def test_get_status(self):
        a = DecisionAggregator(min_signals=2)
        a.add_signal(_msg("technical_analyst", {"confidence": 0.5}))
        status = a.get_status()
        assert status["current_signals"] == 1
        assert status["min_signals"] == 2

    def test_reset(self):
        a = DecisionAggregator()
        a.add_signal(_msg("technical_analyst", {"confidence": 0.5}))
        a.reset()
        assert a.signals == []
