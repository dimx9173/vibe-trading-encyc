"""Shadow Account 主協調器"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .biases import calculate_all_biases
from .counterfactual import run_counterfactual
from .models import BehavioralProfile, ShadowReport, TradeRecord
from .parser import pair_trades, parse_binance_csv
from .report import generate_html_report
from .rules import extract_rules


class ShadowAccountAnalyzer:
    """Shadow Account 分析器"""

    def __init__(
        self,
        recommended_daily_trades: int = 8,
        chasing_threshold_pct: float = 3.0,
    ):
        self.recommended_daily_trades = recommended_daily_trades
        self.chasing_threshold_pct = chasing_threshold_pct

    def analyze(
        self,
        trades: List[TradeRecord],
        trader_id: str = "default",
        generate_report: bool = True,
    ) -> ShadowReport:
        """執行完整分析

        Args:
            trades: 交易記錄列表
            trader_id: 交易者 ID
            generate_report: 是否生成 HTML 報告

        Returns:
            ShadowReport
        """
        # 配對交易
        paired_trades = pair_trades(trades)

        # 計算行為偏差
        biases = calculate_all_biases(
            paired_trades,
            self.recommended_daily_trades,
            self.chasing_threshold_pct,
        )

        # 計算整體分數
        overall_score = sum(b.score for b in biases) / len(biases) if biases else 0

        # 生成行為剖面
        closed_trades = [t for t in paired_trades if t.is_closed]
        open_trades = [t for t in paired_trades if not t.is_closed]

        times = [t.entry_time for t in paired_trades]
        profile = BehavioralProfile(
            trader_id=trader_id,
            analysis_period_start=min(times) if times else datetime.now(),
            analysis_period_end=max(times) if times else datetime.now(),
            total_trades=len(paired_trades),
            closed_trades=len(closed_trades),
            open_trades=len(open_trades),
            biases=biases,
            overall_score=overall_score,
            summary=self._generate_summary(profile=None, biases=biases),
        )

        # 提取規則
        rules = extract_rules(paired_trades)

        # 反事實分析
        counterfactual = run_counterfactual(paired_trades)

        # 生成建議
        recommendations = self._generate_recommendations(biases, rules)

        # 生成報告
        report = ShadowReport(
            trader_id=trader_id,
            generated_at=datetime.now(),
            profile=profile,
            rules=rules,
            counterfactual=counterfactual,
            recommendations=recommendations,
        )

        if generate_report:
            report.html_content = generate_html_report(report)

        return report

    def analyze_csv(
        self,
        csv_path: str | Path,
        trader_id: str = "default",
        generate_report: bool = True,
    ) -> ShadowReport:
        """從 CSV 文件分析

        Args:
            csv_path: Binance CSV 文件路徑
            trader_id: 交易者 ID
            generate_report: 是否生成 HTML 報告

        Returns:
            ShadowReport
        """
        trades = parse_binance_csv(csv_path)
        return self.analyze(trades, trader_id, generate_report)

    def save_report(self, report: ShadowReport, output_path: str | Path) -> None:
        """保存 HTML 報告

        Args:
            report: ShadowReport
            output_path: 輸出文件路徑
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.html_content)

    def _generate_summary(self, profile, biases) -> str:
        """生成分析摘要"""
        if not biases:
            return "無足夠數據生成摘要"

        high_biases = [b for b in biases if b.score >= 0.7]
        medium_biases = [b for b in biases if 0.4 <= b.score < 0.7]

        if high_biases:
            return f"發現 {len(high_biases)} 個嚴重行為偏差，需要立即改進"
        elif medium_biases:
            return f"發現 {len(medium_biases)} 個中等行為偏差，建議逐步改進"
        else:
            return "行為偏差較輕微，保持當前交易紀律"

    def _generate_recommendations(self, biases, rules) -> List[str]:
        """生成總結建議"""
        recommendations = []

        # 根據偏差分數生成建議
        for bias in sorted(biases, key=lambda b: b.score, reverse=True):
            if bias.score >= 0.7:
                recommendations.append(f"【優先】{bias.recommendation}")
            elif bias.score >= 0.4:
                recommendations.append(f"【建議】{bias.recommendation}")

        # 根據規則生成建議
        for rule in rules:
            if rule.confidence >= 0.5:
                recommendations.append(f"【規則】{rule.suggested_action}")

        return recommendations[:10]  # 最多 10 條建議
