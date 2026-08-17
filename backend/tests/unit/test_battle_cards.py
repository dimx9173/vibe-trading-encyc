"""L1: Battle Cards 戰法庫測試 (規格書 §2.4)."""
from vibe_trading.research.battle_cards import BattleCardRegistry


class TestBattleCards:
    def test_load_8_cards(self):
        r = BattleCardRegistry()
        cards = r.get_all()
        assert len(cards) == 8
        ids = {c["id"] for c in cards}
        assert ids == {f"BC-0{i}" for i in range(1, 9)}

    def test_match_BC01(self):
        r = BattleCardRegistry()
        m = r.match_active_cards({
            "macro_regime": "4H_DOWNTREND",
            "rsi_divergence": "BEARISH_DIV",
            "price_action": "LOWER_HIGH_OR_PINBAR",
        })
        assert any(c["id"] == "BC-01" for c in m)

    def test_match_numeric_condition(self):
        r = BattleCardRegistry()
        m = r.match_active_cards({
            "rsi": 15.0, "volume_ratio": 3.0, "candle_type": "PINBAR_REVERSAL",
        })
        assert any(c["id"] == "BC-04" for c in m)

    def test_no_match(self):
        r = BattleCardRegistry()
        m = r.match_active_cards({"macro_regime": "4H_UPTREND"})
        assert not any(c["id"] == "BC-01" for c in m)

    def test_record_outcome_win(self):
        r = BattleCardRegistry()
        upd = r.record_trade_outcome("BC-01", 150.0, 2.5)
        assert upd["historical_trades"] == 41
        assert upd["historical_win_rate"] > 0.675  # 盈利上調

    def test_record_outcome_loss(self):
        r = BattleCardRegistry()
        upd = r.record_trade_outcome("BC-02", -50.0, -1.0)
        assert upd["historical_trades"] == 29
        assert upd["historical_win_rate"] < 0.640

    def test_record_unknown(self):
        r = BattleCardRegistry()
        assert r.record_trade_outcome("BC-99", 10.0, 1.0) is None
