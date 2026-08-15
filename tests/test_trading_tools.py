"""Tests for agents/decision/trading_tools (Wave D — coverage 85% plan).

計算器都是純邏輯 — 直接測數值正確性.
"""
import pytest

from vibe_trading.agents.decision.trading_tools import (
    DecisionFramework,
    ExecutionStrategyCalculator,
    ExecutionStyle,
    OrderType,
    PositionSide,
    PositionSizeCalculator,
    StopLossTakeProfitCalculator,
    TradingPlan,
)


class TestTradingPlan:
    def _plan(self):
        return TradingPlan(
            symbol="BTCUSDT",
            position_side=PositionSide.LONG,
            direction="LONG",
            execution_style=ExecutionStyle.IMMEDIATE,
            entry_orders=[{"order_type": "market", "price": 50000, "pct": 100, "note": "市價"}],
            total_position_usdt=1000.0,
            total_position_coin=0.02,
            leverage=5,
            stop_loss_orders=[{"trigger_price": 49000, "note": "硬止損"}],
            take_profit_orders=[{"price": 52000, "pct": 50, "note": "止盈1"}],
            max_loss_usdt=100.0,
            max_loss_pct=10.0,
            risk_reward_ratio=2.0,
            execution_notes=["測試"],
        )

    def test_to_dict(self):
        d = self._plan().to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert d["position_side"] == "long"
        assert d["leverage"] == 5

    def test_str_contains_sections(self):
        s = str(self._plan())
        assert "交易执行计划" in s
        assert "入场计划" in s
        assert "止损计划" in s
        assert "止盈计划" in s
        assert "盈亏比" in s

    def test_len(self):
        assert len(self._plan()) == len(str(self._plan()))


class TestPositionSizeCalculator:
    def test_moderate_risk(self):
        c = PositionSizeCalculator()
        r = c.calculate_position_size(
            account_balance=10000.0, entry_price=50000.0, stop_loss_price=49000.0,
            risk_preference="moderate",
        )
        # 2% risk = 200; 距離2% → risk_based = 10000; cap 30% = 3000
        assert r["position_size_usdt"] <= 3000.0
        assert r["risk_amount_usdt"] == 200.0
        assert r["leverage"] >= 1

    def test_conservative_risk(self):
        c = PositionSizeCalculator()
        r = c.calculate_position_size(
            account_balance=10000.0, entry_price=100.0, stop_loss_price=95.0,
            risk_preference="conservative",
        )
        assert r["risk_amount_usdt"] == 100.0  # 1%

    def test_kelly_fraction(self):
        c = PositionSizeCalculator()
        r = c.calculate_position_size(
            account_balance=10000.0, entry_price=100.0, stop_loss_price=98.0,
            kelly_fraction=0.1,
        )
        # kelly: 10000*0.1*0.5 = 500; risk_based: 200/0.02=10000 → min = 500
        assert r["position_size_usdt"] == 500.0

    def test_high_volatility_atr_reduces(self):
        c = PositionSizeCalculator()
        normal = c.calculate_position_size(
            account_balance=10000.0, entry_price=100.0, stop_loss_price=98.0)
        reduced = c.calculate_position_size(
            account_balance=10000.0, entry_price=100.0, stop_loss_price=98.0,
            current_atr=3.0)  # 3% ATR > 2%
        assert reduced["position_size_usdt"] < normal["position_size_usdt"]

    def test_reasoning_contains_preference(self):
        c = PositionSizeCalculator()
        r = c.calculate_position_size(
            account_balance=10000.0, entry_price=100.0, stop_loss_price=95.0,
            risk_preference="aggressive")
        assert "aggressive" in r["reasoning"]


class TestStopLossTakeProfit:
    def test_long_atr_based(self):
        c = StopLossTakeProfitCalculator()
        r = c.calculate_levels(100.0, PositionSide.LONG, atr=1.0)
        assert r["stop_loss_price"] == 98.0  # 2*ATR
        assert r["take_profit_price"] == 104.0  # 2*ATR*2
        assert len(r["partial_take_profits"]) == 3
        assert r["risk_reward_ratio"] == 2.0

    def test_short_fixed_pct(self):
        c = StopLossTakeProfitCalculator()
        r = c.calculate_levels(100.0, PositionSide.SHORT, atr=None,
                               volatility_adjusted=False)
        assert r["stop_loss_price"] == 102.0  # 2% 上方
        assert r["take_profit_price"] == 96.0  # 4% 下方

    def test_partial_profit_levels(self):
        c = StopLossTakeProfitCalculator()
        r = c.calculate_levels(100.0, PositionSide.LONG, atr=1.0)
        assert r["partial_take_profits"][0]["pct"] == 30
        assert r["partial_take_profits"][2]["price"] == r["take_profit_price"]


