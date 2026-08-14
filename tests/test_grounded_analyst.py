"""
Tests for P1-2: Grounded Analyst functionality

Verifies that:
1. News analyst prompt contains grounding requirements
2. Sentiment analyst prompt contains grounding requirements
3. Grounded validation detects missing anchors
4. Grounded validation accepts properly grounded reports
"""
import pytest

from vibe_trading.config.prompts import NEWS_ANALYST_PROMPT, SENTIMENT_ANALYST_PROMPT
from vibe_trading.agents.grounded_validation import (
    validate_grounded_output,
    extract_grounded_references,
)


class TestGroundedPrompts:
    """Test that analyst prompts contain grounding requirements"""

    def test_news_analyst_prompt_has_grounding(self):
        """Test that NEWS_ANALYST_PROMPT contains grounding requirements"""
        assert "锚定要求" in NEWS_ANALYST_PROMPT or "Grounding Requirements" in NEWS_ANALYST_PROMPT
        assert "价格" in NEWS_ANALYST_PROMPT or "price" in NEWS_ANALYST_PROMPT.lower()
        assert "时间戳" in NEWS_ANALYST_PROMPT or "timestamp" in NEWS_ANALYST_PROMPT.lower()
        assert "数据来源" in NEWS_ANALYST_PROMPT or "data source" in NEWS_ANALYST_PROMPT.lower()

    def test_sentiment_analyst_prompt_has_grounding(self):
        """Test that SENTIMENT_ANALYST_PROMPT contains grounding requirements"""
        assert "锚定要求" in SENTIMENT_ANALYST_PROMPT or "Grounding Requirements" in SENTIMENT_ANALYST_PROMPT
        assert "价格" in SENTIMENT_ANALYST_PROMPT or "price" in SENTIMENT_ANALYST_PROMPT.lower()
        assert "数据来源" in SENTIMENT_ANALYST_PROMPT or "data source" in SENTIMENT_ANALYST_PROMPT.lower()


class TestGroundedValidation:
    """Test grounded output validation"""

    def test_validate_news_analyst_good_report(self):
        """Test validation passes for a properly grounded news report"""
        report = """
        根据 Binance 数据，BTC 在 2024-01-15 14:30 UTC 突破 $42,000 阻力位。
        以太坊同步上涨至 $2,250，交易量增加 35%。
        CoinGecko 统计显示，过去 24 小时总市值增长 5.2%。
        """
        is_valid, violations = validate_grounded_output(report, "news")
        assert is_valid, f"Expected valid report but got violations: {violations}"

    def test_validate_news_analyst_missing_price(self):
        """Test validation fails when news report lacks price references"""
        report = """
        根据 Binance 数据，BTC 在 2024-01-15 突破阻力位。
        以太坊同步上涨，交易量增加。
        """
        is_valid, violations = validate_grounded_output(report, "news")
        assert not is_valid
        assert any("价格" in v for v in violations)

    def test_validate_news_analyst_missing_timestamp(self):
        """Test validation fails when news report lacks timestamp"""
        report = """
        根据 Binance 数据，BTC 突破 $42,000 阻力位。
        以太坊同步上涨至 $2,250。
        """
        is_valid, violations = validate_grounded_output(report, "news")
        assert not is_valid
        assert any("时间戳" in v for v in violations)

    def test_validate_news_analyst_missing_source(self):
        """Test validation fails when news report lacks data source"""
        report = """
        BTC 在 2024-01-15 14:30 突破 $42,000 阻力位。
        以太坊同步上涨至 $2,250。
        """
        is_valid, violations = validate_grounded_output(report, "news")
        assert not is_valid
        assert any("数据来源" in v for v in violations)

    def test_validate_sentiment_analyst_good_report(self):
        """Test validation passes for a properly grounded sentiment report"""
        report = """
        根据 Binance 数据，恐惧贪婪指数当前为 45（中性）。
        BTC 在 $42,000 附近震荡，资金费率维持在 0.01%。
        CoinGecko 统计显示社交媒体提及量增加 20%。
        """
        is_valid, violations = validate_grounded_output(report, "sentiment")
        assert is_valid, f"Expected valid report but got violations: {violations}"

    def test_validate_sentiment_analyst_missing_price(self):
        """Test validation fails when sentiment report lacks price"""
        report = """
        根据 Binance 数据，恐惧贪婪指数当前为 45（中性）。
        资金费率维持在 0.01%。
        """
        is_valid, violations = validate_grounded_output(report, "sentiment")
        assert not is_valid
        assert any("价格" in v for v in violations)

    def test_validate_sentiment_analyst_missing_source(self):
        """Test validation fails when sentiment report lacks data source"""
        report = """
        恐惧贪婪指数当前为 45（中性）。
        BTC 在 $42,000 附近震荡。
        """
        is_valid, violations = validate_grounded_output(report, "sentiment")
        assert not is_valid
        assert any("数据来源" in v for v in violations)

    def test_extract_references(self):
        """Test extraction of grounded references from report"""
        report = """
        根据 Binance 数据，BTC 在 2024-01-15 14:30 UTC 突破 $42,000。
        CoinGecko 统计显示以太坊上涨至 $2,250。
        """
        refs = extract_grounded_references(report)
        
        assert len(refs["prices"]) >= 2, f"Expected at least 2 prices, got {refs['prices']}"
        assert len(refs["timestamps"]) >= 1, f"Expected at least 1 timestamp, got {refs['timestamps']}"
        assert len(refs["sources"]) >= 2, f"Expected at least 2 sources, got {refs['sources']}"

    def test_empty_report_fails_validation(self):
        """Test that empty report fails validation"""
        is_valid, violations = validate_grounded_output("", "news")
        assert not is_valid
        assert len(violations) > 0
