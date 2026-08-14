"""Backtest data loading facade.

Provides a single entry point for backtest engines to load K-line data,
independent of the live plugin layer. Live-only plugins (news/sentiment/
liquidation) are intentionally never loaded through this facade — backtests
are source-consistent by construction (Task 4.3).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Sequence


class DataSource(str, Enum):
    """Supported backtest data sources."""
    BINANCE = "binance"
    LOCAL = "local"
    HYBRID = "hybrid"


class BacktestDataLoader:
    """Data loading facade for backtest engines."""

    def __init__(self, default_source: DataSource = DataSource.HYBRID) -> None:
        self.default_source = default_source

    async def load_klines(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        source: Optional[DataSource] = None,
    ) -> Sequence[object]:
        """
        Load K-line data for backtest.

        Args:
            symbol: trading pair (e.g. "BTCUSDT")
            interval: k-line interval (e.g. "1h", "30m")
            start/end: backtest window
            limit: max bars (live-style fetch)
            source: override default source

        Returns:
            List of Kline objects from the underlying data layer.
        """
        effective = source or self.default_source
        return await self._load_from(effective, symbol, interval, start, end, limit)

    async def _load_from(
        self,
        source: DataSource,
        symbol: str,
        interval: str,
        start: Optional[datetime],
        end: Optional[datetime],
        limit: Optional[int],
    ) -> Sequence[object]:
        """Dispatch to the underlying data source."""
        from vibe_trading.data_sources.kline_storage import KlineQuery, KlineStorage

        def _to_ms(dt: Optional[datetime]) -> Optional[int]:
            return int(dt.timestamp() * 1000) if dt is not None else None

        storage = KlineStorage()
        await storage.init()
        try:
            query = KlineQuery(
                symbol=symbol,
                interval=interval,
                start_time=_to_ms(start),
                end_time=_to_ms(end),
                limit=limit,
            )
            return await storage.query_klines(query)
        finally:
            await storage.close()