class TestExecutionStrategy:
    def test_high_urgency_market(self):
        c = ExecutionStrategyCalculator()
        r = c.determine_execution_style("LONG", 50000.0, urgency_level="high")
        assert r["execution_style"] == ExecutionStyle.IMMEDIATE
        assert r["order_type"] == OrderType.MARKET
        assert r["entry_orders"][0]["pct"] == 100

    def test_low_urgency_high_vol_scaled(self):
        c = ExecutionStrategyCalculator()
        r = c.determine_execution_style("LONG", 50000.0, volatility=0.05,
                                        urgency_level="low")
        assert r["execution_style"] == ExecutionStyle.SCALED_IN
        assert len(r["entry_orders"]) == 3

    def test_low_urgency_low_vol_patient(self):
        c = ExecutionStrategyCalculator()
        r = c.determine_execution_style("LONG", 50000.0, volatility=0.01,
                                        urgency_level="low")
        assert r["execution_style"] == ExecutionStyle.PATIENT_LIMIT

    def test_normal_wide_spread(self):
        c = ExecutionStrategyCalculator()
        r = c.determine_execution_style("LONG", 50000.0, spread_pct=0.2)
        assert r["execution_style"] == ExecutionStyle.AGGRESSIVE_LIMIT

    def test_normal_low_liquidity(self):
        c = ExecutionStrategyCalculator()
        r = c.determine_execution_style("LONG", 50000.0, volume_24h=100000)
        assert r["execution_style"] == ExecutionStyle.SCALED_IN
        assert len(r["entry_orders"]) == 2

    def test_normal_good_market(self):
        c = ExecutionStrategyCalculator()
        r = c.determine_execution_style("LONG", 50000.0, volume_24h=10**8)
        assert r["execution_style"] == ExecutionStyle.IMMEDIATE

    def test_build_entry_orders_market(self):
        c = ExecutionStrategyCalculator()
        orders = c.build_entry_orders("LONG", 50000.0, 1.0,
                                      [{"type": "market", "pct": 100, "note": "n"}])
        assert orders[0]["price"] == 50000.0
        assert orders[0]["size_coin"] == 1.0

    def test_build_entry_orders_limit_long(self):
        c = ExecutionStrategyCalculator()
        orders = c.build_entry_orders("LONG", 50000.0, 1.0,
                                      [{"type": "limit", "price_offset_pct": -1.0, "pct": 50, "note": "n"}])
        assert orders[0]["price"] == 49500.0  # 50000 * (1 - 1/100)

    def test_build_entry_orders_limit_short(self):
        c = ExecutionStrategyCalculator()
        orders = c.build_entry_orders("SHORT", 50000.0, 1.0,
                                      [{"type": "limit", "price_offset_pct": -1.0, "pct": 50, "note": "n"}])
        assert orders[0]["price"] == 50500.0  # SHORT 方向相反


class TestDecisionFramework:
    def _framework(self):
        return DecisionFramework()

    def test_bullish_scorecard(self):
        f = self._framework()
        sc = f.calculate_decision_scorecard(
            analyst_reports={"technical": "看漲 80分", "fundamental": "看漲 70分",
                             "sentiment": "正面"},
            research_recommendation={"action": "BUY"},
            risk_assessment={"risk_level": "low"},
            current_market_data={},
        )
        assert sc.overall_score >= 55
        assert sc.recommended_action in ("STRONG_BUY", "BUY")
        assert sc.to_dict()["overall_score"] == sc.overall_score

    def test_bearish_scorecard(self):
        f = self._framework()
        sc = f.calculate_decision_scorecard(
            analyst_reports={"technical": "看跌 30分", "fundamental": "看跌 20分",
                             "sentiment": "恐惧"},
            research_recommendation={"action": "SELL"},
            risk_assessment={"risk_level": "high"},
            current_market_data={},
        )
        assert sc.overall_score < 50
        assert sc.recommended_action != "BUY"

    def test_neutral_scorecard(self):
        f = self._framework()
        sc = f.calculate_decision_scorecard(
            analyst_reports={},
            research_recommendation={},
            risk_assessment={},
            current_market_data={},
        )
        # 全部中性: 50*0.3+50*0.25+50*0.2+50*0.15+70*0.1 = 52 (risk medium=70)
        assert 50 <= sc.overall_score <= 55
        assert sc.recommended_action == "WEAK_BUY"

    def test_str_scorecard(self):
        f = self._framework()
        sc = f.calculate_decision_scorecard({}, {}, {}, {})
        assert "决策评分卡" in str(sc)
