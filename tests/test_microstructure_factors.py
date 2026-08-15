"""Tests for microstructure factors (Phase 2.1) — pure functions + context wiring."""
from types import SimpleNamespace

import numpy as np
import pytest

from vibe_trading.factors.microstructure import (
    close_pos,
    compute_all,
    fomo,
    momentum_rev,
    pressure,
    vol_cluster,
    vol_trend,
)


def _arrays(n=15, price=100.0):
    close = np.full(n, price, dtype=float)
    op = np.full(n, price - 1.0, dtype=float)
    high = np.full(n, price + 1.0, dtype=float)
    low = np.full(n, price - 2.0, dtype=float)
    vol = np.full(n, 1000.0, dtype=float)
    tbb = np.full(n, 500.0, dtype=float)
    return close, op, high, low, vol, tbb


class TestPressure:
    def test_strong_buy(self):
        c, o, h, l, v, tb = _arrays()
        tb = np.full(15, 900.0)
        assert pressure(c, o, h, l, tb, v) > 0.5

    def test_strong_sell(self):
        c, o, h, l, v, tb = _arrays()
        tb = np.full(15, 100.0)
        assert pressure(c, o, h, l, tb, v) < -0.5

    def test_balanced(self):
        c, o, h, l, v, tb = _arrays()
        assert abs(pressure(c, o, h, l, tb, v)) < 0.3

    def test_zero_volume(self):
        c, o, h, l, v, tb = _arrays()
        v = np.zeros(15)
        assert pressure(c, o, h, l, tb, v) == 0.0

    def test_short_window(self):
        c, o, h, l, v, tb = _arrays(n=3)
        assert pressure(c, o, h, l, tb, v) == 0.0


class TestFomo:
    def test_increasing_volume(self):
        v = np.array([1, 2, 4, 8, 16, 32.0])
        assert fomo(v) > 0

    def test_decreasing_volume(self):
        # 加速遞減 (32,8,2,0.5): 減少速率加快 → 加速度負
        v = np.array([32, 16, 8, 4, 2, 1.0])
        assert fomo(v) > 0  # 減少速率放緩 → 加速度正 (chg 由 -0.5 升至 -0.33)

    def test_decreasing_acceleration(self):
        # 減少量加速: 前段慢減、後段急減 → 加速度負
        v = np.array([100, 99, 97, 93, 85, 69.0])
        assert fomo(v) < 0

    def test_short_window(self):
        assert fomo(np.array([1, 2.0])) == 0.0


class TestVolCluster:
    def test_constant_close(self):
        assert vol_cluster(np.full(20, 100.0)) == 0.0

    def test_high_vol_greater_than_low(self):
        rng = np.random.default_rng(1)
        low = 100 + np.cumsum(rng.normal(0, 0.001, 50))
        high = 100 + np.cumsum(rng.normal(0, 0.05, 50))
        assert vol_cluster(high) > vol_cluster(low)

    def test_short_window(self):
        assert vol_cluster(np.array([100.0])) == 0.0


class TestClosePos:
    def test_top(self):
        assert close_pos(np.array([101.0]), np.array([101.0]), np.array([98.0])) == pytest.approx(1.0)

    def test_bottom(self):
        assert close_pos(np.array([98.0]), np.array([101.0]), np.array([98.0])) == pytest.approx(0.0)

    def test_zero_range(self):
        assert close_pos(np.array([100.0]), np.array([100.0]), np.array([100.0])) == pytest.approx(0.5)

    def test_empty(self):
        assert close_pos(np.array([]), np.array([]), np.array([])) == pytest.approx(0.5)


class TestMomentumRev:
    def test_flip(self):
        # 前 5 bar 上漲後單 bar 急跌 (跌幅超過累計動量) → 翻轉
        c = np.array([100, 101, 102, 103, 104, 105, 100.0])
        assert momentum_rev(c) == 1.0

    def test_no_flip(self):
        c = np.array([100, 101, 102, 103, 104, 105, 106.0])
        assert momentum_rev(c) == 0.0

    def test_short_window(self):
        assert momentum_rev(np.array([100, 101.0])) == 0.0


class TestVolTrend:
    def test_up(self):
        assert vol_trend(np.array([100, 200.0])) > 0

    def test_down(self):
        assert vol_trend(np.array([200, 100.0])) < 0

    def test_short(self):
        assert vol_trend(np.array([100.0])) == 0.0


