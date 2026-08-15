"""Smart Order Router (SOR) — 跨所最佳報價路由 (Phase 4.1).

向所有 connector 詢價, 選最優執行路徑. fail-safe: 單所失敗不阻塞.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from vibe_trading.execution.broker_connector import BrokerConnector, BrokerType
from vibe_trading.data_sources.binance_client import OrderSide

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    """跨所報價."""
    broker: BrokerType
    price: float
    spread_bps: float = 0.0

    def __str__(self) -> str:
        return f"{self.broker.value}={self.price:.4f}"


class SmartOrderRouter:
    """跨所最佳報價路由."""

    def __init__(self, connectors: Dict[BrokerType, BrokerConnector]):
        self.connectors = connectors

    async def best_quote(self, symbol: str, side: OrderSide) -> Optional[Quote]:
        """向所有 connector 詢價, 回報最佳.

        BUY → 最低價; SELL → 最高價. fail-safe: 詢價失敗的所跳過.
        """
        best: Optional[Quote] = None
        for broker, conn in self.connectors.items():
            try:
                mid = await self._mid_price(conn, symbol)
                if mid is None:
                    continue
                if best is None:
                    best = Quote(broker=broker, price=mid)
                elif side == OrderSide.BUY and mid < best.price:
                    best = Quote(broker=broker, price=mid)
                elif side == OrderSide.SELL and mid > best.price:
                    best = Quote(broker=broker, price=mid)
            except Exception as e:
                logger.warning(f"SOR: {broker.value} quote failed: {e}")
                continue
        return best

    async def quotes_all(self, symbol: str) -> Dict[BrokerType, float]:
        """詢價所有所 (並行), 回報 {broker: mid}."""
        import asyncio

        async def _quote(broker: BrokerType, conn: BrokerConnector) -> Optional[Tuple[BrokerType, float]]:
            try:
                mid = await self._mid_price(conn, symbol)
                return (broker, mid) if mid is not None else None
            except Exception:
                return None

        results = await asyncio.gather(
            *(_quote(b, c) for b, c in self.connectors.items()),
            return_exceptions=True,
        )
        out: Dict[BrokerType, float] = {}
        for r in results:
            if isinstance(r, tuple) and r is not None:
                out[r[0]] = r[1]
        return out

    async def _mid_price(self, conn: BrokerConnector, symbol: str) -> Optional[float]:
        """從 connector 讀中間價 (各所 provider 層)."""
        # 優先使用專用 get_mid_price (Hyperliquid/Jupiter)
        get_mid = getattr(conn, "get_mid_price", None)
        if get_mid is not None:
            return await get_mid(symbol)
        # fallback: 用 get_balance 不可行 — 改為公開 ticker (若有)
        get_ticker = getattr(conn, "get_ticker", None)
        if get_ticker is not None:
            ticker = await get_ticker(symbol)
            bid = getattr(ticker, "bid_price", None)
            ask = getattr(ticker, "ask_price", None)
            if bid is not None and ask is not None:
                return (float(bid) + float(ask)) / 2.0
        raise NotImplementedError(f"{type(conn).__name__} 無報價介面")
