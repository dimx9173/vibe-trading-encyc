"""L1: Meta-Cognition 元認知測試 (規格書 §2.7)."""
from vibe_trading.research.meta_cognition import MetaCognitionEngine


class TestMetaCognition:
    def test_empty_dashboard(self):
        m = MetaCognitionEngine()
        assert "新手保護期" in m.generate_dashboard_prompt()

    def test_post_mortem_win(self):
        m = MetaCognitionEngine()
        r = m.run_post_mortem(
            {"trade_id": "T-1", "direction": "SHORT", "entry": 65000,
             "exit": 62000, "pnl": 300, "battle_card_id": "BC-01"},
            {"regime": "4H_STRONG_DOWNTREND"})
        assert r["result"] == "WIN"
        assert "BC-01" in r["attribution_primary"]

    def test_post_mortem_trap(self):
        m = MetaCognitionEngine()
        r = m.run_post_mortem(
            {"trade_id": "T-2", "direction": "LONG", "entry": 65000,
             "exit": 64000, "pnl": -100},
            {"regime": "4H_STRONG_DOWNTREND"})
        assert r["result"] == "LOSS"
        assert r["memory_trap_created"] == "RISK_TRAP_01_LONG_AGAINST_DOWNTREND"

    def test_rhythm_defensive(self):
        m = MetaCognitionEngine()
        for i in range(4):
            m.run_post_mortem(
                {"trade_id": f"L{i}", "direction": "LONG", "entry": 65000,
                 "exit": 64800, "pnl": -50}, {"regime": "4H_CHOPPY_RANGE"})
        m.run_post_mortem(
            {"trade_id": "W0", "direction": "SHORT", "entry": 65000,
             "exit": 62000, "pnl": 300}, {"regime": "4H_STRONG_DOWNTREND"})
        assert m.get_rhythm_mode()["mode"] == "DEFENSIVE"

    def test_rhythm_aggressive(self):
        m = MetaCognitionEngine()
        for i in range(4):
            m.run_post_mortem(
                {"trade_id": f"W{i}", "direction": "SHORT", "entry": 65000,
                 "exit": 63000, "pnl": 200}, {"regime": "4H_STRONG_DOWNTREND"})
        m.run_post_mortem(
            {"trade_id": "L0", "direction": "LONG", "entry": 65000,
             "exit": 64900, "pnl": -10}, {"regime": "4H_CHOPPY_RANGE"})
        assert m.get_rhythm_mode()["mode"] == "AGGRESSIVE"

    def test_dashboard_stats(self):
        m = MetaCognitionEngine()
        for i in range(4):
            m.run_post_mortem(
                {"trade_id": f"W{i}", "direction": "SHORT", "entry": 65000,
                 "exit": 63000, "pnl": 200}, {"regime": "4H_STRONG_DOWNTREND"})
        m.run_post_mortem(
            {"trade_id": "L0", "direction": "LONG", "entry": 65000,
             "exit": 64900, "pnl": -10}, {"regime": "4H_CHOPPY_RANGE"})
        dash = m.generate_dashboard_prompt()
        assert "80%" in dash  # 4/5 勝
        assert "盈虧比" in dash
