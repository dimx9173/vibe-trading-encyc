"""Tests for DebateAnalyzer (Wave D — coverage 85% plan)."""
import pytest

from vibe_trading.agents.researchers.debate_analyzer import (
    Argument,
    ArgumentCategory,
    ArgumentExtractor,
    ArgumentStrength,
    DebateEvaluator,
    InvestmentRecommendation,
)


class TestArgumentExtractor:
    def test_extract_bull_technical(self):
        ex = ArgumentExtractor()
        args = ex.extract_arguments(
            "RSI 顯示超買，但 MACD 金叉確認上升趨勢。數據顯示強烈突破阻力位，歷史新高。",
            "bull",
        )
        assert len(args) >= 1
        assert args[0].content  # 非空
        assert args[0].category in ArgumentCategory

    def test_extract_bear_fundamental(self):
        ex = ArgumentExtractor()
        args = ex.extract_arguments(
            "基本面惡化，營收下降，監管風險上升。可能導致崩盤，需要謹慎。",
            "bear",
        )
        assert len(args) >= 1

    def test_extract_empty_text(self):
        ex = ArgumentExtractor()
        assert ex.extract_arguments("", "bull") == []

    def test_extract_filler_filtered(self):
        ex = ArgumentExtractor()
        # 純客套話 → 過濾
        args = ex.extract_arguments("我認為", "bull")
        assert args == []

    def test_split_sentences(self):
        ex = ArgumentExtractor()
        sentences = ex._split_into_sentences("这是一个足够长的句子有实质内容。这也是另一个足够长的句子。")
        assert len(sentences) == 2

    def test_is_substantive(self):
        ex = ArgumentExtractor()
        assert ex._is_substantive("這是一個足夠長的實質內容句子超過十五字")
        assert not ex._is_substantive("短句")

    def test_classify_technical_default(self):
        ex = ArgumentExtractor()
        assert ex._classify_argument("隨機文字沒有類別") == ArgumentCategory.TECHNICAL

    def test_classify_fundamental(self):
        ex = ArgumentExtractor()
        assert ex._classify_argument("基本面良好市值增長營收上升") == ArgumentCategory.FUNDAMENTAL

    def test_assess_strength_very_strong(self):
        ex = ArgumentExtractor()
        s = ex._assess_strength("明確突破歷史新高，數據顯示大幅上漲", "bull")
        assert s == ArgumentStrength.VERY_STRONG

    def test_assess_strength_weak(self):
        ex = ArgumentExtractor()
        s = ex._assess_strength("可能也许大概会涨", "bull")
        assert s in (ArgumentStrength.WEAK, ArgumentStrength.VERY_WEAK)

    def test_has_evidence(self):
        ex = ArgumentExtractor()
        assert ex._has_evidence("数据显示上涨") is True
        assert ex._has_evidence("單純看法") is False

    def test_extract_data_indicators(self):
        ex = ArgumentExtractor()
        indicators = ex._extract_data_indicators("漲幅 5.5%，RSI 70，價格 45000 USDT")
        assert "%" in indicators[0] or "5.5%" in indicators
        assert any("RSI=70" == i for i in indicators)

    def test_extract_key_points(self):
        ex = ArgumentExtractor()
        points = ex._extract_key_points("比特幣 突破 阻力位 強勢 上漲")
        assert len(points) <= 5
        assert "比特幣" in points

    def test_assess_confidence_strong_evidence(self):
        ex = ArgumentExtractor()
        c = ex._assess_confidence("強烈看漲", ArgumentStrength.STRONG, evidence_based=True)
        assert c >= 0.75

    def test_assess_confidence_weak(self):
        ex = ArgumentExtractor()
        c = ex._assess_confidence("可能下跌", ArgumentStrength.VERY_WEAK, evidence_based=False)
        assert c == 0.15

    def test_argument_to_dict(self):
        a = Argument(
            content="測試論點", category=ArgumentCategory.TECHNICAL,
            strength=ArgumentStrength.MODERATE, confidence=0.5,
            evidence_based=False, data_mentioned=[], key_points=[],
            timestamp=__import__("datetime").datetime(2026, 1, 1),
        )
        d = a.to_dict()
        assert d["content"] == "測試論點"
        assert d["category"] == "technical"


