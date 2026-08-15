"""Hyperliquid 訂單執行器 (Phase 4.1, DEX).

鏈上訂單簿永續合約. 讀取用公開 info API (無需金鑰);
下單需錢包 ed25519 簽名 — dry-run 模式回報「需錢包簽名」.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from vibe_trading.execution.broker_connector import BrokerConfig, BrokerConnector
from vibe_trading.data_sources.binance_client import (
    OrderSide,
    OrderType,
    Position,
    PositionSide,
)
from vibe_trading.execution.order_executor import OrderResult

logger = logging.getLogger(__name__)


class HyperliquidOrderExecutor(BrokerConnector):
    """Hyperliquid DEX 訂單簿永續執行器."""

    INFO_URL = "https://api.hyperliquid.xyz/info"
    EXCHANGE_URL = "https://api.hyperliquid.xyz/exchange"

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._session: Any = None

    async def _post_info(self, payload: Dict[str, Any]) -> Any:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.INFO_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return await resp.json()

    async def get_mid_price(self, symbol: str) -> Optional[float]:
        """讀取 allMids (公開, 無需金鑰)."""
        try:
            data = await self._post_info({"type": "allMids"})
            # 回傳 {coin: mid} dict
            if isinstance(data, dict):
                mid = data.get(symbol)
                return float(mid) if mid is not None else None
            return None
        except Exception as e:
            logger.error(f"Hyperliquid mid failed: {e}")
            return None

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """下單 (dry-run 或真實 REST).

        Hyperliquid 下單需錢包 ed25519 簽名 + 帳戶地址 —
        真實執行需錢包, dry-run 回報需簽名.
        """
        if self.config.dry_run:
            logger.info("[DRY-RUN] Hyperliquid 訂單 (需錢包 ed25519 簽名, 不實際執行)")
            logger.info(f"  Symbol: {symbol} Side: {side.value} Qty: {quantity} Price: {price}")
            return OrderResult(
                order_id=f"hl_dryrun_{uuid.uuid4().hex[:8]}",
                symbol=symbol, side=side, order_type=order_type,
                quantity=quantity, price=price, filled_price=price,
                filled_quantity=quantity, status="FILLED",
                timestamp=int(time.time() * 1000), is_paper=False,
            )
        raise NotImplementedError(
            "Hyperliquid 真實下單需錢包 ed25519 簽名 (wallet private key); "
            "dry_run=True 使用 (Phase 4.1 僅 dry-run)"
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消訂單."""
        if self.config.dry_run:
            return True
        raise NotImplementedError("Hyperliquid 真實取消需錢包簽名")

    async def get_positions(self) -> List[Position]:
        """獲取持倉 (需帳戶地址; dry-run 回 [])."""
        if self.config.dry_run:
            return []
        raise NotImplementedError("Hyperliquid 持倉查詢需 wallet address")

    async def get_balance(self) -> Dict[str, float]:
        """獲取餘額 (dry-run 回 {})."""
        if self.config.dry_run:
            return {}
        raise NotImplementedError("Hyperliquid 餘額查詢需 wallet address")

    async def close(self) -> None:
        """關閉連接."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
