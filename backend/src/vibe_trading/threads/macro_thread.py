"""
Macro Analysis Thread

Runs macro analysis on a periodic basis (2hr) with 24hr of 30m klines fed to LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Optional
from datetime import datetime
import time

from vibe_trading.agents.macro_agent import MacroAnalysisAgent
from vibe_trading.data_sources.macro_storage import MacroStorage, get_macro_storage
from vibe_trading.agents.agent_factory import ToolContext
from vibe_trading.agents.messaging import get_message_broker, MessageType
from vibe_trading.tools import sentiment_tools, fundamental_tools, market_data_tools

if TYPE_CHECKING:
    from vibe_trading.data_sources.kline_storage import KlineStorage

logger = logging.getLogger(__name__)


class MacroAnalysisThread:
    """
    Macro analysis thread

    Runs periodically to analyze the macro environment and update the macro state.
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        interval_seconds: int = 7200,  # 2hr: LLM 判斷週期
        storage: Optional[MacroStorage] = None,
        kline_storage: Optional["KlineStorage"] = None,
        kline_lookback_hours: int = 24,
        kline_interval: str = "30m",
    ):
        """
        Initialize macro analysis thread

        Args:
            symbol: Trading symbol to analyze
            interval_seconds: Analysis interval in seconds (default 2hr)
            storage: Macro storage instance
            kline_storage: KlineStorage for 24hr K線投喂 (optional, graceful fallback)
            kline_lookback_hours: 回看多少小時的 K 線喂給 LLM (default 24hr)
            kline_interval: K 線週期 (default 30m, 24hr=48根)
        """
        self.symbol = symbol
        self.interval_seconds = interval_seconds
        self.storage = storage or get_macro_storage()
        self.kline_storage = kline_storage
        self.kline_lookback_hours = kline_lookback_hours
        self.kline_interval = kline_interval

        # Initialize agent
        self._agent: Optional[MacroAnalysisAgent] = None
        self._tool_context: Optional[ToolContext] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Statistics
        self._total_runs = 0
        self._successful_runs = 0
        self._failed_runs = 0
        self._last_run_time: Optional[datetime] = None

        logger.info(
            f"MacroAnalysisThread initialized for {symbol} "
            f"(interval={interval_seconds}s, lookback={kline_lookback_hours}h@{kline_interval})"
        )

    async def initialize(self) -> None:
        """Initialize the thread"""
        # Initialize storage
        await self.storage.init()

        # Create tool context
        self._tool_context = ToolContext(
            symbol=self.symbol,
            interval="1h",
        )

        # Initialize macro agent
        self._agent = MacroAnalysisAgent()
        await self._agent.initialize(self._tool_context, enable_streaming=False)

        logger.info("MacroAnalysisThread initialized")

    async def start(self) -> None:
        """Start the macro analysis thread"""
        if self._running:
            logger.warning("MacroAnalysisThread already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("MacroAnalysisThread started")

    async def stop(self) -> None:
        """Stop the macro analysis thread"""
        if not self._running:
            logger.warning("MacroAnalysisThread not running")
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("MacroAnalysisThread stopped")

    async def _run_loop(self) -> None:
        """Main loop for macro analysis"""
        while self._running:
            try:
                # Check if should run
                should_run = await self._should_update()

                if should_run:
                    await self._run_analysis()
                else:
                    logger.debug("Skipping macro analysis (already up to date)")

                # Wait for next interval
                await asyncio.sleep(self.interval_seconds)

            except asyncio.CancelledError:
                logger.info("MacroAnalysisThread cancelled")
                break
            except Exception as e:
                logger.error(f"Error in macro analysis loop: {e}", exc_info=True)
                self._failed_runs += 1
                await asyncio.sleep(60)  # Wait 1 minute before retry

    async def _should_update(self) -> bool:
        """
        Check if macro analysis should be updated

        Returns:
            True if update is needed
        """
        # Get latest state
        latest_state = await self.storage.get_latest_state(self.symbol)

        if latest_state is None:
            return True

        # Check if latest state is older than interval
        latest_timestamp = latest_state.timestamp / 1000  # Convert to seconds
        current_timestamp = time.time()

        time_since_last = current_timestamp - latest_timestamp

        return time_since_last >= self.interval_seconds

    async def _run_analysis(self) -> None:
        """Run macro analysis"""
        start_time = time.time()

        try:
            self._total_runs += 1
            logger.info(f"Starting macro analysis for {self.symbol}")

            # Collect market data
            market_data = await self._collect_market_data()

            # Perform analysis
            analysis = await self._agent.analyze(market_data)

            # Create macro state
            analysis_duration = time.time() - start_time
            macro_state = await self._agent.create_macro_state(
                symbol=self.symbol,
                analysis=analysis,
                analysis_duration=analysis_duration,
            )

            # Save to storage
            saved = await self.storage.save_state(macro_state)

            if saved:
                self._successful_runs += 1
                self._last_run_time = datetime.now()

                logger.info(
                    f"Macro analysis completed: {macro_state.market_regime} "
                    f"(trend={macro_state.trend_direction}, "
                    f"sentiment={macro_state.overall_sentiment}, "
                    f"confidence={macro_state.confidence:.2f})"
                )

                # Notify other threads
                await self._notify_update(macro_state)
            else:
                self._failed_runs += 1
                logger.error("Failed to save macro state")

        except Exception as e:
            self._failed_runs += 1
            logger.error(f"Error running macro analysis: {e}", exc_info=True)

    def _interval_to_minutes(self, interval: str) -> int:
        mapping = {
            "1m": 1,
            "3m": 3,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "2h": 120,
            "4h": 240,
            "6h": 360,
            "8h": 480,
            "12h": 720,
            "1d": 1440,
            "3d": 4320,
            "1w": 10080,
            "1M": 43200,
        }
        return mapping.get(interval, 30)

    async def _collect_klines_24h(self) -> Optional[list]:
        if not getattr(self, "kline_storage", None):
            return None
        try:
            from vibe_trading.data_sources.kline_storage import KlineQuery

            lookback = getattr(self, "kline_lookback_hours", 24)
            interval = getattr(self, "kline_interval", "30m")
            interval_min = self._interval_to_minutes(interval)
            limit = max(1, int(lookback * 60 / interval_min))
            storage = getattr(self, "kline_storage", None)
            if storage is None:
                return None
            rows = await storage.query_klines(
                KlineQuery(symbol=self.symbol, interval=interval, limit=limit)
            )
            if not rows:
                return None
            out = []
            for r in rows[-limit:]:
                out.append(
                    {
                        "t": int(getattr(r, "open_time", 0) or 0),
                        "o": float(getattr(r, "open", 0.0)),
                        "h": float(getattr(r, "high", 0.0)),
                        "l": float(getattr(r, "low", 0.0)),
                        "c": float(getattr(r, "close", 0.0)),
                        "v": float(getattr(r, "volume", 0.0)),
                    }
                )
            return out
        except Exception as e:
            logger.warning(f"Failed to collect 24h klines for LLM: {e}")
            return None

    async def _collect_market_data(self) -> Dict:
        """
        Collect market data for macro analysis

        Returns:
            Dictionary of market data
        """
        market_data: Dict = {
            "symbol": self.symbol,
        }

        try:
            # Get fear/greed index
            fg_data = await sentiment_tools.get_fear_and_greed_index()
            market_data["fear_greed"] = fg_data
            logger.debug("Collected fear/greed index")
        except Exception as e:
            logger.warning(f"Failed to get fear/greed index: {e}")

        try:
            # Get funding rate
            fr_data = await fundamental_tools.get_funding_rates(self.symbol)
            market_data["funding_rate"] = fr_data
            logger.debug("Collected funding rate")
        except Exception as e:
            logger.warning(f"Failed to get funding rate: {e}")

        try:
            # Get 24h ticker
            ticker_data = await market_data_tools.get_24hr_ticker(self.symbol)
            market_data["ticker_24h"] = ticker_data
            logger.debug("Collected 24h ticker")
        except Exception as e:
            logger.warning(f"Failed to get 24h ticker: {e}")

        try:
            # Get trending symbols
            trending_data = await sentiment_tools.get_trending_symbols()
            market_data["trending"] = trending_data
            logger.debug("Collected trending symbols")
        except Exception as e:
            logger.warning(f"Failed to get trending symbols: {e}")

        klines_24h = await self._collect_klines_24h()
        if klines_24h:
            market_data["klines_24h"] = klines_24h
            market_data["klines_24h_interval"] = getattr(self, "kline_interval", "30m")
            market_data["klines_24h_hours"] = getattr(self, "kline_lookback_hours", 24)
            logger.debug(f"Collected {len(klines_24h)} klines for 24h context")

        return market_data

    async def _notify_update(self, macro_state) -> None:
        """
        Notify other threads of macro state update

        Args:
            macro_state: Updated macro state
        """
        message_broker = get_message_broker()

        message_broker.send(
            sender="macro_thread",
            receiver="all",
            message_type=MessageType.INFO,
            content={
                "type": "macro_state_update",
                "symbol": self.symbol,
                "state": macro_state.to_dict(),
            },
            correlation_id=f"macro_{int(time.time() * 1000)}",
        )

        logger.debug(f"Macro state update notified: {macro_state.market_regime}")

    def get_statistics(self) -> Dict:
        """
        Get thread statistics

        Returns:
            Dictionary of statistics
        """
        return {
            "symbol": self.symbol,
            "running": self._running,
            "interval_seconds": self.interval_seconds,
            "total_runs": self._total_runs,
            "successful_runs": self._successful_runs,
            "failed_runs": self._failed_runs,
            "success_rate": (
                self._successful_runs / self._total_runs
                if self._total_runs > 0
                else 0.0
            ),
            "last_run_time": (
                self._last_run_time.isoformat() if self._last_run_time else None
            ),
        }

    async def run_once(self) -> Optional[Dict]:
        """
        Run macro analysis once (for testing or manual trigger)

        Returns:
            Macro state or None if failed
        """
        try:
            start_time = time.time()
            logger.info(f"Running macro analysis once for {self.symbol}")

            # Collect market data
            market_data = await self._collect_market_data()

            # Perform analysis
            analysis = await self._agent.analyze(market_data)

            # Create macro state
            analysis_duration = time.time() - start_time
            macro_state = await self._agent.create_macro_state(
                symbol=self.symbol,
                analysis=analysis,
                analysis_duration=analysis_duration,
            )

            # Save to storage
            saved = await self.storage.save_state(macro_state)

            if saved:
                logger.info(f"Macro analysis completed: {macro_state.market_regime}")
                return macro_state.to_dict()
            else:
                logger.error("Failed to save macro state")
                return None

        except Exception as e:
            logger.error(f"Error running macro analysis once: {e}", exc_info=True)
            return None
