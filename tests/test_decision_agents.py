"""Tests for decision agents pure methods (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.agents.decision.decision_agents import (
    PortfolioManagerAgent,
    TraderAgent,
)
from vibe_trading.agents.decision.trading_tools import (
    ExecutionStyle,
    PositionSide,
    TradingPlan,
)


def _trading_plan(direction: str = "LONG") -> TradingPlan:
    return TradingPlan(
        symbol="BTCUSDT", position_side=PositionSide.LONG, direction=direction,
        execution_style=ExecutionStyle.IMMEDIATE,
        entry_orders=[{"order_type": "market", "price": 50000, "pct": 100, "note": "市價"}],
        total_position_usdt=1000.0, total_position_coin=0.02, leverage=5,
        stop_loss_orders=[{"trigger_price": 49000, "note": "硬止損"}],
        take_profit_orders=[{"price": 52000, "pct": 50, "note": "止盈1"}],
        max_loss_usdt=100.0, max_loss_pct=10.0, risk_reward_ratio=2.0,
    )


class TestTraderRiskPreference:
    def test_conservative(self):
        t = TraderAgent()
        assert t._determine_risk_preference(
            {"conservative_1": "保守", "conservative_2": "保守"}) == "conservative"

    def test_aggressive(self):
        t = TraderAgent()
        assert t._determine_risk_preference(
            {"aggressive_1": "激进", "aggressive_2": "激进"}) == "aggressive"

    def test_mixed_moderate(self):
        t = TraderAgent()
        assert t._determine_risk_preference(
            {"neutral_1": "中性", "neutral_2": "中性"}) == "moderate"

    def test_empty_default_moderate(self):
        t = TraderAgent()
        assert t._determine_risk_preference({}) == "moderate"


class TestTraderPrompt:
    def test_build_prompt_contains_plan(self):
        t = TraderAgent()
        t._tool_context = MagicMock()
        t._tool_context.symbol = "BTCUSDT"
        prompt = t._build_trading_plan_prompt(
            _trading_plan(), "BUY 建議", {"conservative": "低風險"},
        )
        assert "BTCUSDT" in prompt
        assert "LONG" in prompt
        assert "plan_approved" in prompt

    def test_build_prompt_stop_loss(self):
        t = TraderAgent()
        t._tool_context = MagicMock()
        t._tool_context.symbol = "BTCUSDT"
        prompt = t._build_trading_plan_prompt(
            _trading_plan(), "建議", {},
        )
        assert "49000" in prompt  # 止損價格


class TestPMJsonable:
    def test_pydantic_model(self):
        pm = PortfolioManagerAgent()
        v = MagicMock()
        v.model_dump.return_value = {"a": 1}
        assert pm._to_jsonable(v) == {"a": 1}

    def test_dict_recursive(self):
        pm = PortfolioManagerAgent()
        assert pm._to_jsonable({"k": {"nested": "v"}}) == {"k": {"nested": "v"}}

    def test_list(self):
        pm = PortfolioManagerAgent()
        assert pm._to_jsonable([1, "two", 3.0]) == [1, "two", 3.0]

    def test_enum_value(self):
        pm = PortfolioManagerAgent()
        v = PositionSide.LONG
        assert pm._to_jsonable(v) == "long"

    def test_plain_value(self):
        pm = PortfolioManagerAgent()
        assert pm._to_jsonable(42) == 42


class TestPMMemorySection:
    def test_no_memory_returns_empty(self):
        pm = PortfolioManagerAgent()
        pm._memory = None
        pm._tool_context = MagicMock()
        assert pm._build_memory_section(MagicMock()) == ""

    def test_memory_no_results(self):
        pm = PortfolioManagerAgent()
        mem = MagicMock()
        mem.retrieve_relevant.return_value = []
        mem.get_cross_ticker_lessons.return_value = []
        pm._memory = mem
        pm._tool_context = MagicMock()
        assert pm._build_memory_section(MagicMock()) == ""

    def test_memory_with_lessons(self):
        pm = PortfolioManagerAgent()
        mem = MagicMock()
        mem.retrieve_relevant.return_value = ["lesson1"]
        mem.get_cross_ticker_lessons.return_value = []
        pm._memory = mem
        pm._tool_context = MagicMock()
        from vibe_trading.config.settings import get_settings
        sc = MagicMock()
        sc.recommended_action = "BUY"
        sc.rationale = "看漲"
        section = pm._build_memory_section(sc)
        assert "lesson1" in section

    def test_memory_with_cross(self):
        pm = PortfolioManagerAgent()
        mem = MagicMock()
        mem.retrieve_relevant.return_value = ["l1"]
        mem.get_cross_ticker_lessons.return_value = ["cross1"]
        pm._memory = mem
        pm._tool_context = MagicMock()
        sc = MagicMock()
        sc.recommended_action = "BUY"
        sc.rationale = "看漲"
        section = pm._build_memory_section(sc)
        assert "CROSS-TICKER" in section


class TestPMDecision:
    @pytest.mark.asyncio
    async def test_make_final_decision_not_initialized(self):
        pm = PortfolioManagerAgent()
        pm._agent = None
        with pytest.raises(RuntimeError):
            await pm.make_final_decision({}, "", _trading_plan(), {}, [], 0, 0)

    @pytest.mark.asyncio
    async def test_make_final_decision_hold(self):
        pm = PortfolioManagerAgent()
        pm._agent = MagicMock()
        pm._decision_framework = MagicMock()
        sc = MagicMock()
        sc.recommended_action = "HOLD"
        sc.rationale = "觀望"
        pm._decision_framework.calculate_decision_scorecard.return_value = sc
        result = await pm.make_final_decision(
            {}, "plan", _trading_plan(), {}, [], 10000, 50000)
        assert result["execution_plan"] is None
        assert "HOLD" in result["decision_text"]

    @pytest.mark.asyncio
    async def test_make_final_decision_llm_path(self):
        """BUY 決策 → LLM 生成 decision_text."""
        pm = PortfolioManagerAgent()
        pm._agent = MagicMock()
        pm.config = MagicMock()
        pm.config.name = "PM"
        pm._decision_framework = MagicMock()
        sc = MagicMock()
        sc.recommended_action = "BUY"
        sc.rationale = "看漲"
        sc.to_dict.return_value = {"action": "BUY"}
        sc.confidence = 0.8
        pm._decision_framework.calculate_decision_scorecard.return_value = sc
        pm._decision_framework.record_decision = MagicMock()
        # agent state messages 含 assistant 回應
        from pi_agent_core.types import TextContent
        pm._agent.state.messages = [
            MagicMock(role="assistant", content=[TextContent(text="Decision: BUY\nRationale: 突破")]),
        ]
        with patch.object(pm, "_build_decision_prompt", return_value="prompt"), \
             patch("vibe_trading.agents.decision.decision_agents.prompt_with_timeout",
                   new=AsyncMock(return_value=True)), \
             patch("vibe_trading.agents.decision.decision_agents.parse_structured_output",
                   return_value=None):
            result = await pm.make_final_decision(
                {"technical": "看漲"}, "plan", _trading_plan(), {}, [], 10000, 50000)
        assert result["decision_text"] == "Decision: BUY\nRationale: 突破"
        assert result["execution_plan"] is not None  # total_position_usdt > 0


class TestBuildDecisionPrompt:
    def test_build_prompt_contains_context(self):
        from vibe_trading.agents.decision.decision_agents import PortfolioManagerAgent
        pm = PortfolioManagerAgent()
        pm._tool_context = MagicMock()
        pm._tool_context.symbol = "BTCUSDT"
        sc = MagicMock()
        sc.recommended_action = "BUY"
        sc.confidence = 0.8
        sc.supporting_factors = ["技術面"]
        sc.risk_factors = ["波動大"]
        prompt = pm._build_decision_prompt(
            scorecard=sc, analyst_reports={"technical": "看漲"},
            investment_plan="BUY plan", trading_plan=_trading_plan(),
            risk_debate={"neutral": "低風險"},
            current_positions=[], account_balance=10000, current_price=50000,
        )
        assert "BTCUSDT" in prompt
        assert "BUY" in prompt

    def test_build_prompt_no_analysts(self):
        from vibe_trading.agents.decision.decision_agents import PortfolioManagerAgent
        pm = PortfolioManagerAgent()
        pm._tool_context = MagicMock()
        pm._tool_context.symbol = "BTCUSDT"
        sc = MagicMock()
        sc.recommended_action = "HOLD"
        sc.confidence = 0.5
        sc.supporting_factors = []
        sc.risk_factors = []
        prompt = pm._build_decision_prompt(
            scorecard=sc, analyst_reports={}, investment_plan="",
            trading_plan=_trading_plan(), risk_debate={},
            current_positions=[], account_balance=0, current_price=0,
        )
        assert "BTCUSDT" in prompt


class TestTraderPlan:
    @pytest.mark.asyncio
    async def test_create_trading_plan_full(self):
        from vibe_trading.agents.decision.decision_agents import TraderAgent
        t = TraderAgent()
        t._tool_context = MagicMock()
        t._tool_context.symbol = "BTCUSDT"
        # mock calculators
        t._stop_loss_calculator = MagicMock()
        t._stop_loss_calculator.calculate_levels = MagicMock(return_value={
            "stop_loss_price": 49000.0,
            "risk_reward_ratio": 2.0,
            "partial_take_profits": [
                {"price": 52000.0, "size_pct": 50, "level": 1}],
            "trailing_stop_config": {"enabled": True},
        })
        t._position_size_calculator = MagicMock()
        t._position_size_calculator.calculate_position_size = MagicMock(
            return_value={
                "position_size_coin": 0.02, "position_size_usdt": 1000.0,
                "leverage": 5, "risk_amount_usdt": 100.0,
                "stop_distance_pct": 10.0,
            })
        t._execution_strategy_calculator = MagicMock()
        t._execution_strategy_calculator.determine_execution_style = MagicMock(
            return_value={"execution_style": ExecutionStyle.IMMEDIATE,
                          "entry_orders": [{"order_type": "market"}],
                          "reasoning": "fast"})
        t._execution_strategy_calculator.build_entry_orders = MagicMock(
            return_value=[{"order_type": "market", "price": 50000.0, "pct": 100, "note": "市價"}])
        # agent
        agent = MagicMock()
        assistant = MagicMock()
        assistant.role = "assistant"
        assistant.content = [MagicMock()]
        assistant.content[0].text = '{"plan_approved": true}'
        agent.state.messages = [assistant]
        t._agent = agent
        from vibe_trading.agents.decision import decision_agents as da
        with patch.object(da, "prompt_with_timeout",
                          new=AsyncMock(return_value=True)), \
             patch.object(da, "parse_structured_output",
                          return_value=MagicMock(plan_approved=True)):
            plan = await t.create_trading_plan(
                direction="LONG",
                investment_recommendation="buy",
                risk_assessment={"conservative": "低風險"},
                current_price=50000.0,
                account_balance=10000.0,
            )
        assert plan.symbol == "BTCUSDT"
        assert plan.position_side == PositionSide.LONG
        assert plan.total_position_coin == 0.02
        assert plan.structured_analysis is not None

    @pytest.mark.asyncio
    async def test_create_trading_plan_timeout_fallback(self):
        from vibe_trading.agents.decision.decision_agents import TraderAgent
        t = TraderAgent()
        t._tool_context = MagicMock()
        t._tool_context.symbol = "BTCUSDT"
        t._stop_loss_calculator = MagicMock()
        t._stop_loss_calculator.calculate_levels = MagicMock(return_value={
            "stop_loss_price": 49000.0, "risk_reward_ratio": 2.0,
            "partial_take_profits": [], "trailing_stop_config": {}})
        t._position_size_calculator = MagicMock()
        t._position_size_calculator.calculate_position_size = MagicMock(
            return_value={"position_size_coin": 0.02, "position_size_usdt": 1000.0,
                          "leverage": 5, "risk_amount_usdt": 100.0,
                          "stop_distance_pct": 10.0})
        t._execution_strategy_calculator = MagicMock()
        t._execution_strategy_calculator.determine_execution_style = MagicMock(
            return_value={"execution_style": ExecutionStyle.IMMEDIATE,
                          "entry_orders": [], "reasoning": "fast"})
        t._execution_strategy_calculator.build_entry_orders = MagicMock(
            return_value=[])
        agent = MagicMock()
        agent.state.messages = []
        t._agent = agent
        from vibe_trading.agents.decision import decision_agents as da
        with patch.object(da, "prompt_with_timeout",
                          new=AsyncMock(return_value=False)):
            plan = await t.create_trading_plan(
                direction="SHORT",
                investment_recommendation="sell",
                risk_assessment={},
                current_price=50000.0,
                account_balance=10000.0,
            )
        assert plan.direction == "SHORT"
        assert plan.position_side == PositionSide.SHORT

    @pytest.mark.asyncio
    async def test_create_trading_plan_not_initialized(self):
        from vibe_trading.agents.decision.decision_agents import TraderAgent
        t = TraderAgent()
        with pytest.raises(RuntimeError):
            await t.create_trading_plan("LONG", "r", {}, 100.0, 1000.0)
