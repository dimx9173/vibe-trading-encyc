"""Bitget v2 訂單執行器 (Phase 4.1).

永續合約執行 (mix), 鏡像 OkxOrderExecutor 模式 (dry-run + REST).
真實下單需 API 金鑰; dry_run=True 時不發真實請求.
"""
from __future__ import annotations

import hashlib
import hmac
import json
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


class BitgetOrderExecutor(BrokerConnector):
    """Bitget v2 永續訂單執行器 (mix)."""

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._base_url = "https://api.bitget.com"
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

        product_type = "USDT-FUTURES"
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "productType": product_type,
            "marginMode": "crossed",
            "side": self._convert_side(side),
            "orderType": self._convert_order_type(order_type),
            "size": str(quantity),
        }
        if price is not None:
            payload["price"] = str(price)
        if reduce_only:
            payload["reduceOnly"] = "true"
        headers = self._auth_headers(payload, "/api/v2/mix/order/place-order")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/api/v2/mix/order/place-order",
                    json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            if data.get("code") != "00000":
                raise RuntimeError(f"Bitget order failed: {data.get('msg')}")
            return OrderResult(
                order_id=str(data["data"]["orderId"]),
                symbol=symbol, side=side, order_type=order_type,
                quantity=quantity, price=price, filled_price=price,
                filled_quantity=0.0, status="SUBMITTED",
                timestamp=int(time.time() * 1000), is_paper=False,
            )
        except Exception as e:
            logger.error(f"Bitget place_order failed: {e}")
            return self._create_dry_run_result(
                symbol, side, order_type, quantity, price, position_side
            )

    def _auth_headers(self, payload: Dict[str, Any], path: str) -> Dict[str, str]:
        """Bitget v2 簽名 (HMAC-SHA256)."""
        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload, separators=(",", ":"))
        sign_str = f"{timestamp}{self.config.api_key}{path}{body}"
        signature = hmac.new(
            self.config.api_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "ACCESS-KEY": self.config.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.config.passphrase or "",
            "Content-Type": "application/json",
        }

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消訂單."""
        if self.config.dry_run:
            return True
        try:
            import aiohttp

            payload = {"symbol": symbol, "productType": "USDT-FUTURES", "orderId": order_id}
            headers = self._auth_headers(payload, "/api/v2/mix/order/cancel-order")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/api/v2/mix/order/cancel-order",
                    json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            return data.get("code") == "00000"
        except Exception as e:
            logger.error(f"Bitget cancel failed: {e}")
            return False

    async def get_positions(self) -> List[Position]:
        """獲取持倉."""
        if self.config.dry_run:
            return []
        try:
            import aiohttp

            headers = self._auth_headers({}, "/api/v2/mix/position/all-position")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/api/v2/mix/position/all-position?productType=USDT-FUTURES",
                    headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            positions: List[Position] = []
            for item in (data.get("data") or []):
                qty = float(item.get("total", 0))
                entry = float(item.get("averageOpenPrice", 0))
                positions.append(Position(
                    symbol=item["symbol"],
                    position_amount=qty,
                    entry_price=entry,
                    mark_price=float(item.get("markPrice", 0)),
                    unrealized_profit=float(item.get("unrealizedProfit", 0)),
                    liquidation_price=float(item.get("liquidationPrice", 0)),
                    leverage=int(float(item.get("leverage", 1))),
                    position_side=PositionSide.LONG if item.get("holdSide") == "long" else PositionSide.SHORT,
                    notional=qty * entry,
                ))
            return positions
        except Exception as e:
            logger.error(f"Bitget positions failed: {e}")
            return []

    async def get_balance(self) -> Dict[str, float]:
        """獲取餘額."""
        if self.config.dry_run:
            return {}
        try:
            import aiohttp

            headers = self._auth_headers({}, "/api/v2/account/all-account-balance")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/api/v2/account/all-account-balance",
                    headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
            balances: Dict[str, float] = {}
            for acct in (data.get("data") or []):
                for coin in (acct.get("coinList") or []):
                    balances[coin["coinName"]] = float(coin.get("available", 0))
            return balances
        except Exception as e:
            logger.error(f"Bitget balance failed: {e}")
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
        logger.info("[DRY-RUN] Bitget 訂單打印 (不會實際執行)")
        logger.info(f"  Symbol: {symbol} Side: {side.value} Type: {order_type.value} "
                    f"Qty: {quantity} Price: {price}")
        return OrderResult(
            order_id=f"bitget_dryrun_{uuid.uuid4().hex[:8]}",
            symbol=symbol, side=side, order_type=order_type,
            quantity=quantity, price=price, filled_price=price,
            filled_quantity=quantity, status="FILLED",
            timestamp=int(time.time() * 1000), is_paper=False,
        )

    def _convert_order_type(self, order_type: OrderType) -> str:
        type_map = {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_MARKET: "market",
            OrderType.STOP_LIMIT: "limit",
            OrderType.TAKE_PROFIT_MARKET: "market",
            OrderType.TAKE_PROFIT_LIMIT: "limit",
        }
        return type_map.get(order_type, "market")

    def _convert_side(self, side: OrderSide) -> str:
        return "buy" if side == OrderSide.BUY else "sell"
