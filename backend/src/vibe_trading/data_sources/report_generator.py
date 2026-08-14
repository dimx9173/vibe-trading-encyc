"""
Report Generator

Produces unified performance reports for backtest and Paper modes,
marking data-source differences and generating comparison reports.

Part of the external data layer Phase 4 (Task 4.4).
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


class ReportGenerator:
    """Generate unified backtest / Paper reports"""

    def __init__(self, mode: str = "backtest"):
        """
        Args:
            mode: "backtest" or "paper" — default data-source label
        """
        assert mode in ("backtest", "paper"), f"unknown mode: {mode}"
        self.mode = mode

    # ------------------------------------------------------------------
    # Report building
    # ------------------------------------------------------------------

    def build_report(
        self,
        symbol: str,
        metrics: Dict[str, Any],
        data_sources: Optional[List[str]] = None,
        note: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build a unified report dict.

        Args:
            symbol: trading pair
            metrics: performance metrics (sharpe/win_rate/max_dd/etc)
            data_sources: list of data sources used (for diff marking)
            note: optional remark (e.g. "回测未使用新闻/情绪数据")
            mode: override report mode

        Returns:
            Unified report dict with data-source difference markers
        """
        mode = mode or self.mode
        return {
            "generated_at": datetime.now().isoformat(),
            "mode": mode,
            "symbol": symbol,
            "metrics": metrics,
            "data_sources": data_sources or self._default_sources(mode),
            "data_source_notes": self._mark_source_differences(
                data_sources or self._default_sources(mode)
            ),
            "note": note or self._default_note(mode),
        }

    def _default_sources(self, mode: str) -> List[str]:
        """Default data sources per mode"""
        if mode == "backtest":
            return ["歷史 K-line", "技術指標", "Alpha 因子", "Skills"]
        return ["即時 K-line", "技術指標", "新聞/情緒", "清算數據"]

    def _default_note(self, mode: str) -> str:
        if mode == "backtest":
            return "回測未使用新聞/情緒數據"
        return "Paper 模式包含即時插件數據"

    def _mark_source_differences(self, sources: List[str]) -> List[str]:
        """Mark which sources differ from the other mode"""
        differences = []
        for s in sources:
            if "新聞" in s or "情緒" in s or "清算" in s:
                differences.append(f"{s} — 即時專用，回測不含")
        return differences

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare_reports(
        self,
        backtest_report: Dict[str, Any],
        paper_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a comparison report between backtest and Paper runs.

        Args:
            backtest_report: report built with mode="backtest"
            paper_report: report built with mode="paper"

        Returns:
            Comparison dict: metric deltas + source-difference summary
        """
        bt_metrics = backtest_report.get("metrics", {})
        paper_metrics = paper_report.get("metrics", {})

        deltas: Dict[str, Any] = {}
        for key in set(bt_metrics) | set(paper_metrics):
            a = bt_metrics.get(key)
            b = paper_metrics.get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                deltas[key] = {
                    "backtest": a,
                    "paper": b,
                    "delta": round(b - a, 6),
                }
            else:
                deltas[key] = {"backtest": a, "paper": b, "delta": None}

        return {
            "generated_at": datetime.now().isoformat(),
            "comparison": deltas,
            "source_differences": {
                "backtest_only": self._mark_source_differences(
                    backtest_report.get("data_sources", [])
                ),
                "paper_only": self._mark_source_differences(
                    paper_report.get("data_sources", [])
                ),
            },
            "note": (
                "回測/即時結果差異可能源於數據源不同 "
                "（回測不含新聞/情緒/清算插件）"
            ),
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_markdown(self, report: Dict[str, Any]) -> str:
        """Render a unified report as Markdown"""
        lines = [
            f"# {report.get('mode', 'report').upper()} 報告 — {report.get('symbol', '')}",
            f"生成時間: {report.get('generated_at', '')}",
            "",
            "## 績效指標",
        ]
        metrics = report.get("metrics", {})
        if metrics:
            for key, value in metrics.items():
                lines.append(f"- **{key}**: {value}")
        else:
            lines.append("- (無數據)")

        sources = report.get("data_source_notes", [])
        if sources:
            lines.append("")
            lines.append("## 數據源差異")
            lines.extend(f"- ⚠️ {s}" for s in sources)

        note = report.get("note")
        if note:
            lines.append("")
            lines.append(f"> {note}")

        return "\n".join(lines)

    def to_json(self, report: Dict[str, Any]) -> str:
        """Serialize a report to JSON string"""
        return json.dumps(report, ensure_ascii=False, indent=2, default=str)
