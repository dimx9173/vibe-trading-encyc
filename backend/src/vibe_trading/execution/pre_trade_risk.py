"""Deterministic pre-trade risk gate for execution tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide
from vibe_trading.config.settings import get_settings
from vibe_trading.execution.order_executor import OrderExecutor


class RiskVerdict(str, Enum):
    """Pre-trade risk verdict."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class RiskPolicy:
    """Hard limits evaluated before submitting an order."""

    max_single_order_notional: float = 100.0
    max_total_exposure: float = 300.0
    max_margin_fraction: float = 0.5
    position_mode: str = "hedge"

    @classmethod
    def from_settings(cls) -> "RiskPolicy":
        settings = get_settings()
        return cls(
            max_single_order_notional=settings.execution_max_single_order_notional,
            max_total_exposure=settings.execution_max_total_exposure,
            max_margin_fraction=settings.execution_max_margin_fraction,
            position_mode=settings.execution_position_mode,
        )


@dataclass
class PreTradeRiskResult:
    """Pre-trade risk check result."""

    verdict: RiskVerdict
    reason: str
    order_notional: float
    total_exposure: float
    available_balance: Optional[float]
    checks: Dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.verdict == RiskVerdict.APPROVED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "order_notional": self.order_notional,
            "total_exposure": self.total_exposure,
            "available_balance": self.available_balance,
            "checks": self.checks,
        }


class PreTradeRiskGate:
    """Hard pre-trade validator independent from LLM instructions."""

    def __init__(self, executor: OrderExecutor, policy: Optional[RiskPolicy] = None):
        self.executor = executor
        self.policy = policy or RiskPolicy()

    async def validate_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        position_side: PositionSide,
        price: Optional[float] = None,
        reference_price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> PreTradeRiskResult:
        effective_price = price or reference_price or self._executor_reference_price(symbol)
        if effective_price is None or effective_price <= 0:
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason="reference price is required for pre-trade notional checks",
                order_notional=0.0,
                total_exposure=0.0,
                available_balance=None,
            )

        positions = await self.executor.get_positions()
        balance = await self.executor.get_balance()
        total_exposure = sum(abs(pos.notional) for pos in positions)
        available_balance = self._extract_available_balance(balance)
        order_notional = quantity * effective_price

        checks = {
            "symbol": symbol,
            "side": side.value,
            "order_type": order_type.value,
            "position_side": position_side.value,
            "effective_price": effective_price,
            "max_single_order_notional": self.policy.max_single_order_notional,
            "max_total_exposure": self.policy.max_total_exposure,
            "max_margin_fraction": self.policy.max_margin_fraction,
            "position_mode": self.policy.position_mode,
            "reduce_only": reduce_only,
        }

        if self.policy.position_mode == "one_way" and position_side != PositionSide.BOTH:
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason="one-way position mode requires positionSide BOTH",
                order_notional=order_notional,
                total_exposure=total_exposure,
                available_balance=available_balance,
                checks=checks,
            )

        if self.policy.position_mode == "hedge" and position_side == PositionSide.BOTH:
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason="hedge position mode requires positionSide LONG or SHORT",
                order_notional=order_notional,
                total_exposure=total_exposure,
                available_balance=available_balance,
                checks=checks,
            )

        if reduce_only and not self._has_reducible_position(positions, symbol, position_side):
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason="reduce-only order requires an existing matching position",
                order_notional=order_notional,
                total_exposure=total_exposure,
                available_balance=available_balance,
                checks=checks,
            )

        if order_notional > self.policy.max_single_order_notional:
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason=(
                    f"single order notional {order_notional:.2f} exceeds "
                    f"limit {self.policy.max_single_order_notional:.2f}"
                ),
                order_notional=order_notional,
                total_exposure=total_exposure,
                available_balance=available_balance,
                checks=checks,
            )

        if total_exposure + order_notional > self.policy.max_total_exposure:
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason=(
                    f"total exposure {total_exposure + order_notional:.2f} exceeds "
                    f"limit {self.policy.max_total_exposure:.2f}"
                ),
                order_notional=order_notional,
                total_exposure=total_exposure,
                available_balance=available_balance,
                checks=checks,
            )

        if available_balance and order_notional / available_balance > self.policy.max_margin_fraction:
            return PreTradeRiskResult(
                verdict=RiskVerdict.REJECTED,
                reason="order notional exceeds allowed balance fraction",
                order_notional=order_notional,
                total_exposure=total_exposure,
                available_balance=available_balance,
                checks=checks,
            )

        return PreTradeRiskResult(
            verdict=RiskVerdict.APPROVED,
            reason="pre-trade risk checks approved",
            order_notional=order_notional,
            total_exposure=total_exposure,
            available_balance=available_balance,
            checks=checks,
        )

    def _executor_reference_price(self, symbol: str) -> Optional[float]:
        getter = getattr(self.executor, "get_reference_price", None)
        if callable(getter):
            return getter(symbol)
        return None

    def _extract_available_balance(self, balance: Dict[str, Any]) -> Optional[float]:
        usdt = balance.get("USDT")
        if isinstance(usdt, dict):
            value = usdt.get("available", usdt.get("balance"))
            return float(value) if value is not None else None
        if usdt is not None:
            return float(usdt)
        return None

    def _has_reducible_position(self, positions: list, symbol: str, position_side: PositionSide) -> bool:
        for pos in positions:
            if pos.symbol != symbol:
                continue
            if position_side != PositionSide.BOTH and pos.position_side != position_side:
                continue
            if abs(pos.position_amount) > 0:
                return True
        return False
