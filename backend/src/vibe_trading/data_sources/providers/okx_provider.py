"""
OKX 交易所数据提供者

实现标准化的 ExchangeProvider 接口，支持 REST API 和 WebSocket 实时数据。
"""
import asyncio
import hashlib
import hmac
import base64
import json
import logging
import time
from typing import List, Optional, Callable, Dict, Any

import aiohttp
import websockets

from .base import ExchangeProvider, ConnectionStatus
from .models import StandardKline, StandardTicker, StandardOrderBook, OrderBookLevel
from ..exchange_config import OkxExchangeConfig

logger = logging.getLogger(__name__)

# OKX interval 格式映射
_INTERVAL_MAP: Dict[str, str] = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W", "1M": "1M",
}

# WebSocket channel 名称映射
_WS_BAR_MAP: Dict[str, str] = {
    "1m": "candle1m", "3m": "candle3m", "5m": "candle5m",
    "15m": "candle15m", "30m": "candle30m",
    "1h": "candle1H", "2h": "candle2H", "4h": "candle4H",
    "6h": "candle6H", "12h": "candle12H",
    "1d": "candle1D", "1w": "candle1W", "1M": "candle1M",
}

# interval -> 毫秒数
_INTERVAL_MS: Dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "12h": 43_200_000, "1d": 86_400_000, "1w": 604_800_000, "1M": 2_592_000_000,
}


