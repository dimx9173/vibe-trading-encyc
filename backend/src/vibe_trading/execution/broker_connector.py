"""
Broker Connector 抽象層

提供統一的交易所接口，支持多 broker 路由。
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from vibe_trading.execution.order_executor import (
    OrderResult,
    OrderSide,
    OrderType,
    Position,
    PositionSide,
)


class BrokerType(str, Enum):
    """Broker 類型"""
    BINANCE = "binance"
    OKX = "okx"
    BYBIT = "bybit"
    BITGET = "bitget"
    HYPERLIQUID = "hyperliquid"
    JUPITER = "jupiter"
    PAPER = "paper"


@dataclass
class BrokerConfig:
    """Broker 配置"""
    broker_type: BrokerType
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None  # OKX 需要
    testnet: bool = False
    dry_run: bool = False


class BrokerConnector(ABC):
    """
    Broker Connector 抽象基類
    
    提供統一的交易所接口，所有 broker 實現必須繼承此類。
    """

    @abstractmethod
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
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消訂單"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """獲取持倉"""
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """獲取餘額"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """關閉連接"""
        pass


class BrokerRouter:
    """
    Broker 路由器
    
    根據配置路由訂單到不同的 broker connector。
    """

    def __init__(self, default_broker: BrokerType = BrokerType.BINANCE):
        self.connectors: Dict[BrokerType, BrokerConnector] = {}
        self.default_broker = default_broker

    def register_connector(self, broker_type: BrokerType, connector: BrokerConnector):
        """註冊 broker connector"""
        self.connectors[broker_type] = connector

    def get_connector(self, broker_type: Optional[BrokerType] = None) -> BrokerConnector:
        """獲取 broker connector"""
        broker = broker_type or self.default_broker
        if broker not in self.connectors:
            raise ValueError(f"Broker {broker.value} not registered")
        return self.connectors[broker]

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
        broker: Optional[BrokerType] = None,
    ) -> OrderResult:
        """路由下單到指定 broker"""
        connector = self.get_connector(broker)
        return await connector.place_order(
            symbol, side, order_type, quantity, price, stop_price, position_side, reduce_only
        )

    async def cancel_order(
        self, symbol: str, order_id: str, broker: Optional[BrokerType] = None
    ) -> bool:
        """路由取消訂單到指定 broker"""
        connector = self.get_connector(broker)
        return await connector.cancel_order(symbol, order_id)

    async def get_positions(self, broker: Optional[BrokerType] = None) -> List[Position]:
        """從指定 broker 獲取持倉"""
        connector = self.get_connector(broker)
        return await connector.get_positions()

    async def get_balance(self, broker: Optional[BrokerType] = None) -> Dict[str, float]:
        """從指定 broker 獲取餘額"""
        connector = self.get_connector(broker)
        return await connector.get_balance()

    async def close_all(self) -> None:
        """關閉所有 broker 連接"""
        for connector in self.connectors.values():
            await connector.close()
