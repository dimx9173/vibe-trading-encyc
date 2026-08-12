"""HTML 報告生成器"""
from __future__ import annotations

from datetime import datetime
from typing import List

from .models import BehavioralProfile, CounterfactualResult, ExtractedRule, ShadowReport


def generate_html_report(report: ShadowReport) -> str:
    """生成 HTML 報告

    Args:
        report: ShadowReport 物件

    Returns:
        HTML 字符串
    """
    profile = report.profile
    counterfactual = report.counterfactual

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shadow Account Report - {profile.trader_id}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
        }}
        .metric {{
            display: inline-block;
            background: #ecf0f1;
            padding: 15px 20px;
            margin: 10px;
            border-radius: 6px;
            min-width: 150px;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .metric-label {{
            font-size: 12px;
            color: #7f8c8d;
            text-transform: uppercase;
        }}
        .bias-card {{
            background: #fff;
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 20px;
            margin: 15px 0;
        }}
        .bias-score {{
            font-size: 32px;
            font-weight: bold;
        }}
        .score-low {{ color: #27ae60; }}
        .score-medium {{ color: #f39c12; }}
        .score-high {{ color: #e74c3c; }}
        .evidence {{
            background: #f8f9fa;
            padding: 10px;
            border-left: 4px solid #3498db;
            margin: 10px 0;
        }}
        .recommendation {{
            background: #e8f6f3;
            padding: 10px;
            border-left: 4px solid #27ae60;
            margin: 10px 0;
        }}
        .rule-card {{
            background: #fef9e7;
            border: 1px solid #f1c40f;
            border-radius: 6px;
            padding: 15px;
            margin: 10px 0;
        }}
        .counterfactual {{
            display: flex;
            gap: 20px;
            margin: 20px 0;
        }}
        .cf-box {{
            flex: 1;
            padding: 20px;
            border-radius: 6px;
            text-align: center;
        }}
        .cf-actual {{
            background: #fadbd8;
            border: 2px solid #e74c3c;
        }}
        .cf-ideal {{
            background: #d5f4e6;
            border: 2px solid #27ae60;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: #3498db;
            color: white;
        }}
        .footer {{
            text-align: center;
            color: #7f8c8d;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎭 Shadow Account Report</h1>
        <p><strong>交易者:</strong> {profile.trader_id}</p>
        <p><strong>生成時間:</strong> {report.generated_at.strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p><strong>分析期間:</strong> {profile.analysis_period_start.strftime("%Y-%m-%d")} - {profile.analysis_period_end.strftime("%Y-%m-%d")}</p>

        <h2>📊 交易概覽</h2>
        <div>
            <div class="metric">
                <div class="metric-value">{profile.total_trades}</div>
                <div class="metric-label">總交易次數</div>
            </div>
            <div class="metric">
                <div class="metric-value">{profile.closed_trades}</div>
                <div class="metric-label">已平倉</div>
            </div>
            <div class="metric">
                <div class="metric-value">{profile.open_trades}</div>
                <div class="metric-label">未平倉</div>
            </div>
            <div class="metric">
                <div class="metric-value">{profile.overall_score:.2f}</div>
                <div class="metric-label">整體偏差分數</div>
            </div>
        </div>

        <h2> 行為偏差分析</h2>
"""

    # 偏差卡片
    for bias in profile.biases:
        score_class = "score-low" if bias.score < 0.4 else ("score-medium" if bias.score < 0.7 else "score-high")
        html += f"""
        <div class="bias-card">
            <h3>{_get_bias_emoji(bias.bias_type)} {bias.bias_type.value.title()}</h3>
            <div class="bias-score {score_class}">{bias.score:.2f}</div>
            <p>{bias.description}</p>
            <div class="evidence">
                <strong>證據:</strong>
                <ul>
"""
        for ev in bias.evidence:
            html += f"                    <li>{ev}</li>\n"
        html += f"""                </ul>
            </div>
            <div class="recommendation">
                <strong>建議:</strong> {bias.recommendation}
            </div>
        </div>
"""

    # 反事實分析
    if counterfactual:
        html += f"""
        <h2>🔮 反事實分析</h2>
        <p>如果移除行為偏差，你的交易結果會如何？</p>
        <div class="counterfactual">
            <div class="cf-box cf-actual">
                <h3>實際表現</h3>
                <div class="metric-value" style="color: #e74c3c;">{counterfactual.actual_pnl:.2f} USDT</div>
                <p>收益率：{counterfactual.actual_pnl_pct:.2%}</p>
                <p>勝率：{counterfactual.actual_win_rate:.1%}</p>
                <p>Sharpe：{counterfactual.actual_sharpe:.2f}</p>
            </div>
            <div class="cf-box cf-ideal">
                <h3>理想表現</h3>
                <div class="metric-value" style="color: #27ae60;">{counterfactual.ideal_pnl:.2f} USDT</div>
                <p>收益率：{counterfactual.ideal_pnl_pct:.2%}</p>
                <p>勝率：{counterfactual.ideal_win_rate:.1%}</p>
                <p>Sharpe：{counterfactual.ideal_sharpe:.2f}</p>
            </div>
        </div>
        <div class="recommendation">
            <strong>潛在改進:</strong> +{counterfactual.improvement:.2f} USDT ({counterfactual.improvement_pct:.2%})
        </div>
"""

    # 提取的規則
    if report.rules:
        html += """
        <h2>📋 行為規則</h2>
"""
        for rule in report.rules:
            html += f"""
        <div class="rule-card">
            <h4>{rule.description}</h4>
            <p><strong>觸發條件:</strong> {rule.trigger_condition}</p>
            <p><strong>建議行動:</strong> {rule.suggested_action}</p>
            <p><strong>置信度:</strong> {rule.confidence:.1%} (基於 {rule.evidence_count} 筆交易)</p>
        </div>
"""

    # 總結建議
    if report.recommendations:
        html += """
        <h2>💡 總結建議</h2>
        <ol>
"""
        for rec in report.recommendations:
            html += f"            <li>{rec}</li>\n"
        html += """        </ol>
"""

    html += """
        <div class="footer">
            <p>Generated by Vibe Trading Shadow Account Analyzer</p>
        </div>
    </div>
</body>
</html>
"""

    return html


def _get_bias_emoji(bias_type) -> str:
    """獲取偏差類型的 emoji"""
    emojis = {
        "disposition": "⏰",
        "overtrading": "🔄",
        "chasing": "",
        "anchoring": "⚓",
        "gambler": "🎲",
    }
    return emojis.get(bias_type.value, "❓")