class OkxProvider(ExchangeProvider):
    """OKX 交易所数据提供者

    通过 aiohttp 和 websockets 实现 ExchangeProvider 接口。
    """

    def __init__(self, config: OkxExchangeConfig):
        super().__init__(config)
        self.config: OkxExchangeConfig = config

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_listen_task: Optional[asyncio.Task] = None
        self._ws_callbacks: Dict[str, Callable] = {}
        self._subscribed_streams: set = set()

    # ==================== 辅助方法 ====================

    @staticmethod
    def _convert_symbol(symbol: str) -> str:
        """将 BTCUSDT 转换为 OKX 格式 BTC-USDT-SWAP"""
        for quote in ("USDT", "USDC", "BTC", "ETH"):
            if symbol.endswith(quote) and len(symbol) > len(quote):
                base = symbol[: -len(quote)]
                return f"{base}-{quote}-SWAP"
        return symbol

    @staticmethod
    def _okx_bar(interval: str) -> str:
        """将标准 interval 转换为 OKX bar 参数"""
        return _INTERVAL_MAP.get(interval, "30m")

    @staticmethod
    def _interval_to_ms(interval: str) -> int:
        """将 interval 转换为毫秒数"""
        return _INTERVAL_MS.get(interval, 1_800_000)

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """OKX HMAC-SHA256 签名"""
        message = f"{timestamp}{method}{path}{body}"
        mac = hmac.new(
            self.config.api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """构建请求头（含认证）"""
        ts = str(int(time.time()))
        headers = {
            "OK-ACCESS-KEY": self.config.api_key,
            "OK-ACCESS-SIGN": self._sign(ts, method, path, body),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.config.passphrase,
            "Content-Type": "application/json",
        }
        if self.config.demo_trading:
            headers["x-simulated-trading"] = "1"
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """发送 REST API 请求（公开端点无需签名）"""
        session = await self._get_session()
        url = f"{self.config.rest_base_url}{endpoint}"

        headers = {}
        if self.config.demo_trading:
            headers["x-simulated-trading"] = "1"

        async with session.get(url, params=params, headers=headers) as resp:
            data = await resp.json()

        if data.get("code") != "0":
            raise Exception(f"OKX API error: {data.get('msg', data.get('code'))}")

        return data["data"]

    # ==================== 连接管理 ====================

    async def connect(self) -> None:
        """建立连接"""
        try:
            await self._get_session()
            self._status.connected = True
            logger.info(f"OKX provider connected: {self._status}")
        except Exception as e:
            self._status.connected = False
            self._status.last_error = str(e)
            logger.error(f"Failed to connect OKX provider: {e}")
            raise

    async def disconnect(self) -> None:
        """断开连接"""
        try:
            if self._ws_listen_task:
                self._ws_listen_task.cancel()
                self._ws_listen_task = None
            if self._ws:
                await self._ws.close()
                self._ws = None
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None
            self._status.connected = False
            logger.info("OKX provider disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting OKX provider: {e}")

    @property
    def exchange_name(self) -> str:
        return "okx"

    # ==================== 市场数据 ====================

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[StandardKline]:
        """获取K线数据"""
        inst_id = self._convert_symbol(symbol)
        bar = self._okx_bar(interval)

        params: Dict[str, Any] = {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit),
        }
        if start_time:
            params["after"] = str(start_time)  # OKX: after 表示请求此时间戳之后的数据
        if end_time:
            params["before"] = str(end_time)   # OKX: before 表示请求此时间戳之前的数据

        raw_list = await self._request("/api/v5/market/candles", params)

        # OKX 返回 newest-first，反转为时间正序
        raw_list = list(reversed(raw_list))

        return [
            self._convert_kline(raw, symbol, interval)
            for raw in raw_list
        ]

    async def get_ticker(self, symbol: str) -> StandardTicker:
        """获取24小时行情"""
        inst_id = self._convert_symbol(symbol)
        data = await self._request("/api/v5/market/ticker", {"instId": inst_id})
        data = data[0]

        last = float(data["last"])
        open_24h = float(data["open24h"])
        change_pct = ((last - open_24h) / open_24h * 100) if open_24h else 0.0

        return StandardTicker(
            exchange="okx",
            symbol=symbol,
            price_change=last - open_24h,
            price_change_percent=change_pct,
            high=float(data["high24h"]),
            low=float(data["low24h"]),
            volume=float(data["vol24h"]),
            quote_volume=float(data["volCcy24h"]),
            open=open_24h,
            close=last,
            timestamp=int(data.get("ts", time.time() * 1000)),
        )

    async def get_orderbook(self, symbol: str, limit: int = 20) -> StandardOrderBook:
        """获取订单簿"""
        inst_id = self._convert_symbol(symbol)
        data = await self._request("/api/v5/market/books", {
            "instId": inst_id,
            "sz": str(limit),
        })
        data = data[0]

        return StandardOrderBook(
            exchange="okx",
            symbol=symbol,
            bids=[
                OrderBookLevel(price=float(b[0]), quantity=float(b[1]))
                for b in data["bids"][:limit]
            ],
            asks=[
                OrderBookLevel(price=float(a[0]), quantity=float(a[1]))
                for a in data["asks"][:limit]
            ],
            timestamp=int(data.get("ts", 0)),
        )

    async def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        inst_id = self._convert_symbol(symbol)
        data = await self._request("/api/v5/market/ticker", {"instId": inst_id})
        return float(data[0]["last"])

    # ==================== 订阅管理 ====================

    async def _ensure_ws(self) -> None:
        """确保 WebSocket 连接已建立"""
        if self._ws is not None:
            return

        self._ws = await websockets.connect(self.config.ws_base_url)
        self._ws_listen_task = asyncio.create_task(self._ws_listen())
        logger.info("OKX WebSocket connected")

    async def _ws_listen(self) -> None:
        """WebSocket 后台监听任务"""
        try:
            async for message in self._ws:
                data = json.loads(message)
                if "data" in data and "arg" in data:
                    arg = data["arg"]
                    key = f"{arg.get('channel', '')}:{arg.get('instId', '')}"
                    callback = self._ws_callbacks.get(key)
                    if callback:
                        for candle_data in data["data"]:
                            std_kline = self._convert_kline(candle_data, "", "")
                            # 从 channel 推断 symbol 和 interval
                            channel = arg.get("channel", "")
                            # candle1H -> 1H
                            bar = channel.replace("candle", "") if channel.startswith("candle") else ""
                            std_kline = self._convert_ws_kline(
                                candle_data, arg.get("instId", ""), bar
                            )
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(std_kline)
                                else:
                                    callback(std_kline)
                            except Exception as e:
                                logger.error(f"Error in OKX WS callback: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"OKX WebSocket error: {e}")
            self._ws = None

    async def subscribe_klines(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[StandardKline], None],
    ) -> None:
        """订阅K线数据"""
        await self._ensure_ws()

        inst_id = self._convert_symbol(symbol)
        ws_bar = _WS_BAR_MAP.get(interval)
        if not ws_bar:
            logger.warning(f"Unsupported WS interval '{interval}', skipping")
            return

        channel = ws_bar
        key = f"{channel}:{inst_id}"
        stream_key = f"{symbol}@{interval}"

        self._ws_callbacks[key] = callback

        # 发送订阅消息
        subscribe_msg = json.dumps({
            "op": "subscribe",
            "args": [{"channel": channel, "instId": inst_id}],
        })
        await self._ws.send(subscribe_msg)

        self._subscribed_streams.add(stream_key)
        logger.info(f"OKX subscribed to {stream_key}")

    async def unsubscribe_klines(self, symbol: str, interval: str) -> None:
        """取消订阅K线数据"""
        inst_id = self._convert_symbol(symbol)
        ws_bar = _WS_BAR_MAP.get(interval)
        if not ws_bar:
            return

        channel = ws_bar
        key = f"{channel}:{inst_id}"
        stream_key = f"{symbol}@{interval}"

        self._ws_callbacks.pop(key, None)

        if self._ws:
            msg = json.dumps({
                "op": "unsubscribe",
                "args": [{"channel": channel, "instId": inst_id}],
            })
            try:
                await self._ws.send(msg)
            except Exception as e:
                logger.error(f"Failed to send unsubscribe: {e}")

        self._subscribed_streams.discard(stream_key)
        logger.info(f"OKX unsubscribed from {stream_key}")

    # ==================== 数据转换 ====================

    def _convert_kline(self, raw: list, symbol: str, interval: str) -> StandardKline:
        """转换 REST API K线数据为 StandardKline

        OKX 格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        interval_ms = self._interval_to_ms(interval) if interval else 1_800_000
        return StandardKline(
            exchange="okx",
            symbol=symbol,
            interval=interval,
            open_time=int(raw[0]),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            close_time=int(raw[0]) + interval_ms,
            quote_volume=float(raw[7]) if len(raw) > 7 else 0.0,
            trades=0,
            taker_buy_base=0.0,
            taker_buy_quote=0.0,
            is_final=str(raw[8]) == "1" if len(raw) > 8 else True,
        )

    def _convert_ws_kline(self, raw: list, inst_id: str, bar: str) -> StandardKline:
        """转换 WebSocket K线数据为 StandardKline

        WS 格式与 REST 相同: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        # 从 instId 反推 symbol (BTC-USDT-SWAP -> BTCUSDT)
        symbol = inst_id.replace("-", "").replace("SWAP", "")
        # 从 bar 反推 interval (1H -> 1h)
        interval = bar.lower() if bar else ""

        return self._convert_kline(raw, symbol, interval)
