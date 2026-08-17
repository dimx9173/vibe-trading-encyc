"""
AI 交易元認知看板與平倉覆盤 (Harvested Alpha 模組七 — 規格書 §2.7)

1. generate_dashboard_prompt: 戰績/手感看板注入 PM 與 Risk
2. run_post_mortem: 平倉自動歸因覆盤 + 避坑記憶
3. 自適應節奏 (Meta-Regime): 順風放開 / 逆風謹慎
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetaCognitionEngine:
    """元認知引擎: 戰績看板 + 覆盤歸因 + 節奏控制."""

    def __init__(self):
        self._trade_history: List[Dict[str, Any]] = []

    def record_trade(self, trade: Dict[str, Any]) -> None:
        """記錄已平倉交易 (供看板/覆盤)."""
        self._trade_history.append(trade)
        if len(self._trade_history) > 200:
            self._trade_history = self._trade_history[-200:]

    def generate_dashboard_prompt(self, trade_history: Optional[List[Dict[str, Any]]] = None) -> str:
        """生成戰績與手感看板 Prompt (規格書 §2.7)."""
        history = trade_history if trade_history is not None else self._trade_history
        if not history:
            return "📊 戰績看板: 尚無已平倉交易紀錄 (新手保護期)."

        wins = [t for t in history if t.get("result") == "WIN"]
        losses = [t for t in history if t.get("result") == "LOSS"]
        total = len(history)
        win_rate = len(wins) / total * 100 if total else 0.0

        long_trades = [t for t in history if t.get("direction") == "LONG"]
        short_trades = [t for t in history if t.get("direction") == "SHORT"]
        long_wr = (sum(1 for t in long_trades if t.get("result") == "WIN") / len(long_trades) * 100) if long_trades else 0.0
        short_wr = (sum(1 for t in short_trades if t.get("result") == "WIN") / len(short_trades) * 100) if short_trades else 0.0

        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0.0
        payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        # 手感趨勢 (最近 5 筆)
        recent = history[-5:]
        recent_wr = sum(1 for t in recent if t.get("result") == "WIN") / len(recent) * 100

        rhythm = "🔥 順風" if recent_wr >= 60 else ("⚠️ 逆風" if recent_wr <= 40 else "➡️ 中性")
        mode = "放開倉位" if rhythm == "🔥 順風" else ("謹慎防守 (倉位減半/收緊止損)" if rhythm == "⚠️ 逆風" else "標準")

        return (
            f"📊 <b>戰績看板</b> (最近 {total} 筆)\n"
            f"勝率 {win_rate:.0f}% | 多 {long_wr:.0f}% / 空 {short_wr:.0f}% | "
            f"盈虧比 {payoff:.1f}:1\n"
            f"最近 5 筆勝率 {recent_wr:.0f}% → 手感 <b>{rhythm}</b>\n"
            f"建議節奏: <b>{mode}</b>"
        )

    def get_rhythm_mode(self) -> Dict[str, str]:
        """自適應節奏 (計劃書 §4 模組七: 順風放開 / 逆風謹慎)."""
        if not self._trade_history:
            return {"mode": "STANDARD", "reason": "no history"}
        recent = self._trade_history[-5:]
        recent_wr = sum(1 for t in recent if t.get("result") == "WIN") / len(recent)
        if recent_wr >= 0.6:
            return {"mode": "AGGRESSIVE", "reason": f"recent WR {recent_wr:.0%} (順風)"}
        if recent_wr <= 0.4:
            return {"mode": "DEFENSIVE", "reason": f"recent WR {recent_wr:.0%} (逆風)"}
        return {"mode": "STANDARD", "reason": f"recent WR {recent_wr:.0%}"}

    def run_post_mortem(
        self,
        closed_trade: Dict[str, Any],
        market_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """平倉自動覆盤歸因 (規格書 §2.7).

        Args:
            closed_trade: {trade_id, direction, entry, exit, pnl, battle_card_id?, expected_rr}
            market_snapshot: {regime, rsi_at_exit, ...}

        Returns:
            {trade_id, result, attribution_primary, lessons_learned, memory_trap_created}
        """
        trade_id = closed_trade.get("trade_id", "T-?")
        pnl = float(closed_trade.get("pnl", 0.0))
        result = "WIN" if pnl > 0 else "LOSS"

        # 歸因: 戰法命中 vs 止損保護 vs 逆勢
        card_id = closed_trade.get("battle_card_id")
        regime = market_snapshot.get("regime", "?")
        direction = closed_trade.get("direction", "LONG")

        if result == "WIN":
            if card_id:
                attribution = f"{card_id} 戰法命中"
            else:
                attribution = f"方向正確 ({direction} @ {regime})"
            lessons = "順勢持倉並讓利潤奔跑"
            trap = None
        else:
            # 逆勢虧損 → 避坑記憶
            if regime and ("DOWN" in str(regime) and direction == "LONG"):
                attribution = "逆勢做多 (4H 空頭中接飛刀)"
                lessons = "4H 空頭排列下禁止抄底做多"
                trap = "RISK_TRAP_01_LONG_AGAINST_DOWNTREND"
            elif regime and ("UP" in str(regime) and direction == "SHORT"):
                attribution = "逆勢做空 (4H 多頭中摸頂)"
                lessons = "4H 多頭排列下禁止摸頂做空"
                trap = "RISK_TRAP_02_SHORT_AGAINST_UPTREND"
            else:
                attribution = f"止損保護 (虧損 {abs(pnl):.2f})"
                lessons = "紀律止損執行正確, 行情未按預期"
                trap = None

        record = {
            "trade_id": trade_id,
            "result": result,
            "attribution_primary": attribution,
            "lessons_learned": lessons,
            "memory_trap_created": trap,
            "pnl": round(pnl, 2),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.record_trade(record)
        logger.info(f"[PostMortem] {trade_id} {result}: {attribution}")
        return record

    def get_recent_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._trade_history[-limit:]
