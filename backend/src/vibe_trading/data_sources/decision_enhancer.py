"""
Decision Enhancer

Decorator that enriches a decision function with optional plugin data
(news/sentiment, liquidation). Degrades gracefully when plugins are
unavailable — the base decision always proceeds.

Part of the external data layer Phase 3 (Task 3.6).
"""
import functools
from typing import Any, Awaitable, Callable, Dict, Optional

from pi_logger import get_logger

logger = get_logger(__name__)


class DecisionEnhancer:
    """Enrich decisions with optional plugin data (decorator pattern)"""

    def __init__(
        self,
        sentiment_plugin: Optional[Any] = None,
        liquidation_plugin: Optional[Any] = None,
    ):
        """
        Args:
            sentiment_plugin: object with async get_sentiment(symbol) + is_available
            liquidation_plugin: object with async fetch(symbol) + is_available
        """
        self.sentiment_plugin = sentiment_plugin
        self.liquidation_plugin = liquidation_plugin

    # ------------------------------------------------------------------
    # Direct data enrichment
    # ------------------------------------------------------------------

    async def gather_context(self, symbol: str) -> Dict[str, Any]:
        """
        Collect optional plugin data for a symbol. Never raises — a plugin
        failure (or unavailability) simply omits that key.
        """
        context: Dict[str, Any] = {}

        if self.sentiment_plugin is not None:
            try:
                if self.sentiment_plugin.is_available:
                    score = await self.sentiment_plugin.get_sentiment(symbol)
                    if score is not None:
                        context["sentiment_score"] = float(score)
                        context["sentiment_source"] = self.sentiment_plugin.name
                    else:
                        logger.debug(f"[Enhancer] sentiment None for {symbol}, skipped")
                else:
                    logger.debug("[Enhancer] sentiment plugin unavailable, skipped")
            except Exception as e:
                logger.warning(f"[Enhancer] sentiment failed for {symbol}: {e}")

        if self.liquidation_plugin is not None:
            try:
                if self.liquidation_plugin.is_available:
                    events = await self.liquidation_plugin.fetch(symbol)
                    if events:
                        context["liquidation_events"] = events
                        context["liquidation_source"] = self.liquidation_plugin.name
                    else:
                        logger.debug(f"[Enhancer] no liquidation events for {symbol}")
                else:
                    logger.debug("[Enhancer] liquidation plugin unavailable, skipped")
            except Exception as e:
                logger.warning(f"[Enhancer] liquidation failed for {symbol}: {e}")

        return context

    # ------------------------------------------------------------------
    # Decorator API
    # ------------------------------------------------------------------

    def enhance(
        self,
        fn: Callable[..., Awaitable[Dict[str, Any]]],
    ) -> Callable[..., Awaitable[Dict[str, Any]]]:
        """
        Wrap an async decision function. The wrapped result dict is enriched
        with an 'enhancements' key containing plugin data (when available).
        The base function is always invoked; plugin failure never blocks it.
        """
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            # Resolve symbol from kwargs (primary) or positional (secondary)
            symbol = kwargs.get("symbol")
            if symbol is None and args:
                symbol = args[0]

            result = await fn(*args, **kwargs)

            if not isinstance(result, dict) or symbol is None:
                return result

            enhancement = await self.gather_context(symbol)
            if enhancement:
                result.setdefault("enhancements", {})
                result["enhancements"].update(enhancement)
            return result

        return wrapper
