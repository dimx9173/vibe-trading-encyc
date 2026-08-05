"""
Fix A (P0) regression tests: negation-context parsing.

PM 說「最終決策：HOLD」但全文含「否决...BUY建议」→ 必須回 HOLD，不是 BUY。
（17:00–22:00 六根被誤判成 BUY 的根因）
"""
import pytest

from vibe_trading.coordinator.signal_processor import SignalProcessor
from vibe_trading.tools.signal_parser import parse_decision


@pytest.fixture
def sp():
    return SignalProcessor()


@pytest.mark.parametrize(
    "text,expected",
    [
        # 實際 17:00 / 18:30 根的 PM 輸出模式
        (
            "## 一、最终决策：**HOLD（观望，不开新仓）**\n"
            "> 我在此否决量化评分卡的BUY建议。理由如下。",
            "HOLD",
        ),
        (
            "## 一、最终决策：HOLD（观望，不开新仓）\n"
            "否决量化评分卡的BUY建议。",
            "HOLD",
        ),
        (
            "决策概要：HOLD（不开新仓，不提交订单）。理由：R:R虚报、情绪Sell。",
            "HOLD",
        ),
        (
            "最终决策：HOLD。不追多、不做空，等待方向确认。",
            "HOLD",
        ),
        # 明確欄位優先：欄位說 BUY、全文討論 SELL → 欄位勝
        ("最终决策：BUY。虽然有人看空，但我否决SELL建议。", "BUY"),
        # 無明確欄位時，否定語境不該誤判
        ("我否决BUY建议，维持观望。", "HOLD"),
        ("不建議买入，先观察。", "HOLD"),
        ("不要做多，风险太大。", "HOLD"),
        # 真 BUY 不受影響
        ("Decision: BUY\nRationale: 情绪面强劲", "BUY"),
        ("最终决策：WEAK_BUY", "WEAK BUY"),
        ("最终决策：STRONG_BUY", "STRONG BUY"),
    ],
)
def test_negation_context_parse(sp, text, expected):
    assert parse_decision(text) == expected, f"text={text!r}"


def test_negation_pm_full_decision_flow(sp):
    """完整重現 17:00 根：PM 最終決策 HOLD + 否決 BUY → 記錄應為 HOLD。"""
    text = (
        "数据已获取完毕。让我综合所有信息进行最终决策评估。\n\n"
        "## 关键实时数据核验\n"
        "| 当前价格 | 64,080 USDT |\n\n"
        "# 投资组合经理最终决策报告\n"
        "## 一、最终决策：**HOLD（观望，不开新仓）**\n"
        "> 我在此否决量化评分卡的BUY建议。理由如下。"
    )
    result = sp.process_signal(decision_text=text, agent_name="PM")
    assert result.signal.value == "HOLD", (
        f"PM 最終決策 HOLD 被誤判成 {result.signal.value!r}"
    )
