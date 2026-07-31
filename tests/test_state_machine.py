"""
Test for DecisionStateMachine

Reproduces the bug found in production 2026-07-31:
TradingCoordinator.analyze_and_decide() called transition_to(COMPLETED) while
the state machine was still in ANALYZING state, because intermediate transitions
to DEBATING / ASSESSING_RISK / PLANNING had failed for some reason.
"""
from vibe_trading.coordinator.state_machine import (
    DecisionState,
    DecisionStateMachine,
)


class TestFullFlow:
    """The expected pipeline: PENDING → ANALYZING → DEBATING → ASSESSING_RISK → PLANNING → COMPLETED."""

    def test_walk_full_path_succeeds(self):
        sm = DecisionStateMachine(decision_id="t1", symbol="BTCUSDT", interval="30m")
        assert sm.current_state == DecisionState.PENDING

        assert sm.transition_to(DecisionState.ANALYZING)
        assert sm.current_state == DecisionState.ANALYZING

        assert sm.transition_to(DecisionState.DEBATING)
        assert sm.current_state == DecisionState.DEBATING

        assert sm.transition_to(DecisionState.ASSESSING_RISK)
        assert sm.current_state == DecisionState.ASSESSING_RISK

        assert sm.transition_to(DecisionState.PLANNING)
        assert sm.current_state == DecisionState.PLANNING

        assert sm.transition_to(DecisionState.COMPLETED)
        assert sm.current_state == DecisionState.COMPLETED
        assert sm.is_terminal_state()

    def test_complete_helper_at_planning(self):
        sm = DecisionStateMachine(decision_id="t2", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        sm.transition_to(DecisionState.ASSESSING_RISK)
        sm.transition_to(DecisionState.PLANNING)
        assert sm.complete({"decision": "BUY", "rationale": "ok"})
        assert sm.current_state == DecisionState.COMPLETED


class TestInvalidTransitions:
    """Phase-to-phase transitions must still be enforced (no skipping)."""

    def test_skip_to_completed_from_pending_fails(self):
        """PENDING must enter ANALYZING first; COMPLETED is a safety valve only
        from non-pending intermediate states."""
        sm = DecisionStateMachine(decision_id="t5", symbol="BTCUSDT", interval="30m")
        # PENDING does not allow COMPLETED directly (only ANALYZING/FAILED/CANCELLED)
        result = sm.transition_to(DecisionState.COMPLETED)
        assert result is False
        assert sm.current_state == DecisionState.PENDING

    def test_invalid_jump_analyzing_to_assessing_risk_fails(self):
        sm = DecisionStateMachine(decision_id="t6", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        result = sm.transition_to(DecisionState.ASSESSING_RISK)
        assert result is False
        assert sm.current_state == DecisionState.ANALYZING

    def test_invalid_jump_debating_to_planning_fails(self):
        sm = DecisionStateMachine(decision_id="t6b", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        # Once a phase is started, must progress through the chain (or terminal)
        result = sm.transition_to(DecisionState.PLANNING)
        assert result is False
        assert sm.current_state == DecisionState.DEBATING

    def test_terminal_state_blocks_all_transitions(self):
        sm = DecisionStateMachine(decision_id="t7", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.FAILED, "boom")
        assert sm.is_terminal_state()

        # Any transition from terminal fails
        assert sm.transition_to(DecisionState.COMPLETED) is False
        assert sm.transition_to(DecisionState.DEBATING) is False
        assert sm.current_state == DecisionState.FAILED


class TestTerminalStateCanStillComplete:
    """
    After the fix: COMPLETED becomes a "safety valve" reachable from any
    non-terminal state. This unblocks the coordinator when intermediate
    transitions fail silently, so the pipeline at least records the decision
    instead of dropping it on the floor.
    """

    def test_complete_from_analyzing_succeeds_after_fix(self):
        sm = DecisionStateMachine(decision_id="t8", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        # After fix this should succeed even though we skipped DEBATING
        assert sm.complete({"decision": "BUY"})
        assert sm.current_state == DecisionState.COMPLETED

    def test_complete_from_debating_succeeds_after_fix(self):
        sm = DecisionStateMachine(decision_id="t9", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        assert sm.complete({"decision": "SELL"})
        assert sm.current_state == DecisionState.COMPLETED

    def test_complete_from_assessing_risk_succeeds_after_fix(self):
        sm = DecisionStateMachine(decision_id="t10", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        sm.transition_to(DecisionState.ASSESSING_RISK)
        assert sm.complete({"decision": "HOLD"})
        assert sm.current_state == DecisionState.COMPLETED

    def test_complete_from_pending_still_fails(self):
        # PENDING is special: you should at least start ANALYZING before completing
        sm = DecisionStateMachine(decision_id="t11", symbol="BTCUSDT", interval="30m")
        # Allowed from PENDING: ANALYZING, FAILED, CANCELLED
        # COMPLETED is not allowed - must enter pipeline first
        assert sm.complete({"decision": "BUY"}) is False
        assert sm.current_state == DecisionState.PENDING


class TestStateHistory:
    def test_history_records_successful_transitions_only(self):
        sm = DecisionStateMachine(decision_id="t12", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        # COMPLETED is now allowed from DEBATING (safety valve), so it is recorded
        sm.transition_to(DecisionState.COMPLETED)
        assert len(sm.state_history) == 3
        assert sm.state_history[0].from_state == DecisionState.PENDING
        assert sm.state_history[0].to_state == DecisionState.ANALYZING
        assert sm.state_history[1].from_state == DecisionState.ANALYZING
        assert sm.state_history[1].to_state == DecisionState.DEBATING
        assert sm.state_history[2].from_state == DecisionState.DEBATING
        assert sm.state_history[2].to_state == DecisionState.COMPLETED

    def test_history_does_not_record_invalid_transitions(self):
        # Invalid transitions (e.g. PENDING -> COMPLETED) must NOT be logged
        sm = DecisionStateMachine(decision_id="t12b", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.COMPLETED)  # invalid, must be rejected
        assert sm.current_state == DecisionState.PENDING
        assert len(sm.state_history) == 0

    def test_cancel_from_any_non_terminal(self):
        sm = DecisionStateMachine(decision_id="t13", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        sm.transition_to(DecisionState.ASSESSING_RISK)
        sm.cancel("test cancel")
        assert sm.current_state == DecisionState.CANCELLED
        assert sm.is_terminal_state()

    def test_fail_from_any_non_terminal(self):
        sm = DecisionStateMachine(decision_id="t14", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        sm.fail("something broke")
        assert sm.current_state == DecisionState.FAILED
        assert sm.is_terminal_state()


class TestStateSummary:
    def test_summary_includes_phase_info(self):
        sm = DecisionStateMachine(decision_id="t15", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING)
        sm.transition_to(DecisionState.DEBATING)
        summary = sm.get_state_summary()
        assert summary["current_state"] == DecisionState.DEBATING
        assert summary["current_phase"] == 2
        assert len(summary["state_history"]) == 2
        assert summary["has_analyst_reports"] is False
        assert summary["has_debate_result"] is False


class TestContextUpdate:
    def test_context_phase_advances(self):
        sm = DecisionStateMachine(decision_id="t16", symbol="BTCUSDT", interval="30m")
        assert sm.context.current_phase == 0
        sm.transition_to(DecisionState.ANALYZING)
        assert sm.context.current_phase == 1
        sm.transition_to(DecisionState.DEBATING)
        assert sm.context.current_phase == 2
        sm.transition_to(DecisionState.ASSESSING_RISK)
        assert sm.context.current_phase == 3
        sm.transition_to(DecisionState.PLANNING)
        assert sm.context.current_phase == 4

    def test_context_metadata_propagates(self):
        sm = DecisionStateMachine(decision_id="t17", symbol="BTCUSDT", interval="30m")
        sm.transition_to(DecisionState.ANALYZING, metadata={"analyst_reports": {"macro": "bullish"}})
        assert sm.context.analyst_reports == {"macro": "bullish"}
        sm.transition_to(DecisionState.DEBATING, metadata={"debate_result": {"side": "buy"}})
        assert sm.context.debate_result == {"side": "buy"}
