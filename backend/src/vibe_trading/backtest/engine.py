"""Backtest engine facade.

Phase 1 implementation: a minimal order simulator that walks a list of
historical OHLCV bars, applies a simple MA-crossover signal, and tracks
round-trip trades. The goal is to produce real P&L numbers (win rate, drawdown,
avg win/loss) so callers can evaluate strategy behavior offline.

The interface is intentionally minimal: callers pass a sequence of K-line
dicts (`{"open_time_ms", "open", "high", "low", "close", "volume"}`) and the
engine returns a `BacktestResult`. LLM integration is intentionally out of
scope for this phase — see llm_optimizer.py for the planned extension.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

from vibe_trading.backtest.models import (
    BacktestConfig,
    BacktestResult,
    Trade,
)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


class BacktestEngine:
    """Minimal backtest engine with MA-crossover strategy + order simulator."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    # === Strategy: simple MA crossover ===
    # Buy when fast MA crosses above slow MA, sell (close long) when it crosses
    # below. Long-only for the v1 — no shorts, no leverage, no fees. Returns
    # "LONG" / "FLAT" for each bar's close.

    @staticmethod
    def _sma(values: List[float], period: int) -> Optional[float]:
        if len(values) < period or period <= 0:
            return None
        return sum(values[-period:]) / period

    @staticmethod
    def _signals_from_klines(
        klines: List[Dict],
        fast_period: int = 10,
        slow_period: int = 30,
    ) -> List[str]:
        """Return a list of "LONG" / "FLAT" signals, one per bar at close time."""
        closes: List[float] = []
        signals: List[str] = []
        for bar in klines:
            close = float(bar["close"])
            closes.append(close)
            fast = BacktestEngine._sma(closes, fast_period)
            slow = BacktestEngine._sma(closes, slow_period)
            if fast is None or slow is None:
                signals.append("FLAT")
            elif fast > slow:
                signals.append("LONG")
            else:
                signals.append("FLAT")
        return signals

    # === Order simulator ===

    @staticmethod
    def _simulate(
        klines: List[Dict],
        signals: List[str],
        position_size: float,
    ) -> List[Trade]:
        """Walk bars, convert signals into round-trip trades.

        Conventions: when signal is "LONG" and we are flat, open a long at next
        bar's open. When signal becomes "FLAT" while we hold long, close at next
        bar's open. This 1-bar delay is a simplification — a real backtest would
        model slippage and the actual fill price.
        """
        trades: List[Trade] = []
        in_position = False
        entry_price: float = 0.0
        entry_time_ms: int = 0
        entry_idx: int = 0

        for i in range(len(klines) - 1):
            next_bar = klines[i + 1]
            nxt_open_time = int(next_bar["open_time_ms"])
            nxt_open = float(next_bar["open"])

            if not in_position and signals[i] == "LONG":
                in_position = True
                entry_price = nxt_open
                entry_time_ms = nxt_open_time
                entry_idx = i + 1
            elif in_position and signals[i] == "FLAT":
                exit_price = nxt_open
                exit_time_ms = nxt_open_time
                bars_held = (i + 1) - entry_idx
                pnl = (exit_price - entry_price) * position_size
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
                trades.append(
                    Trade(
                        entry_time=_ms_to_dt(entry_time_ms),
                        exit_time=_ms_to_dt(exit_time_ms),
                        side="LONG",
                        entry_price=entry_price,
                        exit_price=exit_price,
                        position_size=position_size,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        bars_held=bars_held,
                    )
                )
                in_position = False

        # Force-close at the last bar if still holding
        if in_position:
            last = klines[-1]
            exit_price = float(last["close"])
            bars_held = (len(klines) - 1) - entry_idx
            pnl = (exit_price - entry_price) * position_size
            pnl_pct = (exit_price - entry_price) / entry_price if entry_price else 0.0
            trades.append(
                Trade(
                    entry_time=_ms_to_dt(entry_time_ms),
                    exit_time=_ms_to_dt(int(last["open_time_ms"])),
                    side="LONG",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    position_size=position_size,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    bars_held=bars_held,
                )
            )

        return trades

    # === Statistics ===

    @staticmethod
    def _stats_from_trades(
        trades: List[Trade],
        initial_balance: float,
    ) -> Dict[str, float]:
        if not trades:
            return {
                "total_pnl": 0.0,
                "total_pnl_pct": 0.0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_drawdown": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "final_balance": initial_balance,
            }

        pnls = [t.pnl for t in trades]
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]

        total_pnl = sum(pnls)
        total_pnl_pct = total_pnl / initial_balance if initial_balance else 0.0
        win_rate = len(winning) / len(trades)
        avg_pnl = total_pnl / len(trades)
        avg_win = (sum(t.pnl for t in winning) / len(winning)) if winning else 0.0
        avg_loss = (sum(t.pnl for t in losing) / len(losing)) if losing else 0.0

        # Drawdown: walk equity curve, track peak, compute max dip from peak
        equity = initial_balance
        peak = initial_balance
        max_dd = 0.0
        max_dd_pct = 0.0
        for t in trades:
            equity += t.pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd / peak if peak else 0.0

        # Sharpe: assume each trade is a return observation, no time weighting
        if len(pnls) > 1:
            mean = sum(pnls) / len(pnls)
            var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
            std = math.sqrt(var) if var > 0 else 0.0
            sharpe = (mean / std) if std > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_drawdown": max_dd,
            "max_drawdown_pct": max_dd_pct,
            "sharpe_ratio": sharpe,
            "final_balance": initial_balance + total_pnl,
        }

    # === Public entry point ===

    def run(
        self,
        klines: List[Dict],
        fast_period: int = 10,
        slow_period: int = 30,
        position_pct: float = 1.0,
    ) -> BacktestResult:
        """Run the MA-crossover backtest on a list of historical K-lines.

        Args:
            klines: List of dicts with keys: open_time_ms, open, high, low, close, volume.
            fast_period: Fast MA window in bars.
            slow_period: Slow MA window in bars.
            position_pct: Fraction of initial_balance to deploy per trade (0, 1].

        Returns:
            BacktestResult with trades + aggregate stats.
        """
        if not klines:
            return self._empty_result()
        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("MA periods must be positive")
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        if not (0 < position_pct <= 1):
            raise ValueError("position_pct must be in (0, 1]")

        position_size = self.config.initial_balance * position_pct
        signals = self._signals_from_klines(klines, fast_period, slow_period)
        trades = self._simulate(klines, signals, position_size)
        stats = self._stats_from_trades(trades, self.config.initial_balance)

        first = klines[0]
        last = klines[-1]

        return BacktestResult(
            symbol=self.config.symbol,
            interval=self.config.interval,
            start_time=_ms_to_dt(int(first["open_time_ms"])),
            end_time=_ms_to_dt(int(last["open_time_ms"])),
            initial_balance=self.config.initial_balance,
            total_trades=len(trades),
            trades=trades,
            **stats,
        )

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            symbol=self.config.symbol,
            interval=self.config.interval,
            start_time=self.config.start_time,
            end_time=self.config.end_time,
            initial_balance=self.config.initial_balance,
            total_trades=0,
            trades=[],
            total_pnl=0.0,
            total_pnl_pct=0.0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            avg_pnl=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            final_balance=self.config.initial_balance,
        )
