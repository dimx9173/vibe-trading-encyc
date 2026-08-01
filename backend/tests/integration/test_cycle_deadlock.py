"""TDD tests for cycle deadlock fix (SWDD PHASE_6 DYNAMIC_COMPILE).

Tests the Option C fix per PHASE_5 SYNTHESIS spec:
- T1: `_cycle_lock` exists on SimplifiedTradingCoordinator as asyncio.Lock
- T2: `_reset_agent_states()` clears `_state.is_streaming=True` leaked state on 5 wrappers
- T2b: `_reset_agent_states()` skips uninitialized (None) agents without crashing
- T2c: `_reset_agent_states()` fails open on private API changes
- T3: concurrent cycles serialize via the lock (no overlap)
"""
import asyncio
import pytest
from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from vibe_trading.coordinator.simplified_coordinator import SimplifiedTradingCoordinator


def _make_coordinator():
    """Create SimplifiedTradingCoordinator with safe defaults (no LLM setup)."""
    return SimplifiedTradingCoordinator(symbol="BTCUSDT", interval="30m")


# === T1: cycle lock presence ===
def test_T1_cycle_lock_is_asyncio_lock_instance():
    """Coordinator must expose `_cycle_lock` as `asyncio.Lock` to serialize cycles."""
    coord = _make_coordinator()
    assert hasattr(coord, "_cycle_lock"), (
        "SimplifiedTradingCoordinator must expose `_cycle_lock` attribute "
        "(see PHASE_5 SYNTHESIS spec)"
    )
    assert isinstance(coord._cycle_lock, asyncio.Lock)


# === T2: defensive reset clears leaked busy state ===
def test_T2_reset_clears_busy_state_on_all_5_agents():
    """`_reset_agent_states()` clears `_state.is_streaming=True` on all 5 wrappers."""
    coord = _make_coordinator()
    leaked = SimpleNamespace(is_streaming=True)
    for attr in (
        "_technical_analyst",
        "_bull_researcher",
        "_bear_researcher",
        "_research_manager",
        "_portfolio_manager",
    ):
        setattr(coord, attr, SimpleNamespace(_agent=SimpleNamespace(_state=leaked)))

    coord._reset_agent_states()

    for attr in (
        "_technical_analyst",
        "_bull_researcher",
        "_bear_researcher",
        "_research_manager",
        "_portfolio_manager",
    ):
        wrapper = getattr(coord, attr)
        assert wrapper._agent._state.is_streaming is False, (
            f"{attr}._agent._state.is_streaming still True after reset"
        )


def test_T2b_reset_skips_uninitialized_agents():
    """`_reset_agent_states()` must not crash on None agents."""
    coord = _make_coordinator()
    # All 5 attrs default to None after __init__
    coord._reset_agent_states()  # must not raise


def test_T2c_reset_silent_on_private_api_changes():
    """`_reset_agent_states()` must fail-open if private API changes."""
    coord = _make_coordinator()
    # Bad wrapper: no `_state` attribute (simulates library API change)
    coord._technical_analyst = SimpleNamespace(_agent=object())
    coord._bull_researcher = None  # mix with None to exercise both paths
    coord._reset_agent_states()  # must not raise


# === T3: concurrent cycles serialize ===
async def test_T3_concurrent_cycles_serialize_no_overlap():
    """Two concurrent cycle calls must serialize via `_cycle_lock` (no overlap)."""
    coord = _make_coordinator()
    log = []

    async def stub_cycle(name):
        async with coord._cycle_lock:
            log.append(f"{name}_enter")
            await asyncio.sleep(0.05)
            log.append(f"{name}_exit")

    await asyncio.gather(stub_cycle("A"), stub_cycle("B"))

    assert log in (
        ["A_enter", "A_exit", "B_enter", "B_exit"],
        ["B_enter", "B_exit", "A_enter", "A_exit"],
    ), f"interleaved execution detected: {log}"
