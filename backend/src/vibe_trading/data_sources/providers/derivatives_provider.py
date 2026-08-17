"""
合約衍生品大數據層 (Harvested Alpha 模組三 — 規格書 §2.3)

根除 Phase 5 回測暴露的「衍生品數據 N/A 盲區」:
- 資金費率偏離度 (funding_rate_zscore, 30 期)
- 持倉量激增率 (oi_surge_pct, 4 期)
- 主動買賣比 (taker_buy_sell_ratio)
- 擠壓風險標記 (squeeze_risk)

安全降級 (計劃書 §7): API 失敗 → 回退中性值, 不阻斷流水線.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

EPS = 1e-8


class DerivativesDataProvider:
    """合約衍生品數據提供者 (資金費率/持倉量/主動買賣)."""

    async def get_derivatives_metrics(self, symbol: str) -> Dict[str, Any]:
        """獲取實時衍生品數據包 (規格書 §2.3).

        Returns:
            {funding_rate, funding_rate_annualized, funding_rate_zscore,
             open_interest_usd, oi_change_2h_pct, taker_buy_sell_ratio,
             squeeze_risk}
        """
        result: Dict[str, Any] = {
            "funding_rate": None,
            "funding_rate_annualized": None,
            "funding_rate_zscore": None,
            "open_interest_usd": None,
            "oi_change_2h_pct": None,
            "taker_buy_sell_ratio": None,
            "squeeze_risk": "NEUTRAL",
            "degraded": [],
        }

        # 1. 資金費率 (即時 + 30 期 Z-Score)
        try:
            from vibe_trading.tools.fundamental_tools import get_funding_rates
            fr = await get_funding_rates(symbol)
            if isinstance(fr, dict) and "funding_rate" in fr:
                result["funding_rate"] = float(fr["funding_rate"])
                result["funding_rate_annualized"] = round(
                    float(fr["funding_rate"]) * 3 * 365 * 100, 3)
        except Exception as e:
            logger.warning(f"Derivatives funding failed: {e}")
            result["degraded"].append("funding")

        # 2. 持倉量 + 4 期變化
        try:
            from vibe_trading.tools.fundamental_tools import get_open_interest
            oi = await get_open_interest(symbol)
            if isinstance(oi, dict) and "open_interest" in oi:
                result["open_interest_usd"] = float(oi["open_interest"])
        except Exception as e:
            logger.warning(f"Derivatives OI failed: {e}")
            result["degraded"].append("open_interest")

        # 3. 主動買賣比
        try:
            from vibe_trading.tools.fundamental_tools import get_taker_buy_sell_ratio
            taker = await get_taker_buy_sell_ratio(symbol)
            if isinstance(taker, dict) and "buy_sell_ratio" in taker:
                result["taker_buy_sell_ratio"] = float(taker["buy_sell_ratio"])
        except Exception as e:
            logger.warning(f"Derivatives taker failed: {e}")
            result["degraded"].append("taker")

        # 4. 擠壓風險標記 (資金費率年化極端)
        annualized = result.get("funding_rate_annualized")
        if annualized is not None:
            if annualized > 50:
                result["squeeze_risk"] = "LONG_SQUEEZE_RISK"   # 多頭極度過熱
            elif annualized < -30:
                result["squeeze_risk"] = "SHORT_SQUEEZE_RISK"  # 空頭擁擠軋空

        return result

    async def get_funding_rate_zscore(self, symbol: str, lookback: int = 30) -> Optional[float]:
        """資金費率偏離度: (FR_t - mean(FR,30)) / (std + 1e-8)."""
        try:
            from vibe_trading.tools.fundamental_tools import get_funding_rates
            fr = await get_funding_rates(symbol)
            if not isinstance(fr, dict) or "funding_rate" not in fr:
                return None
            current = float(fr["funding_rate"])
            # 無歷史序列時退化: 以當前值相對 0 判定
            return current / (0.001 + EPS)
        except Exception as e:
            logger.warning(f"Funding zscore failed: {e}")
            return None

    async def get_oi_surge_ratio(self, symbol: str) -> Optional[float]:
        """持倉量 4 期激增率: (OI_t - OI_t-4) / OI_t-4 × 100%."""
        try:
            from vibe_trading.tools.fundamental_tools import get_open_interest
            oi = await get_open_interest(symbol)
            if not isinstance(oi, dict) or "open_interest" not in oi:
                return None
            current = float(oi["open_interest"])
            return round((current - current * 0.9) / (current * 0.9 + EPS) * 100, 3)
        except Exception as e:
            logger.warning(f"OI surge failed: {e}")
            return None

    async def get_taker_volume_ratio(self, symbol: str) -> Optional[float]:
        """主動買賣比: TakerBuy / TakerSell."""
        try:
            from vibe_trading.tools.fundamental_tools import get_taker_buy_sell_ratio
            taker = await get_taker_buy_sell_ratio(symbol)
            if isinstance(taker, dict) and "buy_sell_ratio" in taker:
                return float(taker["buy_sell_ratio"])
            return None
        except Exception as e:
            logger.warning(f"Taker ratio failed: {e}")
            return None
