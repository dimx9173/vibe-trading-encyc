"""Tests for Alpha Mining (Phase 3) — miner, screener, vm.evaluate_series."""
from types import SimpleNamespace

import numpy as np

from vibe_trading.factors.miner import _random_ast, crossover, evolve, mutate
from vibe_trading.factors.screener import make_screener, passes_gate, score_formula
from vibe_trading.factors.vm import evaluate_series


def _klines(n=60, seed=42):
    rng = np.random.default_rng(seed)
    prices = 100 + np.cumsum(rng.normal(0.001, 0.02, n))
    return [
        SimpleNamespace(
            open=float(prices[i] * 0.999), high=float(prices[i] * 1.01),
            low=float(prices[i] * 0.99), close=float(prices[i]),
            volume=1000.0, taker_buy_base=500.0,
        )
        for i in range(n)
    ]


class TestMiner:
    def test_random_ast_depth(self):
        import random
        ast = _random_ast(["close", "vol", "ret"], rng=random.Random(1))
        def depth(n):
            return 0 if not isinstance(n, list) else 1 + max(depth(x) for x in n[1:])
        assert depth(ast) <= 4

    def test_mutate_changes(self):
        import random
        ast = _random_ast(["close", "vol"], rng=random.Random(1))
        m = mutate(ast, ["close", "vol"], rng=random.Random(2))
        assert ast != m

    def test_crossover(self):
        import random
        a = _random_ast(["close", "vol"], rng=random.Random(3))
        b = _random_ast(["close", "vol"], rng=random.Random(4))
        c = crossover(a, b, rng=random.Random(5))
        assert c is not None

    def test_evolve_returns_top10(self):
        def fitness(ast):
            return -1.0  # 全同 → 排序穩定

        res = evolve(["close", "vol"], fitness, population=20, generations=2, seed=42, top_k=10)
        assert len(res) == 10

    def test_evolve_deterministic(self):
        def fitness(ast):
            return -1.0
        r1 = evolve(["close"], fitness, population=10, generations=2, seed=7, top_k=3)
        r2 = evolve(["close"], fitness, population=10, generations=2, seed=7, top_k=3)
        assert r1 == r2

    def test_evolve_skips_none_fitness(self):
        def fitness(ast):
            return None  # 全部淘汰

        res = evolve(["close"], fitness, population=10, generations=1, seed=1, top_k=5)
        assert res == []  # 無有效候選


class TestScreener:
    def test_series_shape(self):
        s = make_screener(_klines(n=60))
        assert len(s["series"]["close"]) == 60
        assert len(s["fwd"]) == 60
        assert "ret" in s["series"]
        assert "micro_pressure" in s["series"]

    def test_forward_return_no_lookahead(self):
        s = make_screener(_klines(n=60))
        assert s["fwd"][-1] == 0.0  # 最後 bar 無未來
        assert np.any(s["fwd"] != 0.0)  # 有非零 forward return

    def test_score_valid_formula(self):
        s = make_screener(_klines(n=60))
        sc = score_formula(["SUB", "ret", "micro_close_pos"], s["series"], s["fwd"])
        assert sc is not None
        assert "ic" in sc and "sharpe" in sc and "samples" in sc
        assert -1.0 <= sc["ic"] <= 1.0

    def test_score_invalid_formula(self):
        s = make_screener(_klines(n=60))
        assert score_formula(["FOO", "a"], s["series"], s["fwd"]) is None
        assert score_formula(["ADD", "a", "zzz"], s["series"], s["fwd"]) is None

    def test_score_small_samples(self):
        s = make_screener(_klines(n=15))
        sc = score_formula(["ADD", "close", "vol"], s["series"], s["fwd"], min_samples=20)
        assert sc is None  # 樣本不足

    def test_passes_gate(self):
        assert passes_gate(None) is False
        assert passes_gate({"ic": 0.06, "sharpe": 0.5, "samples": 50}, 0.05) is True
        assert passes_gate({"ic": 0.03, "sharpe": 0.5, "samples": 50}, 0.05) is False
        assert passes_gate({"ic": 0.06, "sharpe": -0.5, "samples": 50}, 0.05) is False


class TestEvaluateSeries:
    def test_full_series(self):
        s = make_screener(_klines(n=60))
        series = s["series"]
        f = evaluate_series(["SUB", "ret", "micro_close_pos"], series)
        assert f is not None
        assert f.shape == (60,)
        assert np.isfinite(f).all()

    def test_invalid_returns_none(self):
        s = make_screener(_klines(n=60))
        assert evaluate_series(["FOO", "a"], s["series"]) is None
