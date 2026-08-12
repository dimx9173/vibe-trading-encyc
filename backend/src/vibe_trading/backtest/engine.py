"""Backtest engine — MA-crossover strategy + order simulator.

Walks historical OHLCV bars, computes SMA crossover signals, simulates
round-trip trades, and produces aggregate P&L statistics.

Callers pass a list of K-line dicts and receive a BacktestResult.
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
    def _sma_series(values: List[float], period: int) -> List[Optional[float]]:
        """Sliding-window SMA — O(N) total instead of O(N·P)."""
        n = len(values)
        if period <= 0 or n < period:
            return [None] * n

        out: List[Optional[float]] = [None] * (period - 1)
        window_sum = sum(values[:period])
        out.append(window_sum / period)
        for i in range(period, n):
            window_sum += values[i] - values[i - period]
            out.append(window_sum / period)
        return out

    @staticmethod
    def _signals_from_klines(
        klines: List[Dict],
        fast_period: int = 10,
        slow_period: int = 30,
    ) -> List[str]:
        """Compute MA-crossover signals: LONG when fast > slow, else FLAT."""
        closes = [float(bar["close"]) for bar in klines]
        fast_sma = BacktestEngine._sma_series(closes, fast_period)
        slow_sma = BacktestEngine._sma_series(closes, slow_period)
        return [
            "LONG" if f is not None and s is not None and f > s else "FLAT"
            for f, s in zip(fast_sma, slow_sma)
        ]

    # === Order simulator ===

    @staticmethod
    def _make_trade(
        entry_price: float, exit_price: float,
        entry_time_ms: int, exit_time_ms: int,
        position_size: float, bars_held: int,
        fee_rate: float = 0.0, slippage_rate: float = 0.0,
    ) -> Trade:
        """Build a Trade with computed P&L fields including fees and slippage."""
        # Apply slippage: entry price worse by slippage_rate, exit price worse by slippage_rate
        actual_entry = entry_price * (1 + slippage_rate)
        actual_exit = exit_price * (1 - slippage_rate)
        
        # Calculate raw P&L
        raw_pnl = (actual_exit - actual_entry) * position_size
        
        # Apply fees on both entry and exit
        entry_fee = actual_entry * position_size * fee_rate
        exit_fee = actual_exit * position_size * fee_rate
        total_fees = entry_fee + exit_fee
        
        pnl = raw_pnl - total_fees
        pnl_pct = (actual_exit - actual_entry) / actual_entry if actual_entry else 0.0
        pnl_pct -= 2 * fee_rate  # Subtract fees from percentage
        
        return Trade(
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

    @staticmethod
    def _simulate(
        klines: List[Dict],
        signals: List[str],
        position_size: float,
        fee_rate: float = 0.0,
        slippage_rate: float = 0.0,
    ) -> List[Trade]:
        """Convert signals into round-trip trades.

        Entry/exit at next bar's open (1-bar delay simplification).
        """
        trades: List[Trade] = []
        in_position = False
        entry_price = 0.0
        entry_time_ms = 0
        entry_idx = 0

        for i in range(len(klines) - 1):
            nxt_open = float(klines[i + 1]["open"])
            nxt_time = int(klines[i + 1]["open_time_ms"])

            if not in_position and signals[i] == "LONG":
                in_position = True
                entry_price = nxt_open
                entry_time_ms = nxt_time
                entry_idx = i + 1
            elif in_position and signals[i] == "FLAT":
                trades.append(BacktestEngine._make_trade(
                    entry_price, nxt_open,
                    entry_time_ms, nxt_time,
                    position_size, (i + 1) - entry_idx,
                    fee_rate, slippage_rate,
                ))
                in_position = False

        # Force-close at last bar if still holding
        if in_position:
            last = klines[-1]
            trades.append(BacktestEngine._make_trade(
                entry_price, float(last["close"]),
                entry_time_ms, int(last["open_time_ms"]),
                position_size, (len(klines) - 1) - entry_idx,
                fee_rate, slippage_rate,
            ))

        return trades

    # === Statistics ===

    @staticmethod
    def _stats_from_trades(
        trades: List[Trade],
        initial_balance: float,
    ) -> Dict[str, float]:
        """Single-pass statistics: P&L, win rate, drawdown, Sharpe."""
        if not trades:
            return {
                "total_pnl": 0.0, "total_pnl_pct": 0.0,
                "winning_trades": 0, "losing_trades": 0, "win_rate": 0.0,
                "avg_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0, "final_balance": initial_balance,
            }

        # Single pass: collect pnls + equity-curve drawdown simultaneously
        pnls: List[float] = []
        equity = initial_balance
        peak = initial_balance
        max_dd = 0.0
        max_dd_pct = 0.0
        sum_wins = 0.0
        sum_losses = 0.0
        n_wins = 0
        n_losses = 0

        for t in trades:
            pnls.append(t.pnl)
            equity += t.pnl
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd / peak if peak else 0.0
            if t.pnl > 0:
                n_wins += 1
                sum_wins += t.pnl
            else:
                n_losses += 1
                sum_losses += t.pnl

        n = len(trades)
        total_pnl = sum(pnls)
        avg_win = sum_wins / n_wins if n_wins else 0.0
        avg_loss = sum_losses / n_losses if n_losses else 0.0

        # Sharpe: per-trade return, sample std
        if n > 1:
            mean = total_pnl / n
            var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
            sharpe = (mean / math.sqrt(var)) if var > 0 else 0.0
        else:
            sharpe = 0.0

        return {
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / initial_balance if initial_balance else 0.0,
            "winning_trades": n_wins,
            "losing_trades": n_losses,
            "win_rate": n_wins / n,
            "avg_pnl": total_pnl / n,
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
        trades = self._simulate(klines, signals, position_size, self.config.fee_rate, self.config.slippage_rate)
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
