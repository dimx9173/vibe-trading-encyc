"""Tests for StackVM (Phase 2.2) — operators, evaluator, compose_factor tool."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from vibe_trading.factors.vm import ARITY, evaluate_formula


def _series():
    return {
        "a": np.array([1.0, 2, 3, 4, 5]),
        "b": np.array([5.0, 4, 3, 2, 1]),
        "vol": np.array([0.01, 0.02, 0.5, 0.01, 0.02]),
    }


class TestArithmetic:
    def test_add(self):
        assert evaluate_formula(["ADD", "a", "b"], _series()) == pytest.approx(6.0)

    def test_sub(self):
        assert evaluate_formula(["SUB", "a", "b"], _series()) == pytest.approx(4.0)

    def test_mul(self):
        assert evaluate_formula(["MUL", "a", 2], _series()) == pytest.approx(10.0)

    def test_div(self):
        assert evaluate_formula(["DIV", "a", 2], _series()) == pytest.approx(2.5, abs=1e-3)

    def test_div_eps_guard(self):
        # 除 0 → 大數非 NaN
        result = evaluate_formula(["DIV", "a", 0], _series())
        assert result is not None
        assert np.isfinite(result)


class TestUnary:
    def test_neg(self):
        assert evaluate_formula(["NEG", "a"], _series()) == pytest.approx(-5.0)

    def test_abs(self):
        s = _series()
        s["neg"] = np.array([-1.0, -2, -3, -4, -5])
        assert evaluate_formula(["ABS", "neg"], s) == pytest.approx(5.0)

    def test_sign(self):
        s = _series()
        s["mix"] = np.array([-1.0, 0, 2, -3, 4])
        assert evaluate_formula(["SIGN", "mix"], s) == pytest.approx(1.0)


class TestConditional:
    def test_gate_positive_cond(self):
        # vol 最後值 0.02 > 0 → 選 a (5.0)
        assert evaluate_formula(["GATE", "vol", "a", "b"], _series()) == pytest.approx(5.0)

    def test_gate_negative_cond(self):
        s = _series()
        s["neg_vol"] = np.array([0.01, 0.02, -0.5, 0.01, -0.02])
        # 最後值 -0.02 ≤ 0 → 選 b (1.0)
        assert evaluate_formula(["GATE", "neg_vol", "a", "b"], s) == pytest.approx(1.0)

    def test_jump_normal(self):
        # vol 無 Z>3 → 0
        assert evaluate_formula(["JUMP", "vol"], _series()) == pytest.approx(0.0)

    def test_jump_extreme(self):
        s = _series()
        # 50 個常數點 + 1 個離群 → sd 收斂, Z>3
        s["spike"] = np.array([1.0] * 50 + [100.0])
        assert evaluate_formula(["JUMP", "spike"], s) == pytest.approx(1.0)


class TestTimeseries:
    def test_decay(self):
        # a=[1,2,3,4,5]: last = 5 + 0.8*4 + 0.6*3 = 10.0
        assert evaluate_formula(["DECAY", "a"], _series()) == pytest.approx(10.0)

    def test_delay1(self):
        assert evaluate_formula(["DELAY1", "a"], _series()) == pytest.approx(4.0)

    def test_max3(self):
        assert evaluate_formula(["MAX3", "a"], _series()) == pytest.approx(5.0)


class TestEvaluator:
    def test_nested_ast(self):
        # ["MUL", ["ADD", "a", "b"], "a"] = (5+1)*5 = 30
        assert evaluate_formula(["MUL", ["ADD", "a", "b"], "a"], _series()) == pytest.approx(30.0)

    def test_deep_nested(self):
        # ["GATE", ["SUB", "vol", 0.01], ["ADD", "a", "b"], 0]
        ast = ["GATE", ["SUB", "vol", 0.01], ["ADD", "a", "b"], 0]
        # vol last 0.02-0.01=0.01 > 0 → a+b = 6
        assert evaluate_formula(ast, _series()) == pytest.approx(6.0)

    def test_invalid_op(self):
        assert evaluate_formula(["FOO", "a", "b"], _series()) is None

    def test_wrong_arity(self):
        assert evaluate_formula(["GATE", "a", "b"], _series()) is None

    def test_unknown_series(self):
        assert evaluate_formula(["ADD", "a", "zzz"], _series()) is None

    def test_empty_series(self):
        assert evaluate_formula(["ADD", "a", "b"], {}) is None

    def test_nan_result(self):
        s = _series()
        s["nan_s"] = np.array([np.nan, np.nan, np.nan, np.nan, np.nan])
        assert evaluate_formula(["ADD", "nan_s", "a"], s) is None

    def test_arity_table(self):
        assert ARITY == {
            "ADD": 2, "SUB": 2, "MUL": 2, "DIV": 2,
            "NEG": 1, "ABS": 1, "SIGN": 1,
            "GATE": 3, "JUMP": 1, "DECAY": 1, "DELAY1": 1, "MAX3": 1,
        }


class TestComposeFactorTool:
    @pytest.mark.asyncio
    async def test_tool_with_storage(self):
        from vibe_trading.agents.agent_tools import create_compose_factor_tool
        from vibe_trading.data_sources.kline_storage import Kline
        from vibe_trading.agents.agent_tools import ComposeFactorParams

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
        storage = SimpleNamespace(query_klines=AsyncMock(return_value=kl))
        tool_context = SimpleNamespace(storage=storage)
        tool = create_compose_factor_tool(tool_context)
        assert tool.name == "compose_factor"

        result = await tool.execute(
            "compose_factor",
            ComposeFactorParams(symbol="BTCUSDT", interval="30m",
                                formula=["ADD", "pressure", "close_pos"]),
        )
        text = result.content[0].text
        assert "result:" in text

    @pytest.mark.asyncio
    async def test_tool_no_storage(self):
        from vibe_trading.agents.agent_tools import create_compose_factor_tool
        from vibe_trading.agents.agent_tools import ComposeFactorParams

        tool = create_compose_factor_tool(SimpleNamespace(storage=None))
        result = await tool.execute(
            "compose_factor",
            ComposeFactorParams(symbol="BTCUSDT", interval="30m", formula=["ADD", "a", "b"]),
        )
        assert "N/A" in result.content[0].text

    @pytest.mark.asyncio
    async def test_tool_invalid_formula(self):
        from vibe_trading.agents.agent_tools import create_compose_factor_tool
        from vibe_trading.agents.agent_tools import ComposeFactorParams
        from vibe_trading.data_sources.kline_storage import Kline

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
        storage = SimpleNamespace(query_klines=AsyncMock(return_value=kl))
        tool = create_compose_factor_tool(SimpleNamespace(storage=storage))
        result = await tool.execute(
            "compose_factor",
            ComposeFactorParams(symbol="BTCUSDT", interval="30m", formula=["FOO", "a"]),
        )
        assert "公式無效" in result.content[0].text

    def test_technical_tools_helper(self):
        from vibe_trading.agents.agent_tools import get_technical_tools

        tools = get_technical_tools(SimpleNamespace(storage=None))
        assert len(tools) == 1
        assert tools[0].name == "compose_factor"
