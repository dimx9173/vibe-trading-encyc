"""
Hypothesis 8 大經典戰法卡片庫 (Harvested Alpha 模組四 — 規格書 §2.4)

- 預置 8 大戰法 (BC-01~BC-08) 從 config/battle_cards.yaml 載入
- match_active_cards: 依當前市場形態匹配, 供 Prompt In-Context 注入
- record_trade_outcome: 平倉後回寫勝率/盈虧比, 動態演化
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class BattleCard:
    """單張戰法卡片."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id", "?")
        self.name = data.get("name", "?")
        self.conditions = data.get("conditions", {})
        self.direction = data.get("direction", "HOLD")
        self.target_rr = float(data.get("target_rr", 2.0))
        self.historical_win_rate = float(data.get("historical_win_rate", 0.5))
        self.historical_trades = int(data.get("historical_trades", 0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "conditions": self.conditions,
            "direction": self.direction, "target_rr": self.target_rr,
            "historical_win_rate": self.historical_win_rate,
            "historical_trades": self.historical_trades,
        }


class BattleCardRegistry:
    """戰法卡片註冊表."""

    def __init__(self, yaml_path: Optional[str] = None):
        self._cards: List[BattleCard] = []
        path = yaml_path or str(
            Path(__file__).resolve().parent.parent / "config" / "battle_cards.yaml")
        self._load(path)

    def _load(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._cards = [BattleCard(c) for c in data.get("battle_cards", [])]
            logger.info(f"Battle cards loaded: {len(self._cards)} cards from {path}")
        except Exception as e:
            logger.warning(f"Battle cards load failed (fallback empty): {e}")
            self._cards = []

    def get_all(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self._cards]

    def _match_condition(self, cond_key: str, cond_val: Any, market: Dict[str, Any]) -> bool:
        """單一條件比對 (支援 _max/_min 後綴 + 字串相等)."""
        # 帶 _max/_min 後綴: 用基礎名查 market 值
        base_key = cond_key
        op = "eq"
        if cond_key.endswith("_max"):
            base_key, op = cond_key[:-4], "le"
        elif cond_key.endswith("_min"):
            base_key, op = cond_key[:-4], "ge"
        mv = market.get(base_key, market.get(cond_key))
        if mv is None:
            return False
        if isinstance(cond_val, (int, float)) and isinstance(mv, (int, float)):
            if op == "le":
                return mv <= cond_val
            if op == "ge":
                return mv >= cond_val
            return abs(mv - cond_val) < 1e-6
        return str(mv) == str(cond_val)

    def match_active_cards(self, market_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """比對當前市場形態, 返回匹配的戰法卡片 (含方向/盈虧比/勝率).

        Args:
            market_state: {macro_regime, rsi_divergence, price_action, bb_breakout,
                           volume_ratio, rsi, funding_annualized, candle_type, ...}
        """
        matched: List[Dict[str, Any]] = []
        for card in self._cards:
            hit = True
            for key, val in card.conditions.items():
                if not self._match_condition(key, val, market_state):
                    hit = False
                    break
            if hit:
                matched.append(card.to_dict())
        return matched

    def record_trade_outcome(self, card_id: str, net_pnl: float, r_realized: float) -> Optional[Dict[str, Any]]:
        """交易平倉後回寫: 更新勝率與盈虧比 (動態演化).

        簡化: 以 EMA 平滑更新勝率 (α=0.2), trades+1.
        """
        for card in self._cards:
            if card.id == card_id:
                won = 1.0 if net_pnl > 0 else 0.0
                prev = card.historical_win_rate
                card.historical_win_rate = round(prev + 0.2 * (won - prev), 4)
                card.historical_trades += 1
                logger.info(f"Battle card {card_id} updated: wr={card.historical_win_rate} trades={card.historical_trades}")
                return card.to_dict()
        logger.warning(f"Battle card not found: {card_id}")
        return None
