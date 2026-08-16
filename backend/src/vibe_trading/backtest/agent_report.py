"""Agent replay report — aggregate decision JSONL into P&L/decision/cost summary.

P&L 拆解 (grill Q6/Q10):
- realized_pnl  = 末 bar balance − 初 bar balance (已平倉 + 費用)
- unrealized_pnl = 末 bar equity − 末 bar balance (未平倉 mark-to-market)
- total_pnl     = 末 bar equity − 初 bar balance (= realized + unrealized)
- win_rate      = 已平倉 round-trip 盈虧為正的比率 (以 balance 逐 bar 變化判定)
- 單次採樣警告 + 決策分布表 (grill Q5/Q12)
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from vibe_trading.backtest.agent_models import AgentReplayResult, ReplayRecord

logger = logging.getLogger(__name__)


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    """Load decision JSONL, skipping corrupt lines with a warning."""
    out: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            logger.warning(f"Corrupt JSONL line skipped: {e}")
            continue
    return out


def _account_equity(rec: Dict) -> float:
    acct = rec.get("account", {})
    if isinstance(acct, dict) and "equity" in acct:
        return float(acct["equity"])
    if isinstance(acct, dict) and "balance" in acct:
        return float(acct["balance"])
    return 0.0


def _account_balance(rec: Dict) -> float:
    acct = rec.get("account", {})
    if isinstance(acct, dict) and "balance" in acct:
        return float(acct["balance"])
    return 0.0


def _locked_margin(positions: list) -> float:
    """未平倉持倉鎖定的 margin (平倉時返還, 不應算作已實現虧損).

    每倉 margin = entry_price × position_amount / leverage.
    """
    total = 0.0
    for p in positions:
        try:
            total += float(p["entry_price"]) * float(p["position_amount"]) / float(p.get("leverage", 1))
        except (KeyError, TypeError, ValueError):
            continue
    return total


def _unrealized_pnl(rec: Dict) -> float:
    """期末未平倉浮動損益 = equity − balance."""
    return _account_equity(rec) - _account_balance(rec)


def _realized_via_roundtrips(records: List[Dict[str, Any]], initial_balance: float) -> float:
    """已平倉 P&L (含費用, 不含浮動, 不含未返還 margin).

    balance 是可用餘額 (開倉/加倉扣 margin, 平倉返還 + realized)。因此
    有效已實現損益 = balance 變化 + 期末未返還 margin (強平時返還的部分)。
    """
    if not records:
        return 0.0
    end_balance = _account_balance(records[-1])
    end_margin = _locked_margin(records[-1].get("account", {}).get("positions", [])) \
        if isinstance(records[-1].get("account"), dict) else 0.0
    return (end_balance + end_margin) - initial_balance


def build_report(
    log_path: str,
    symbol: str = "BTCUSDT",
    interval: str = "30m",
    usage_db_path: str = "vibe_trading.db",
    initial_balance: float = 10_000.0,
    with_cost: bool = True,
) -> AgentReplayResult:
    """Aggregate a decision JSONL into an AgentReplayResult."""
    raw = load_jsonl(log_path)
    if not raw:
        return AgentReplayResult(symbol=symbol, interval=interval)

    # Normalize nested account.equity into flat ReplayRecord
    records: List[ReplayRecord] = []
    for r in raw:
        records.append(ReplayRecord(
            bar_open_ms=int(r["bar_open_ms"]),
            bar_close=float(r["bar_close"]),
            decision=str(r.get("decision", "HOLD")),
            confidence=r.get("confidence"),
            elapsed_s=float(r.get("elapsed_s", 0.0)),
            balance=_account_balance(r),
            equity=_account_equity(r),
            positions=r.get("account", {}).get("positions", []) if isinstance(r.get("account"), dict) else [],
        ))

    start_equity = records[0].equity if records else initial_balance
    end_equity = records[-1].equity if records else initial_balance
    end_margin = _locked_margin(records[-1].positions) if records else 0.0
    # 真實總損益 = (期末 equity + 未返還 margin) − 期初 equity
    # (margin 平倉時返還, 不應計為虧損)
    total_pnl = (end_equity + end_margin) - start_equity
    unrealized = _unrealized_pnl(raw[-1]) if raw else 0.0  # 期末浮動
    realized = total_pnl - unrealized

    # Win rate: 已平倉 round-trip = 「有效已實現」為正的 bar 比例
    # 有效 = balance Δ − margin Δ (開倉/加倉扣 margin 不計; 平倉返還 margin + realized 才計)
    closed_bars = 0
    winning = 0
    prev_balance = records[0].balance if records else initial_balance
    prev_margin = _locked_margin(records[0].positions) if records else 0.0
    for rec in records[1:]:
        cur_margin = _locked_margin(rec.positions)
        eff_delta = (rec.balance - prev_balance) - (cur_margin - prev_margin)
        if abs(eff_delta) > 1e-9:  # 有已實現事件 (平倉/費用/realized)
            closed_bars += 1
            if eff_delta > 0:
                winning += 1
        prev_balance = rec.balance
        prev_margin = cur_margin
    win_rate = (winning / closed_bars) if closed_bars else 0.0

    decision_counts = dict(Counter(r.decision for r in records))

    llm_cost, llm_calls = 0.0, 0
    if with_cost:
        try:
            from vibe_trading.monitoring.usage_ledger import UsageLedger
            import asyncio

            async def _fetch_cost():
                ledger = UsageLedger(usage_db_path)
                summary = await ledger.get_summary(symbol=symbol)
                return summary

            summary = asyncio.run(_fetch_cost())
            if summary:
                llm_cost = float(summary.total_cost_usd)
                llm_calls = int(summary.total_requests)
        except Exception as e:
            logger.warning(f"Cost summary failed: {e}")

    return AgentReplayResult(
        symbol=symbol,
        interval=interval,
        records=records,
        total_pnl=total_pnl,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        win_rate=win_rate,
        decision_counts=decision_counts,
        llm_cost_usd=llm_cost,
        llm_calls=llm_calls,
    )


def format_report(result: AgentReplayResult) -> str:
    """Render a full text report with single-sample warning (Q5/Q12)."""
    lines = [
        "═══════════════════════════════════════════════",
        " Agent Replay 報告",
        "═══════════════════════════════════════════════",
        f"  {result.symbol} {result.interval} — {len(result.records)} bars",
        f"  Total P&L:     {result.total_pnl:.2f} USDT",
        f"  Realized:      {result.realized_pnl:.2f} USDT (已平倉)",
        f"  Unrealized:    {result.unrealized_pnl:.2f} USDT (末 bar 持倉)",
        f"  Win rate:      {result.win_rate:.1%} (已平倉 round-trips)",
        "",
        "  決策分布:",
    ]
    for decision, count in sorted(result.decision_counts.items(), key=lambda x: -x[1]):
        lines.append(f"    {decision:<12} {count}")
    lines += [
        "",
        f"  LLM 成本:      ${result.llm_cost_usd:.4f} ({result.llm_calls} calls)",
        "",
        "  ⚠️  單次採樣 — LLM 非確定性未聚合 (v1)。",
        "     重跑相同參數 (cache 命中) 可得確定性結果。",
        "═══════════════════════════════════════════════",
    ]
    return "\n".join(lines)
