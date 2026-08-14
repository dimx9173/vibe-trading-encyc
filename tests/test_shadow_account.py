"""Shadow Account 單元測試"""
import csv
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vibe_trading.backtest.shadow_account import (
    ShadowAccountAnalyzer,
    calculate_all_biases,
    extract_rules,
    generate_html_report,
    parse_binance_csv,
    pair_trades,
    run_counterfactual,
)
from vibe_trading.backtest.shadow_account.models import (
    BiasType,
    ShadowReport,
    TradeRecord,
)


@pytest.fixture
def sample_trades():
    """生成樣本交易記錄"""
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    trades = []

    # 10 筆交易：5 盈 5 虧
    for i in range(10):
        is_win = i % 2 == 0
        pnl = 100.0 if is_win else -80.0
        pnl_pct = 2.0 if is_win else -1.6

        entry_time = base_time + timedelta(hours=i * 4)
        exit_time = entry_time + timedelta(hours=2 if is_win else 8)

        trade = TradeRecord(
            trade_id=f"trade_{i}",
            symbol="BTCUSDT",
            side="BUY" if i % 2 == 0 else "SELL",
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=40000.0 + i * 100,
            exit_price=40000.0 + i * 100 + (100 if is_win else -80),
            quantity=0.1,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fee=5.0,
            is_closed=True,
            metadata={"pre_move_pct": 1.0, "action": "OPEN" if i % 2 == 0 else "CLOSE"},
        )
        trades.append(trade)

    return trades


@pytest.fixture
def sample_csv(tmp_path):
    """生成樣本 CSV 文件"""
    csv_path = tmp_path / "trades.csv"
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "UTC_Time", "Account", "Pair", "Side", "Action",
            "Price", "Quantity", "Fee", "Fee_Currency", "Realized_Profit", "Trade_ID"
        ])

        for i in range(5):
            entry_time = base_time + timedelta(hours=i * 4)
            writer.writerow([
                entry_time.isoformat(),
                "main",
                "BTC/USDT",
                "buy",
                "open" if i % 2 == 0 else "close",
                40000.0 + i * 100,
                0.1,
                5.0,
                "USDT",
                100.0 if i % 2 == 0 else -80.0,
                f"trade_{i}",
            ])

    return csv_path


class TestParser:
    """測試 CSV 解析器"""

    def test_parse_binance_csv(self, sample_csv):
        """測試解析 Binance CSV"""
        trades = parse_binance_csv(sample_csv)
        assert len(trades) == 5
        assert trades[0].symbol == "BTCUSDT"
        assert trades[0].side == "BUY"

    def test_parse_nonexistent_csv(self):
        """測試解析不存在的 CSV"""
        with pytest.raises(FileNotFoundError):
            parse_binance_csv("nonexistent.csv")

    def test_pair_trades(self, sample_trades):
        """測試交易配對"""
        paired = pair_trades(sample_trades)
        assert len(paired) > 0


class TestBiases:
    """測試行為偏差計算"""

    def test_disposition_effect(self, sample_trades):
        """測試處置效應計算"""
        biases = calculate_all_biases(sample_trades)
        disposition = next(b for b in biases if b.bias_type == BiasType.DISPOSITION)
        assert 0.0 <= disposition.score <= 1.0
        assert len(disposition.evidence) > 0

    def test_overtrading(self, sample_trades):
        """測試過度交易計算"""
        biases = calculate_all_biases(sample_trades, recommended_daily_trades=2)
        overtrading = next(b for b in biases if b.bias_type == BiasType.OVERTRADING)
        assert 0.0 <= overtrading.score <= 1.0

    def test_chasing(self, sample_trades):
        """測試追漲殺跌計算"""
        biases = calculate_all_biases(sample_trades, chasing_threshold_pct=3.0)
        chasing = next(b for b in biases if b.bias_type == BiasType.CHASING)
        assert 0.0 <= chasing.score <= 1.0

    def test_anchoring(self, sample_trades):
        """測試錨定效應計算"""
        biases = calculate_all_biases(sample_trades)
        anchoring = next(b for b in biases if b.bias_type == BiasType.ANCHORING)
        assert 0.0 <= anchoring.score <= 1.0

    def test_gambler_fallacy(self, sample_trades):
        """測試賭徒誤計算"""
        biases = calculate_all_biases(sample_trades)
        gambler = next(b for b in biases if b.bias_type == BiasType.GAMBLER)
        assert 0.0 <= gambler.score <= 1.0

    def test_empty_trades(self):
        """測試空交易列表"""
        biases = calculate_all_biases([])
        assert len(biases) == 5
        for bias in biases:
            assert bias.score == 0.0


class TestRules:
    """測試規則提取"""

    def test_extract_rules(self, sample_trades):
        """測試規則提取"""
        rules = extract_rules(sample_trades)
        assert isinstance(rules, list)

    def test_extract_rules_empty(self):
        """測試空交易列表"""
        rules = extract_rules([])
        assert len(rules) == 0


class TestCounterfactual:
    """測試反事實回測"""

    def test_run_counterfactual(self, sample_trades):
        """測試反事實回測"""
        result = run_counterfactual(sample_trades)
        assert result.actual_pnl != 0
        assert result.ideal_pnl != 0
        assert len(result.equity_curve_actual) > 0
        assert len(result.equity_curve_ideal) > 0

    def test_run_counterfactual_empty(self):
        """測試空交易列表"""
        result = run_counterfactual([])
        assert result.actual_pnl == 0
        assert result.ideal_pnl == 0


class TestReport:
    """測試報告生成"""

    def test_generate_html_report(self, sample_trades):
        """測試 HTML 報告生成"""
        analyzer = ShadowAccountAnalyzer()
        report = analyzer.analyze(sample_trades, trader_id="test_trader")

        assert isinstance(report, ShadowReport)
        assert report.trader_id == "test_trader"
        assert len(report.html_content) > 0
        assert "<html" in report.html_content
        assert "test_trader" in report.html_content

    def test_save_report(self, sample_trades, tmp_path):
        """測試保存報告"""
        analyzer = ShadowAccountAnalyzer()
        report = analyzer.analyze(sample_trades, trader_id="test_trader")

        output_path = tmp_path / "report.html"
        analyzer.save_report(report, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "<html" in content


class TestAnalyzer:
    """測試主分析器"""

    def test_analyze(self, sample_trades):
        """測試完整分析流程"""
        analyzer = ShadowAccountAnalyzer()
        report = analyzer.analyze(sample_trades, trader_id="test_trader")

        assert report.trader_id == "test_trader"
        assert report.profile.total_trades == len(sample_trades) // 2  # 配對後減半
        assert len(report.profile.biases) == 5
        assert len(report.rules) >= 0
        assert report.counterfactual is not None
        assert len(report.recommendations) >= 0

    def test_analyze_csv(self, sample_csv):
        """測試從 CSV 分析"""
        analyzer = ShadowAccountAnalyzer()
        report = analyzer.analyze_csv(sample_csv, trader_id="csv_trader")

        assert report.trader_id == "csv_trader"
        assert report.profile.total_trades > 0

    def test_custom_parameters(self, sample_trades):
        """測試自定義參數"""
        analyzer = ShadowAccountAnalyzer(
            recommended_daily_trades=5,
            chasing_threshold_pct=2.0,
        )
        report = analyzer.analyze(sample_trades)

        assert report.profile.overall_score >= 0

    def test_no_report_generation(self, sample_trades):
        """測試不生成報告"""
        analyzer = ShadowAccountAnalyzer()
        report = analyzer.analyze(sample_trades, generate_report=False)

        assert report.html_content == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
