"""
OKX 訂單執行器

實現 OKX 交易所的訂單執行功能。
"""
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from vibe_trading.execution.broker_connector import BrokerConnector, BrokerConfig
from vibe_trading.execution.order_executor import (
    OrderResult,
    OrderSide,
    OrderType,
)
from vibe_trading.data_sources.binance_client import (
    Position,
    PositionSide,
)
from vibe_trading.data_sources.providers.okx_provider import OkxProvider
from vibe_trading.data_sources.exchange_config import OkxExchangeConfig, ExchangeType

logger = logging.getLogger(__name__)


class OkxOrderExecutor(BrokerConnector):
    """
    OKX 訂單執行器

    實現 OKX 交易所的訂單執行功能，支持：
    - 限價單/市價單
    - 止損止盈單
    - 持倉查詢
    - 餘額查詢
    """

    def __init__(self, config: BrokerConfig):
        self.config = config
        self._dry_run = config.dry_run

        okx_config = OkxExchangeConfig(
            exchange_type=ExchangeType.OKX,
            api_key=config.api_key,
            api_secret=config.api_secret,
            passphrase=config.passphrase or "",
            environment="testnet" if config.testnet else "mainnet",
        )
        self._provider = OkxProvider(okx_config)

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
        """下單"""
        if self._dry_run:
            return self._create_dry_run_result(
                symbol, side, order_type, quantity, price, position_side
            )

        try:
            okx_order_type = self._convert_order_type(order_type)
            okx_side = self._convert_side(side)

            body = {
                "instId": symbol,
                "tdMode": "cash",
                "side": okx_side,
                "ordType": okx_order_type,
                "sz": str(quantity),
            }

            if price is not None:
                body["px"] = str(price)

            if stop_price is not None:
                body["slTriggerPx"] = str(stop_price)
                body["slOrdType"] = "market"

            result = await self._provider._request(
                "/api/v5/trade/order",
                params=body,
            )

            return OrderResult(
                order_id=result.get("ordId", "") if isinstance(result, dict) else "",
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                filled_price=None,
                filled_quantity=0,
                status="NEW",
                timestamp=int(datetime.now().timestamp() * 1000),
                is_paper=False,
            )

        except Exception as e:
            logger.error(f"Failed to place OKX order: {e}")
            return OrderResult(
                order_id="",
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                filled_price=None,
                filled_quantity=0,
                status="ERROR",
                timestamp=int(datetime.now().timestamp() * 1000),
                is_paper=False,
            )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消訂單"""
        if self._dry_run:
            logger.info(f"[DRY-RUN] 取消 OKX 訂單: {order_id}")
            return True

        try:
            await self._provider._request(
                "/api/v5/trade/cancel-order",
                params={"instId": symbol, "ordId": order_id},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to cancel OKX order: {e}")
            return False

    async def get_positions(self) -> List[Position]:
        """獲取持倉"""
        try:
            result = await self._provider._request("/api/v5/account/positions")
            positions = []
            for pos_data in result:
                positions.append(Position(
                    symbol=pos_data.get("instId", ""),
                    position_amount=float(pos_data.get("pos", 0)),
                    entry_price=float(pos_data.get("avgPx", 0)),
                    mark_price=float(pos_data.get("markPx", 0)),
                    unrealized_profit=float(pos_data.get("upl", 0)),
                    liquidation_price=float(pos_data.get("liqPx", 0)),
                    leverage=int(pos_data.get("lever", 1)),
                    position_side=PositionSide.LONG if pos_data.get("posSide") == "long" else PositionSide.SHORT,
                    notional=float(pos_data.get("notionalUsd", 0)),
                ))
            return positions
        except Exception as e:
            logger.error(f"Failed to get OKX positions: {e}")
            return []

    async def get_balance(self) -> Dict[str, float]:
        """獲取餘額"""
        try:
            result = await self._provider._request("/api/v5/account/balance")
            balances = {}
            for detail in result[0].get("details", []) if result else []:
                currency = detail.get("ccy", "")
                balance = float(detail.get("availBal", 0))
                if balance > 0:
                    balances[currency] = balance
            return balances
        except Exception as e:
            logger.error(f"Failed to get OKX balance: {e}")
            return {}

    async def close(self) -> None:
        """關閉連接"""
        pass

    def _create_dry_run_result(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float],
        position_side: Optional[PositionSide],
    ) -> OrderResult:
        """創建 dry-run 訂單結果"""
        order_id = f"okx_dryrun_{uuid.uuid4().hex[:8]}"
        timestamp = int(datetime.now().timestamp() * 1000)

        logger.info("=" * 60)
        logger.info("[DRY-RUN] OKX 訂單打印 (不會實際執行)")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Side: {side.value}")
        logger.info(f"  Type: {order_type.value}")
        logger.info(f"  Quantity: {quantity}")
        logger.info(f"  Price: {price}")
        logger.info(f"  Position Side: {position_side.value if position_side else 'N/A'}")
        logger.info("=" * 60)

        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            filled_price=price,
            filled_quantity=quantity,
            status="FILLED",
            timestamp=timestamp,
            is_paper=False,
        )

    def _convert_order_type(self, order_type: OrderType) -> str:
        type_map = {
            OrderType.LIMIT: "limit",
            OrderType.MARKET: "market",
            OrderType.STOP_LIMIT: "limit",
            OrderType.STOP_MARKET: "market",
        }
        return type_map.get(order_type, "limit")

    def _convert_side(self, side: OrderSide) -> str:
        side_map = {
            OrderSide.BUY: "buy",
            OrderSide.SELL: "sell",
        }
        return side_map.get(side, "buy")
