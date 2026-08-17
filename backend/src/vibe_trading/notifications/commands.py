"""TG query command handlers — pure functions returning HTML reply text.

Each handler takes the executor/system it needs and returns a string.
Handlers never raise: callers (TelegramNotifier) wrap invocation in
try/except and reply with the error message instead (grill Q7).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

COMMANDS: Dict[str, str] = {
    "/help": "顯示可用指令",
    "/balance": "查詢資金餘額與權益",
    "/positions": "查詢當前持倉",
    "/status": "查詢系統運行狀態",
    "/decision": "查詢最後一次 agent 決策報告",
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
    """🖥️ 系統狀態 — threads/triggers/emergency + 模型/系統資訊."""
    lines = ["🖥️ <b>VBT 系統狀態</b>"]

    # ── 基本系統資訊 ──
    symbol = getattr(system, "symbol", "?")
    interval = getattr(system, "interval", "?")
    mode = getattr(system, "mode", "?")
    running = getattr(system, "_running", False)
    lines.append(
        f"\n📈 <b>系統</b>: {symbol} {interval} | 模式 <b>{mode}</b> | "
        f"{'🟢 運行中' if running else '🔴 已停止'}"
    )

    # ── 模型 / Provider 資訊 ──
    try:
        from vibe_trading.config.llm_config import get_llm_config
        cfg = get_llm_config()
        name = cfg.get_current_name()
        mcfg = cfg.get_config(name)
        lines.append(
            f"\n🤖 <b>模型</b>: {mcfg.get('model', '?')} "
            f"(<i>{mcfg.get('description', name)}</i>)\n"
            f"   Provider: {mcfg.get('provider', '?')} | "
            f"<code>{mcfg.get('base_url', '?')}</code>"
        )
    except Exception as e:
        logger.warning(f"Model info failed: {e}")
        lines.append("\n🤖 模型: N/A")

    # ── Git 版本 ──
    try:
        import subprocess
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
        ).stdout.strip()
        if commit:
            lines.append(f"\n📦 <b>版本</b>: {branch or '?'} @ <code>{commit}</code>")
    except Exception:
        pass

    # ── 執行器 ──
    ex = getattr(system, "executor", None)
    if ex is not None:
        lines.append(f"\n💼 <b>執行器</b>: {type(ex).__name__}")

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
# last decision
# ---------------------------------------------------------------------------

def _decision_coordinator(system: Any):
    """Resolve the TradingCoordinator from the system object (or None)."""
    onbar = getattr(system, "onbar_thread", None)
    if onbar is None:
        return None
    return getattr(onbar, "_coordinator", None)


async def format_last_decision(system: Any) -> str:
    """📝 最後一次 agent 決策報告 (HTML). No decision → 提示."""
    coordinator = _decision_coordinator(system)
    if coordinator is None or not hasattr(coordinator, "get_decision_history"):
        return "📝 尚無決策 (coordinator 未初始化)"

    history = coordinator.get_decision_history()
    if not history:
        return "📝 尚無決策記錄"

    d = history[-1]
    ts = datetime.fromtimestamp(d.timestamp / 1000).strftime("%m-%d %H:%M") if d.timestamp else "?"
    lines = [
        f"📝 <b>最後一次決策</b> ({ts})",
        f"決策: <b>{d.decision}</b>",
    ]
    # Grounding 駁回顯示 (Phase 1.2)
    meta = getattr(d, "metadata", None) or {}
    grounding = meta.get("grounding") if isinstance(meta, dict) else None
    if grounding and not grounding.get("passed", True):
        violations = grounding.get("violations", [])
        lines.append(f"\n⚠️ <b>Grounding 駁回</b>: {'; '.join(violations)}")
    if d.confidence is not None:
        lines.append(f"信心: {d.confidence:.2f}")
    if d.rationale:
        # 截斷到 ~800 chars, 保留核心理由
        rationale = d.rationale if len(d.rationale) <= 800 else d.rationale[:800] + "…"
        lines.append(f"\n理由:\n{rationale}")

    # 各階段 agent 輸出摘要 (analysts 4 份 + investment_plan + risk + trading_plan)
    outputs = d.agent_outputs or {}
    analysts = outputs.get("analysts") or {}
    if isinstance(analysts, dict) and analysts:
        lines.append("\n📊 分析師:")
        for role, report in analysts.items():
            snippet = str(report)[:120].replace("\n", " ")
            lines.append(f"  • {role}: {snippet}")
    for key, label in (
        ("investment_plan", "📈 投資計劃"),
        ("risk_assessment", "⚠️ 風控評估"),
        ("trading_plan", "🎯 交易方案"),
    ):
        val = outputs.get(key)
        if val:
            snippet = str(val)[:150].replace("\n", " ")
            lines.append(f"\n{label}:\n  {snippet}")

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
