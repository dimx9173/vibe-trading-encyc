"""
WebSocket 價格緩存

從 WebSocket 流獲取實時價格，避免頻繁 REST API 調用
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Callable, Awaitable

logger = logging.getLogger(__name__)


class WebSocketPriceCache:
    """
    WebSocket 價格緩存管理器
    
    訂閱 WebSocket 價格流，緩存最新價格，供觸發器系統使用
    """
    
    def __init__(self):
        self._prices: Dict[str, float] = {}  # symbol -> price
        self._timestamps: Dict[str, float] = {}  # symbol -> timestamp
        self._subscribers: Dict[str, List] = {}  # symbol -> list of callbacks
        self._lock = asyncio.Lock()
        self._running = False
        self._ws_client = None
    
    async def start(self, symbols: list[str]):
        """啟動 WebSocket 價格流"""
        if self._running:
            return
        
        self._running = True
        
        # 訂閱 WebSocket 價格流
        try:
            from .binance_client import BinanceWebSocketClient
            
            self._ws_client = BinanceWebSocketClient()
            await self._ws_client.connect()
            
            # 訂閱所有 symbol 的價格流
            streams = [f"{symbol.lower()}@ticker" for symbol in symbols]
            await self._ws_client.subscribe_combined_stream(
                streams=streams,
                callback=self._on_price_update
            )
            
            logger.info(f"WebSocket price cache started for {symbols}")
            
        except Exception as e:
            logger.error(f"Failed to start WebSocket price cache: {e}")
            self._running = False
    
    async def stop(self):
        """停止 WebSocket 價格流"""
        self._running = False
        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None
        logger.info("WebSocket price cache stopped")
    
    def _on_price_update(self, data: dict):
        """處理 WebSocket 價格更新（同步包裝器）"""
        try:
            # 解析 ticker 數據
            symbol = data.get("s", "")  # symbol
            price = float(data.get("c", 0))  # current price
            
            if symbol and price > 0:
                # 使用 create_task 來處理異步操作
                asyncio.create_task(self._process_price_update(symbol, price))
                
        except Exception as e:
            logger.error(f"Error processing price update: {e}")
    
    async def _process_price_update(self, symbol: str, price: float):
        """異步處理價格更新"""
        async with self._lock:
            self._prices[symbol] = price
            self._timestamps[symbol] = time.time()
        
        # 通知訂閱者
        await self._notify_subscribers(symbol, price)
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """
        獲取最新價格
        
        Args:
            symbol: 交易對符號
            
        Returns:
            最新價格，如果沒有數據則返回 None
        """
        async with self._lock:
            return self._prices.get(symbol.upper())
    
    async def get_price_with_fallback(
        self, 
        symbol: str, 
        fallback_func: Optional[Callable[[], Awaitable[Optional[float]]]] = None
    ) -> Optional[float]:
        """
        獲取價格，WebSocket 失敗時使用 REST API 降級
        
        Args:
            symbol: 交易對符號
            fallback_func: REST API 降級函數
            
        Returns:
            價格數據
        """
        # 先嘗試 WebSocket 緩存
        price = await self.get_price(symbol)
        
        if price is not None:
            return price
        
        # WebSocket 沒有數據，使用 REST API 降級
        if fallback_func:
            try:
                logger.warning(f"WebSocket price not available for {symbol}, using REST API fallback")
                price = await fallback_func()
                if price is not None:
                    # 更新緩存
                    async with self._lock:
                        self._prices[symbol.upper()] = price
                        self._timestamps[symbol.upper()] = time.time()
                    return price
            except Exception as e:
                logger.error(f"REST API fallback failed for {symbol}: {e}")
        
        return None
    
    def subscribe(self, symbol: str, callback: Callable[[str, float], Awaitable[None]]):
        """訂閱價格更新"""
        symbol = symbol.upper()
        if symbol not in self._subscribers:
            self._subscribers[symbol] = []
        self._subscribers[symbol].append(callback)
    
    def unsubscribe(self, symbol: str, callback: Callable[[str, float], Awaitable[None]]):
        """取消訂閱"""
        symbol = symbol.upper()
        if symbol in self._subscribers:
            self._subscribers[symbol] = [
                cb for cb in self._subscribers[symbol] if cb != callback
            ]
    
    async def _notify_subscribers(self, symbol: str, price: float):
        """通知訂閱者"""
        symbol = symbol.upper()
        if symbol in self._subscribers:
            for callback in self._subscribers[symbol]:
                try:
                    await callback(symbol, price)
                except Exception as e:
                    logger.error(f"Error notifying subscriber: {e}")
    
    async def get_cache_age(self, symbol: str) -> Optional[float]:
        """獲取緩存年齡（秒）"""
        async with self._lock:
            timestamp = self._timestamps.get(symbol.upper())
            if timestamp is None:
                return None
            return time.time() - timestamp
    
    async def is_fresh(self, symbol: str, max_age: float = 10.0) -> bool:
        """檢查緩存是否新鮮"""
        age = await self.get_cache_age(symbol)
        if age is None:
            return False
        return age < max_age
    
    def get_stats(self) -> dict:
        """獲取緩存統計"""
        return {
            "symbols": list(self._prices.keys()),
            "count": len(self._prices),
            "running": self._running
        }


# 全局實例
_global_price_cache: Optional[WebSocketPriceCache] = None


def get_price_cache() -> WebSocketPriceCache:
    """獲取全局價格緩存"""
    global _global_price_cache
    if _global_price_cache is None:
        _global_price_cache = WebSocketPriceCache()
    return _global_price_cache