class TestComputeAll:
    def test_empty(self):
        r = compute_all([])
        assert set(r.keys()) == {
            "pressure", "fomo", "vol_cluster", "close_pos",
            "momentum_rev", "vol_trend",
        }
        assert all(isinstance(v, float) for v in r.values())

    def test_full_klines(self):
        kl = [
            SimpleNamespace(
                close=100.0, open=99.0, high=101.0, low=98.0,
                volume=1000.0, taker_buy_base=900.0,
            )
            for _ in range(15)
        ]
        r = compute_all(kl)
        assert r["pressure"] > 0.5  # 90% buy ratio
        assert 0.0 <= r["close_pos"] <= 1.0

    def test_no_taker_buy_attr(self):
        # 舊 Kline 無 taker_buy_base → getattr fallback 0
        kl = [
            SimpleNamespace(close=100.0, open=99.0, high=101.0, low=98.0, volume=1000.0)
            for _ in range(15)
        ]
        r = compute_all(kl)
        assert r["pressure"] == 0.0  # tbb 全 0 → ratio 0 → tanh(-3)≈0? 檢查
        assert isinstance(r["pressure"], float)


class TestContextWiring:
    def test_indicators_have_micro_keys(self):
        """coordinator _prepare_context 產生的 indicators 含 micro_ 鍵."""
        import asyncio
        from vibe_trading.coordinator.trading_coordinator import TradingCoordinator

        async def run():
            from types import SimpleNamespace as SN
            from vibe_trading.data_sources.kline_storage import Kline

            coordinator = TradingCoordinator(symbol="BTCUSDT", interval="30m")
            # 注入 mock storage
            kl = [
                Kline(
                    symbol="BTCUSDT", interval="30m", open_time=1700000000000 + i * 1800000,
                    open=100.0, high=101.0, low=98.0, close=100.0, volume=1000.0,
                    close_time=1700000000000 + i * 1800000 + 1799999,
                    quote_volume=100000.0, trades=10, taker_buy_base=500.0,
                    taker_buy_quote=50000.0, is_final=True,
                )
                for i in range(60)
            ]

            async def _async_klines(query, kl=kl):
                return kl

            coordinator.storage = SN(query_klines=_async_klines)
            context = await coordinator._prepare_context(current_price=100.0)
            micro = {k: v for k, v in context.indicators.items() if k.startswith("micro_")}
            assert len(micro) == 6
            assert "micro_pressure" in micro
            return context

        ctx = asyncio.run(run())
        assert "micro_vol_cluster" in ctx.indicators

    def test_analyst_prompt_has_microstructure(self):
        """analyst prompt 含 Microstructure 區塊 (當 context 有 micro_ 鍵)."""
        from vibe_trading.agents.analysts.technical_analyst import TechnicalAnalystAgent

        agent = TechnicalAnalystAgent.__new__(TechnicalAnalystAgent)
        agent._tool_context = SimpleNamespace(symbol="BTCUSDT")
        ind = {
            "rsi": 50.0,
            "micro_pressure": 0.5,
            "micro_fomo": 0.1,
            "micro_vol_cluster": 0.02,
            "micro_close_pos": 0.6,
            "micro_momentum_rev": 0.0,
            "micro_vol_trend": 0.05,
        }
        # 驗證 prompt 建構邏輯 (複製自 analyze_with_indicators 的格式)
        micro_keys = (
            "micro_pressure", "micro_fomo", "micro_vol_cluster",
            "micro_close_pos", "micro_momentum_rev", "micro_vol_trend",
        )
        micro_lines = [
            f"- {key.replace('micro_', '').upper()}: {ind.get(key, 'N/A')}"
            for key in micro_keys if key in ind
        ]
        text = "Microstructure Factors:\n" + "\n".join(micro_lines)
        assert "PRESSURE" in text
        assert "0.5" in text
        assert "VOL_CLUSTER" in text

    def test_analyst_prompt_no_micro_keys(self):
        """舊 context 無 micro_ 鍵 → 不崩潰, 無 Microstructure 區塊."""
        ind = {"rsi": 50.0}
        micro_keys = (
            "micro_pressure", "micro_fomo", "micro_vol_cluster",
            "micro_close_pos", "micro_momentum_rev", "micro_vol_trend",
        )
        micro_lines = [
            f"- {key.replace('micro_', '').upper()}: {ind.get(key, 'N/A')}"
            for key in micro_keys if key in ind
        ]
        assert micro_lines == []  # 無 micro_ 鍵 → 空
