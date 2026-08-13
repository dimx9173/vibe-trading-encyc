"""Binance exchange filter validation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from vibe_trading.data_sources.binance_client import SymbolFilters


@dataclass
class ExchangeFilterResult:
    """Result of local exchange filter validation."""

    approved: bool
    reason: str
    filters: Optional[SymbolFilters] = None

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "filters": self.filters.__dict__ if self.filters else None,
        }


class ExchangeFilterValidator:
    """Validate quantity, price and notional against Binance symbol filters."""

    def __init__(self, filters_by_symbol: Dict[str, SymbolFilters]):
        self.filters_by_symbol = filters_by_symbol

    def validate(self, *, symbol: str, quantity: float, price: Optional[float]) -> ExchangeFilterResult:
        filters = self.filters_by_symbol.get(symbol)
        if not filters:
            return ExchangeFilterResult(True, "no exchange filters configured", None)

        if quantity < filters.min_qty:
            return ExchangeFilterResult(False, f"quantity below minQty {filters.min_qty}", filters)
        if filters.max_qty and quantity > filters.max_qty:
            return ExchangeFilterResult(False, f"quantity above maxQty {filters.max_qty}", filters)
        if filters.step_size and not self._is_aligned(quantity, filters.step_size):
            return ExchangeFilterResult(False, f"quantity is not aligned to stepSize {filters.step_size}", filters)

        if price is not None:
            if filters.tick_size and not self._is_aligned(price, filters.tick_size):
                return ExchangeFilterResult(False, f"price is not aligned to tickSize {filters.tick_size}", filters)
            if filters.min_notional and quantity * price < filters.min_notional:
                return ExchangeFilterResult(False, f"order notional below minNotional {filters.min_notional}", filters)

        return ExchangeFilterResult(True, "exchange filters approved", filters)

    def _is_aligned(self, value: float, step: float) -> bool:
        try:
            value_decimal = Decimal(str(value))
            step_decimal = Decimal(str(step))
        except InvalidOperation:
            return False
        if step_decimal == 0:
            return True
        return value_decimal % step_decimal == 0
