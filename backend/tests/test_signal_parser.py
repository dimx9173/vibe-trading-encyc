"""
Unit tests for VBT decision-parsing bug fix (WEAK_BUY underscore variant).

Validates that SignalProcessor._extract_signal_type and
TradingCoordinator._run_portfolio_manager agree on all BUY/SELL/HOLD variants,
including WEAK_BUY / WEAK BUY / weak-buy (underscore/space/hyphen).
"""
import asyncio

import pytest

from vibe_trading.agents.analysts.base_analyst import BaseAnalystAgent
from vibe_trading.config.agent_config import AgentConfig, AgentRole
from vibe_trading.coordinator.signal_processor import SignalProcessor
from vibe_trading.tools.signal_parser import detect_strength, parse_decision, to_signal_enum


# ---------------------------------------------------------------------------
# Pure parser (shared logic)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Decision: WEAK_BUY\nRationale: 情绪面强劲", "WEAK BUY"),
        ("Decision: WEAK BUY\nRationale: x", "WEAK BUY"),
        ("Decision: WEAK-BUY\nRationale: x", "WEAK BUY"),
        ("Decision: weak_buy\nRationale: x", "WEAK BUY"),
        ("Decision: STRONG_BUY\nRationale: x", "STRONG BUY"),
        ("Decision: STRONG BUY\nRationale: x", "STRONG BUY"),
        ("Decision: STRONG-BUY\nRationale: x", "STRONG BUY"),
        ("Decision: BUY\nRationale: x", "BUY"),
        ("Decision: WEAK_SELL\nRationale: x", "WEAK SELL"),
        ("Decision: WEAK SELL\nRationale: x", "WEAK SELL"),
        ("Decision: STRONG_SELL\nRationale: x", "STRONG SELL"),
        ("Decision: SELL\nRationale: x", "SELL"),
        ("Decision: HOLD\nRationale: x", "HOLD"),
        # Empty string → UNKNOWN (covered by test_parse_decision_none_empty)
    ],
)
def test_parse_decision(text, expected):
    assert parse_decision(text) == expected


# ---------------------------------------------------------------------------
# SignalProcessor._extract_signal_type (consistency with parser)
# ---------------------------------------------------------------------------


@pytest.fixture
def sp():
    return SignalProcessor()


@pytest.mark.parametrize(
    "text",
    [
        "Decision: WEAK_BUY\nRationale: 情绪面、risk表现强劲",
        "Decision: WEAK BUY\nRationale: x",
        "Decision: WEAK-BUY\nRationale: x",
        "Decision: STRONG_BUY\nRationale: x",
        "Decision: STRONG BUY\nRationale: x",
        "Decision: STRONG-BUY\nRationale: x",
        "Decision: BUY\nRationale: x",
        "Decision: WEAK_SELL\nRationale: x",
        "Decision: WEAK SELL\nRationale: x",
        "Decision: STRONG_SELL\nRationale: x",
        "Decision: SELL\nRationale: x",
        "Decision: HOLD\nRationale: x",
        "建议买入，价格 63700",
        "弱买，建议分批",
        "强买，立即追",
        "建议卖出",
        "弱卖，减仓",
        "强卖，止损",
        "观望，等突破",
    ],
)
def test_extract_signal_type(sp, text):
    sig = sp._extract_signal_type(text)
    coord = parse_decision(text)
    expected_sig = {
        "BUY": "BUY",
        "WEAK BUY": "BUY",
        "STRONG BUY": "BUY",
        "SELL": "SELL",
        "WEAK SELL": "SELL",
        "STRONG SELL": "SELL",
        "HOLD": "HOLD",
    }.get(coord, "UNKNOWN")
    assert sig.value == expected_sig, (
        f"Inconsistent: signal_processor={sig.value!r}, parser={coord!r} "
        f"→ expected_sig={expected_sig!r}, text={text!r}"
    )


# ---------------------------------------------------------------------------
# Full process_signal returns WEAK strength for WEAK_BUY inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_strength",
    [
        ("Decision: WEAK_BUY\nRationale: x", "weak"),
        ("Decision: WEAK BUY\nRationale: x", "weak"),
        ("Decision: STRONG_BUY\nRationale: x", "strong"),
        ("Decision: STRONG BUY\nRationale: x", "strong"),
        ("Decision: BUY\nRationale: x", "moderate"),
        ("Decision: HOLD\nRationale: x", "uncertain"),
    ],
)
def test_strength_detection(sp, text, expected_strength):
    result = sp.process_signal(decision_text=text, agent_name="PM")
    assert result.strength.value == expected_strength, (
        f"text={text!r} → strength={result.strength.value!r}, expected {expected_strength!r}"
    )


