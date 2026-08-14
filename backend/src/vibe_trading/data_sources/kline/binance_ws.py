"""
Binance K-line WebSocket

Real-time K-line data from Binance WebSocket stream.
Supports auto-reconnect with exponential backoff.
"""
import asyncio
import json
import websockets
from typing import List, Optional
from datetime import datetime
from collections import deque
from .base import KlineDataSource
from ..base import Kline


class BinanceKlineWS(KlineDataSource):
    """Binance WebSocket K-line data source"""
    
    def __init__(self, max_buffer_size: int = 1000):
        self._buffer = deque(maxlen=max_buffer_size)
        self._ws = None
        self._reconnect_delay = 1
        self._max_reconnect_delay = 32
        self._available = False
        self._running = False
        self._subscriptions = {}
    
    async def connect(self):
        """Establish WebSocket connection with auto-reconnect"""
        self._running = True
        
        while self._running:
            try:
                self._ws = await websockets.connect(
                    "wss://fstream.binance.com/ws"
                )
                self._reconnect_delay = 1
                self._available = True
                
                # Resubscribe to all symbols
                for key, params in self._subscriptions.items():
                    await self._subscribe(**params)
                
                await self._listen()
            except Exception:
                self._available = False
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )
    
    async def _subscribe(self, symbol: str, interval: str):
        """Subscribe to K-line stream"""
        if self._ws:
            stream = f"{symbol.lower()}@kline_{interval}"
            await self._ws.send(json.dumps({
                "method": "SUBSCRIBE",
                "params": [stream],
                "id": 1
            }))
    
    async def _listen(self):
        """Listen for K-line updates"""
        async for message in self._ws:
            try:
                data = json.loads(message)
                if data.get("e") == "kline":
                    kline_data = data.get("k", {})
                    kline = Kline(
                        symbol=kline_data.get("s", ""),
                        interval=kline_data.get("i", ""),
                        open_time=datetime.fromtimestamp(kline_data.get("t", 0) / 1000),
                        open=float(kline_data.get("o", 0)),
                        high=float(kline_data.get("h", 0)),
                        low=float(kline_data.get("l", 0)),
                        close=float(kline_data.get("c", 0)),
                        volume=float(kline_data.get("v", 0)),
                        close_time=datetime.fromtimestamp(kline_data.get("T", 0) / 1000)
                    )
                    self._buffer.append(kline)
            except Exception:
                continue
    
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Kline]:
        """Get K-line data from buffer"""
        if not self._available:
            return []
        
        # Filter by symbol and interval
        filtered = [
            k for k in self._buffer
            if k.symbol == symbol and k.interval == interval
        ]
        
        # Filter by time range
        if start:
            filtered = [k for k in filtered if k.open_time >= start]
        if end:
            filtered = [k for k in filtered if k.open_time <= end]
        
        # Apply limit
        if limit:
            filtered = filtered[-limit:]
        
        return filtered
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    async def close(self):
        """Close WebSocket connection"""
        self._running = False
        if self._ws:
            await self._ws.close()
