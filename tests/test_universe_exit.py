"""Tests for dynamic universe + exit ladder (Phase 4.2)."""
from vibe_trading.execution.exit_ladder import make_exit_state, update_exit
from vibe_trading.factors.universe import rank_universe


def _tickers():
    return [
        {"symbol": "BTCUSDT", "quote_volume": 5e9, "price_change_percent": 1.5},
        {"symbol": "ETHUSDT", "quote_volume": 3e9, "price_change_percent": -0.5},
        {"symbol": "BTCUPUSDT", "quote_volume": 2e9, "price_change_percent": 5.0},
        {"symbol": "SOLUSDT", "quote_volume": 5e5, "price_change_percent": 0.2},
        {"symbol": "DOGEUSDT", "quote_volume": 8e8, "price_change_percent": 2.0},
        {"symbol": "ETHUSDC", "quote_volume": 1e9, "price_change_percent": 0.1},
        {"symbol": "BTCBULLUSDT", "quote_volume": 1.5e9, "price_change_percent": 3.0},
        {"symbol": "BTCUSD", "quote_volume": 4e9, "price_change_percent": 0.5},  # 非穩定幣報價
    ]


class TestUniverse:
    def test_rank_filters_leveraged(self):
        r = rank_universe(_tickers(), top_n=10)
        symbols = [t["symbol"] for t in r]
        assert "BTCUPUSDT" not in symbols
        assert "BTCBULLUSDT" not in symbols

    def test_rank_filters_low_volume(self):
        r = rank_universe(_tickers(), top_n=10, min_quote_volume=1e6)
        symbols = [t["symbol"] for t in r]
        assert "SOLUSDT" not in symbols  # 5e5 < 1e6

    def test_rank_filters_non_stable_quote(self):
        r = rank_universe(_tickers(), top_n=10)
        symbols = [t["symbol"] for t in r]
        assert "BTCUSD" not in symbols  # USD 非穩定幣報價

    def test_rank_sorts_by_volume(self):
        r = rank_universe(_tickers(), top_n=10)
        vols = [float(t["quote_volume"]) for t in r]
        assert vols == sorted(vols, reverse=True)

    def test_rank_top_n(self):
        r = rank_universe(_tickers(), top_n=2)
        assert len(r) == 2

    def test_rank_camelcase_volume(self):
        # Binance API 用 quoteVolume (camelCase)
        tickers = [{"symbol": "BTCUSDT", "quoteVolume": 5e9}]
        r = rank_universe(tickers, top_n=1)
        assert r[0]["symbol"] == "BTCUSDT"


class TestExitLadder:
    def test_hold_before_activate(self):
        st = make_exit_state("BTCUSDT", 100.0)
        a = update_exit(st, 102.0, 1.0)  # +2%
        assert a["action"] == "hold"

    def test_trailing_activates(self):
        st = make_exit_state("BTCUSDT", 100.0)
        update_exit(st, 105.0, 1.0)  # +5% → 啟動
        assert st.trailing_active is True
        a = update_exit(st, 104.0, 1.0)  # 啟動後小跌仍 hold
        assert a["action"] == "hold"

    def test_moonbag_sells_half_once(self):
        st = make_exit_state("BTCUSDT", 100.0)
        a = update_exit(st, 110.0, 1.0)  # +10%
        assert a["action"] == "sell_half"
        assert a["quantity"] == 0.5
        a2 = update_exit(st, 115.0, 0.5)  # 不再重複
        assert a2["action"] != "sell_half"
        assert st.moonbag_sold is True

    def test_trailing_exit_on_drawdown(self):
        st = make_exit_state("BTCUSDT", 100.0)
        update_exit(st, 110.0, 1.0)  # moonbag
        update_exit(st, 112.0, 0.5)  # 峰值 112
        a = update_exit(st, 108.0, 0.5)  # 回撤 3.6% ≥ 3%
        assert a["action"] == "sell_all"
        assert a["quantity"] == 0.5

    def test_peak_tracking(self):
        st = make_exit_state("BTCUSDT", 100.0)
        update_exit(st, 108.0, 1.0)
        update_exit(st, 112.0, 1.0)
        assert st.peak_price == 112.0
        update_exit(st, 110.0, 1.0)
        assert st.peak_price == 112.0  # 不回退

    def test_no_position(self):
        st = make_exit_state("BTCUSDT", 100.0)
        a = update_exit(st, 110.0, 0.0)
        assert a["action"] == "hold"