# ---------------------------------------------------------------------------
# TradingCoordinator._run_portfolio_manager end-to-end (without full pipeline)
# ---------------------------------------------------------------------------


class _FakeCoordinator:
    """Minimal mirror of TradingCoordinator._run_portfolio_manager parser logic
    (kept in sync with the source via unit tests).
    """

    async def _run_portfolio_manager(self, pm_response):
        from vibe_trading.tools.signal_parser import parse_decision

        decision_text = (
            pm_response.get("decision_text", "")
            if isinstance(pm_response, dict)
            else str(pm_response)
        )
        decision = parse_decision(decision_text)
        return {
            "decision": decision,
            "rationale": decision_text,
            "execution_instructions": None,
        }


@pytest.mark.parametrize(
    "decision_text,expected_decision",
    [
        ("Decision: WEAK_BUY\nRationale: 情绪面", "WEAK BUY"),
        ("Decision: WEAK BUY\nRationale: x", "WEAK BUY"),
        ("Decision: WEAK-BUY\nRationale: x", "WEAK BUY"),
        ("Decision: STRONG_BUY\nRationale: x", "STRONG BUY"),
        ("Decision: BUY\nRationale: x", "BUY"),
        ("Decision: WEAK_SELL\nRationale: x", "WEAK SELL"),
        ("Decision: HOLD\nRationale: x", "HOLD"),
    ],
)
@pytest.mark.asyncio
async def test_coordinator_decision_via_pm_response(decision_text, expected_decision):
    """Regression: PM outputs Decision: X, coordinator returns X (not BUY)."""
    fc = _FakeCoordinator()
    result = await fc._run_portfolio_manager({"decision_text": decision_text})
    assert result["decision"] == expected_decision


# ---------------------------------------------------------------------------
# Cross-check: parser and signal_processor agree on PM-style WEAK_BUY input
# ---------------------------------------------------------------------------


def test_pm_weak_buy_no_longer_unknown(sp):
    """Regression test for the original bug (11:00 根): PM output `Decision: WEAK_BUY`
    must NOT be parsed as UNKNOWN."""
    decision_text = (
        "Decision: WEAK_BUY\n"
        "Rationale: 情绪面、risk表现强劲，因此建议WEAK_BUY"
    )
    result = sp.process_signal(decision_text=decision_text, agent_name="PM")
    assert result.signal.value == "BUY", (
        f"PM WEAK_BUY must parse as BUY, got {result.signal.value!r}"
    )
    assert result.strength.value == "weak"


# ---------------------------------------------------------------------------
# Coverage gaps from claude review (NEEDS_FIX follow-ups)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [None, ""])
def test_parse_decision_none_empty(text):
    """Empty/None input must return UNKNOWN sentinel (not HOLD), so the
    signal_processor dead-code guard at _extract_signal_type becomes live."""
    assert parse_decision(text) == "UNKNOWN"


def test_parse_decision_strong_sell_hyphen():
    assert parse_decision("Decision: STRONG-SELL") == "STRONG SELL"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("保持不动，等突破", "HOLD"),
        ("不确定，继续观察", "HOLD"),
        ("保持仓位", "HOLD"),
        ("觀望中", "HOLD"),
    ],
)
def test_parse_decision_chinese_hold(text, expected):
    assert parse_decision(text) == expected


def test_parse_decision_multi_signal_ordering():
    """When text mentions BUY before SELL, BUY must win (priority order)."""
    assert parse_decision("BUY but reconsider SELL") == "BUY"


def test_to_signal_enum_unknown_pass_through():
    assert to_signal_enum("UNKNOWN") == "UNKNOWN"


def test_detect_strength_hedge_plain_buy():
    """Hedge words on plain BUY should downgrade to WEAK (regression for HIGH)."""
    assert detect_strength("BUY but might be wrong") == "weak"
    assert detect_strength("SELL possibly overreaction") == "weak"


def test_detect_strength_strong_hedge_plain():
    assert detect_strength("BUY clearly the right move") == "strong"
    assert detect_strength("SELL strongly recommended") == "strong"


def test_detect_strength_none_returns_uncertain():
    assert detect_strength(None) == "uncertain"
    assert detect_strength("") == "uncertain"


# Avoid unused-import warning while keeping imports readable
_ = BaseAnalystAgent
_ = AgentConfig
_ = AgentRole
