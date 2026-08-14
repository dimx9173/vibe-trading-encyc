"""
Binance WebSocket Liquidation Plugin

Real-time liquidation data from Binance Futures WebSocket stream.
Endpoint: wss://fstream.binance.com/ws/!forceOrder@arr
"""
import asyncio
import json
import websockets
from typing import Optional, List
from datetime import datetime
from collections import deque
from .base import LiquidationPlugin, LiquidationData


class BinanceLiquidationWS(LiquidationPlugin):
    """Binance WebSocket liquidation plugin"""
    
    def __init__(self, max_buffer_size: int = 1000):
        self.endpoint = "wss://fstream.binance.com/ws/!forceOrder@arr"
        self._buffer = deque(maxlen=max_buffer_size)
        self._ws = None
        self._reconnect_delay = 1
        self._max_reconnect_delay = 32
        self._available = False
        self._running = False
    
    async def connect(self):
        """Establish WebSocket connection with auto-reconnect"""
        self._running = True
        
        while self._running:
            try:
                self._ws = await websockets.connect(self.endpoint)
                self._reconnect_delay = 1
                self._available = True
                await self._listen()
            except Exception as e:
                self._available = False
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )
    
    async def _listen(self):
        """Listen for liquidation events"""
        async for message in self._ws:
            try:
                data = json.loads(message)
                if data.get("e") == "forceOrder":
                    order = data.get("o", {})
                    liquidation = LiquidationData(
                        symbol=order.get("s", ""),
                        side="long" if order.get("S") == "SELL" else "short",
                        price=float(order.get("p", 0)),
                        quantity=float(order.get("q", 0)),
                        usd_value=float(order.get("p", 0)) * float(order.get("q", 0)),
                        exchange="Binance",
                        timestamp=datetime.fromtimestamp(order.get("T", 0) / 1000)
                    )
                    self._buffer.append(liquidation)
            except Exception:
                continue
    
    async def fetch(self, symbol: str, **kwargs) -> Optional[List[LiquidationData]]:
        """Get liquidation data from buffer"""
        if not self._available:
            return None
        
        relevant = [
            item for item in self._buffer
            if item.symbol == symbol
        ]
        
        return relevant if relevant else None
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    async def close(self):
        """Close WebSocket connection"""
        self._running = False
        if self._ws:
            await self._ws.close()
