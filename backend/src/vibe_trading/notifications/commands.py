"""TG query command handlers — pure functions returning HTML reply text.

Each handler takes the executor/system it needs and returns a string.
Handlers never raise: callers (TelegramNotifier) wrap invocation in
try/except and reply with the error message instead (grill Q7).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

COMMANDS: Dict[str, str] = {
    "/help": "顯示可用指令",
    "/balance": "查詢資金餘額與權益",
    "/positions": "查詢當前持倉",
    "/status": "查詢系統運行狀態",
}


# ---------------------------------------------------------------------------
# balance
# ---------------------------------------------------------------------------

def _extract_balance(balances: Any) -> Dict[str, float]:
    """Normalize get_balance() output.

    PaperOrderExecutor returns {"USDT": {balance, available, unrealized_pnl,
    realized_pnl}} (nested); BinanceOrderExecutor returns {USDT: float} (flat).
    """
    usdt = balances.get("USDT", 0.0) if isinstance(balances, dict) else 0.0
    if isinstance(usdt, dict):
        return {
            "balance": float(usdt.get("balance") or 0.0),
            "available": float(usdt.get("available") or usdt.get("balance") or 0.0),
            "unrealized": float(usdt.get("unrealized_pnl") or 0.0),
            "realized": float(usdt.get("realized_pnl") or 0.0),
        }
    return {
        "balance": float(usdt),
        "available": float(usdt),
        "unrealized": 0.0,
        "realized": 0.0,
    }


async def format_balance(executor: Any) -> str:
    """💰 資金餘額 (HTML)."""
    balances = await executor.get_balance()
    b = _extract_balance(balances)
    equity = b["balance"] + b["unrealized"]
    return (
        "💰 <b>資金餘額</b>\n"
        f"Balance:   {b['balance']:.2f} USDT\n"
        f"Available: {b['available']:.2f}\n"
        f"Unrealized: {b['unrealized']:.2f}\n"
        f"Realized:  {b['realized']:.2f}\n"
        f"Equity:    <b>{equity:.2f}</b>"
    )


# ---------------------------------------------------------------------------
# positions
# ---------------------------------------------------------------------------

async def format_positions(executor: Any) -> str:
    """📊 持倉列表 (HTML). Empty → 無持倉."""
    positions = await executor.get_positions()
    if not positions:
        return "📊 無持倉"

    lines = ["📊 <b>持倉</b>"]
    for p in positions:
        side = str(getattr(p.position_side, "value", p.position_side))
        lines.append(
            f"\n<b>{p.symbol}</b> {side} {p.position_amount:.6f}\n"
            f"  Entry: {p.entry_price:.2f} | Mark: {p.mark_price:.2f}\n"
            f"  uPnL: {p.unrealized_profit:+.2f} "
            f"({(p.mark_price / p.entry_price - 1) * 100:+.2f}%) | "
            f"Notional: {p.notional:.2f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

async def format_status(system: Any) -> str:
    """🖥️ 系統狀態 — threads/triggers/emergency stats."""
    lines = ["🖥️ <b>系統狀態</b>"]

    # Emergency handler stats
    eh = getattr(system, "emergency_handler", None)
    if eh is not None and hasattr(eh, "get_statistics"):
        try:
            stats = eh.get_statistics()
            lines.append(
                f"\n🚨 Emergency: {stats.get('total_handled', 0)} handled "
                f"(executed {stats.get('executed', 0)} / "
                f"deferred {stats.get('deferred', 0)} / "
                f"ignored {stats.get('ignored', 0)} / "
                f"errors {stats.get('errors', 0)})"
            )
        except Exception as e:
            logger.warning(f"Emergency stats failed: {e}")

    # Thread manager stats
    tm = getattr(system, "thread_manager", None)
    if tm is not None and hasattr(tm, "get_statistics"):
        try:
            tstats = await tm.get_statistics()
            lines.append(
                f"\n🧵 Threads: {tstats.get('total_threads', 0)} "
                f"({tstats.get('status_counts', {})})"
            )
        except Exception as e:
            logger.warning(f"Thread stats failed: {e}")

    # Trigger registry
    tr = getattr(system, "trigger_registry", None)
    if tr is not None and hasattr(tr, "get_all"):
        try:
            triggers = tr.get_all()
            lines.append(f"\n🎯 Triggers: {len(triggers)} registered")
        except Exception as e:
            logger.warning(f"Trigger stats failed: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------

def format_help() -> str:
    """❓ 可用指令."""
    lines = ["❓ <b>可用指令</b>"]
    for cmd, desc in COMMANDS.items():
        lines.append(f"\n{cmd} — {desc}")
    lines.append("\n💡 點擊回覆中的 🔄 按鈕可重新查詢")
    return "\n".join(lines)


def build_command_menu() -> list:
    """Build Telegram BotCommand menu from COMMANDS (輸入 / 時彈出選單)."""
    from telegram import BotCommand

    return [
        BotCommand(command=cmd, description=desc)
        for cmd, desc in COMMANDS.items()
    ]
