"""Bybit v5 訂單執行器 (Phase 4.1).

永續合約執行, 鏡像 OkxOrderExecutor 模式 (dry-run + REST).
真實下單需 API 金鑰; dry_run=True 時不發真實請求.
"""
from __future__ import annotations

import hashlib
import hmac
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


class BybitOrderExecutor(BrokerConnector):
    """Bybit v5 永續訂單執行器 (category=linear)."""

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._base_url = (
            "https://api-testnet.bybit.com" if config.testnet else "https://api.bybit.com"
        )
        self._session: Any = None

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
        """下單 (dry-run 或真實 REST)."""
        if self.config.dry_run:
            return self._create_dry_run_result(
                symbol, side, order_type, quantity, price, position_side
            )

        import aiohttp

        payload: Dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "side": self._convert_side(side),
            "orderType": self._convert_order_type(order_type),
            "qty": str(quantity),
        }
        if price is not None:
            payload["price"] = str(price)
        if reduce_only:
            payload["reduceOnly"] = "true"
        headers = self._auth_headers("POST", "/v5/order/create", payload)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/v5/order/create",
                    json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            if data.get("retCode") != 0:
                raise RuntimeError(f"Bybit order failed: {data.get('retMsg')}")
            return OrderResult(
                order_id=str(data["result"]["orderId"]),
                symbol=symbol, side=side, order_type=order_type,
                quantity=quantity, price=price, filled_price=price,
                filled_quantity=0.0, status="SUBMITTED",
                timestamp=int(time.time() * 1000), is_paper=False,
            )
        except Exception as e:
            logger.error(f"Bybit place_order failed: {e}")
            return self._create_dry_run_result(
                symbol, side, order_type, quantity, price, position_side
            )

    def _auth_headers(self, method: str, path: str, payload: Dict[str, Any]) -> Dict[str, str]:
        """Bybit v5 簽名 (HMAC-SHA256)."""
        timestamp = str(int(time.time() * 1000))
        query = ""
        if payload:
            query = "&".join(f"{k}={v}" for k, v in payload.items())
        sign_str = f"{timestamp}{self.config.api_key}{query}"
        signature = hmac.new(
            self.config.api_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": self.config.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": "5000",
            "Content-Type": "application/json",
        }

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消訂單."""
        if self.config.dry_run:
            return True
        try:
            import aiohttp

            payload = {"category": "linear", "symbol": symbol, "orderId": order_id}
            headers = self._auth_headers("POST", "/v5/order/cancel", payload)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/v5/order/cancel",
                    json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            return data.get("retCode") == 0
        except Exception as e:
            logger.error(f"Bybit cancel failed: {e}")
            return False

    async def get_positions(self) -> List[Position]:
        """獲取持倉."""
        if self.config.dry_run:
            return []
        try:
            import aiohttp

            headers = self._auth_headers("GET", "/v5/position/list", {})
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/v5/position/list?category=linear",
                    headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            positions: List[Position] = []
            for item in (data.get("result", {}).get("list") or []):
                qty = float(item.get("size", 0))
                entry = float(item.get("avgPrice", 0))
                positions.append(Position(
                    symbol=item["symbol"],
                    position_amount=qty,
                    entry_price=entry,
                    mark_price=float(item.get("markPrice", 0)),
                    unrealized_profit=float(item.get("unrealisedPnl", 0)),
                    liquidation_price=float(item.get("liqPrice", 0)),
                    leverage=int(float(item.get("leverage", 1))),
                    position_side=PositionSide.LONG if item.get("side") == "Buy" else PositionSide.SHORT,
                    notional=qty * entry,
                ))
            return positions
        except Exception as e:
            logger.error(f"Bybit positions failed: {e}")
            return []

    async def get_balance(self) -> Dict[str, float]:
        """獲取餘額."""
        if self.config.dry_run:
            return {}
        try:
            import aiohttp

            headers = self._auth_headers("GET", "/v5/account/wallet-balance", {})
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/v5/account/wallet-balance?accountType=UNIFIED",
                    headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            result = data.get("result", {})
            balances: Dict[str, float] = {}
            for acct in (result.get("list") or []):
                for coin in (acct.get("coin") or []):
                    balances[coin["coin"]] = float(coin.get("walletBalance", 0))
            return balances
        except Exception as e:
            logger.error(f"Bybit balance failed: {e}")
            return {}

    async def close(self) -> None:
        """關閉連接."""
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    def _create_dry_run_result(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float],
        position_side: Optional[PositionSide],
    ) -> OrderResult:
        """創建 dry-run 訂單結果."""
        logger.info("[DRY-RUN] Bybit 訂單打印 (不會實際執行)")
        logger.info(f"  Symbol: {symbol} Side: {side.value} Type: {order_type.value} "
                    f"Qty: {quantity} Price: {price}")
        return OrderResult(
            order_id=f"bybit_dryrun_{uuid.uuid4().hex[:8]}",
            symbol=symbol, side=side, order_type=order_type,
            quantity=quantity, price=price, filled_price=price,
            filled_quantity=quantity, status="FILLED",
            timestamp=int(time.time() * 1000), is_paper=False,
        )

    def _convert_order_type(self, order_type: OrderType) -> str:
        type_map = {
            OrderType.MARKET: "Market",
            OrderType.LIMIT: "Limit",
            OrderType.STOP_MARKET: "Stop",
            OrderType.STOP_LIMIT: "Stop",
            OrderType.TAKE_PROFIT_MARKET: "Market",
            OrderType.TAKE_PROFIT_LIMIT: "Limit",
        }
        return type_map.get(order_type, "Market")

    def _convert_side(self, side: OrderSide) -> str:
        return "Buy" if side == OrderSide.BUY else "Sell"