class TestDebateEvaluator:
    def test_evaluate_debate(self):
        ev = DebateEvaluator()
        bull = "MACD 金叉確認，數據顯示強烈突破阻力位，歷史新高確認上升趨勢。"
        bear = "基本面惡化，營收下降，監管風險上升，可能導致下跌。"
        result = ev.evaluate_debate(
            bull_messages=[bull], bear_messages=[bear],
        )
        assert result is not None
        assert hasattr(result, "bull_score") or isinstance(result, dict)

    def test_evaluate_empty(self):
        ev = DebateEvaluator()
        result = ev.evaluate_debate([], [])
        assert result is not None


class TestModels:
    def test_investment_recommendation(self):
        rec = InvestmentRecommendation(
            action="BUY", confidence=0.8, rationale="測試",
            key_factors=[], risk_factors=[], overall_score=60,
        )
        assert rec.action == "BUY"


class TestDebateEvaluatorMethods:
    def test_calculate_side_score(self):
        from datetime import datetime
        ev = DebateEvaluator()
        args = [
            Argument(content="看漲", category=ArgumentCategory.TECHNICAL,
                     strength=ArgumentStrength.STRONG, confidence=0.8,
                     evidence_based=True, data_mentioned=[], key_points=[],
                     timestamp=datetime(2026, 1, 1)),
        ]
        score = ev._calculate_side_score(args)
        assert 0 < score <= 100

    def test_calculate_side_score_empty(self):
        ev = DebateEvaluator()
        assert ev._calculate_side_score([]) == 0.0

    def test_count_strengths(self):
        from datetime import datetime
        ev = DebateEvaluator()
        args = [
            Argument(content="a", category=ArgumentCategory.TECHNICAL,
                     strength=ArgumentStrength.STRONG, confidence=0.8,
                     evidence_based=True, data_mentioned=[], key_points=[],
                     timestamp=datetime(2026, 1, 1)),
            Argument(content="b", category=ArgumentCategory.FUNDAMENTAL,
                     strength=ArgumentStrength.WEAK, confidence=0.3,
                     evidence_based=False, data_mentioned=[], key_points=[],
                     timestamp=datetime(2026, 1, 1)),
        ]
        counts = ev._count_strengths(args)
        assert counts[ArgumentStrength.STRONG] == 1
        assert counts[ArgumentStrength.WEAK] == 1

    def test_calculate_consensus(self):
        from datetime import datetime
        ev = DebateEvaluator()
        bull = [
            Argument(content="看漲", category=ArgumentCategory.TECHNICAL,
                     strength=ArgumentStrength.STRONG, confidence=0.8,
                     evidence_based=True, data_mentioned=[], key_points=[],
                     timestamp=datetime(2026, 1, 1)),
        ]
        bear = [
            Argument(content="看跌", category=ArgumentCategory.TECHNICAL,
                     strength=ArgumentStrength.STRONG, confidence=0.8,
                     evidence_based=True, data_mentioned=[], key_points=[],
                     timestamp=datetime(2026, 1, 1)),
        ]
        consensus = ev._calculate_consensus(bull, bear)
        assert 0 < consensus <= 1

    def test_calculate_consensus_empty(self):
        ev = DebateEvaluator()
        assert ev._calculate_consensus([], []) == 0.0

    def test_evaluate_dimensions(self):
        from datetime import datetime
        ev = DebateEvaluator()
        bull = [
            Argument(content="看漲", category=ArgumentCategory.TECHNICAL,
                     strength=ArgumentStrength.STRONG, confidence=0.8,
                     evidence_based=True, data_mentioned=[], key_points=[],
                     timestamp=datetime(2026, 1, 1)),
        ]
        dims = ev._evaluate_dimensions(bull, [])
        assert "technical" in dims
        assert dims["technical"]["bull"] > 0
