"""Tests for TG query commands (notifications/commands.py) and update routing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.notifications.commands import (
    COMMANDS,
    build_command_menu,
    format_balance,
    format_help,
    format_last_decision,
    format_positions,
    format_status,
)


# === balance ===

class TestBalance:
    @pytest.mark.asyncio
    async def test_paper_nested(self):
        executor = AsyncMock()
        executor.get_balance.return_value = {
            "USDT": {
                "balance": 10000.0,
                "available": 9940.47,
                "unrealized_pnl": -8.35,
                "realized_pnl": 0.0,
            }
        }
        text = await format_balance(executor)
        assert "10000.00" in text
        assert "9940.47" in text
        assert "-8.35" in text
        assert "9991.65" in text  # equity = balance + unrealized

    @pytest.mark.asyncio
    async def test_binance_flat(self):
        executor = AsyncMock()
        executor.get_balance.return_value = {"USDT": 5000.0}
        text = await format_balance(executor)
        assert "5000.00" in text
        assert "5000.00" in text  # available == balance


# === positions ===

class TestPositions:
    @pytest.mark.asyncio
    async def test_empty(self):
        executor = AsyncMock()
        executor.get_positions.return_value = []
        text = await format_positions(executor)
        assert "無持倉" in text

    @pytest.mark.asyncio
    async def test_table(self):
        pos = SimpleNamespace(
            symbol="BTCUSDT",
            position_side=SimpleNamespace(value="LONG"),
            position_amount=0.0046,
            entry_price=64707.70,
            mark_price=62892.0,
            unrealized_profit=-8.35,
            notional=297.66,
        )
        executor = AsyncMock()
        executor.get_positions.return_value = [pos]
        text = await format_positions(executor)
        assert "BTCUSDT" in text
        assert "LONG" in text
        assert "64707.70" in text
        assert "-8.35" in text
        assert "297.66" in text


# === status ===

class TestStatus:
    @pytest.mark.asyncio
    async def test_aggregates(self):
        system = SimpleNamespace(
            emergency_handler=SimpleNamespace(get_statistics=lambda: {
                "total_handled": 3, "executed": 1, "deferred": 1,
                "ignored": 1, "errors": 0,
            }),
            thread_manager=AsyncMock(),
            trigger_registry=SimpleNamespace(get_all=lambda: {"a": 1, "b": 2}),
        )
        system.thread_manager.get_statistics = AsyncMock(return_value={
            "total_threads": 2,
            "status_counts": {"running": 2},
        })
        text = await format_status(system)
        assert "3 handled" in text
        assert "2" in text  # threads
        assert "2 registered" in text  # triggers

    @pytest.mark.asyncio
    async def test_missing_parts_ok(self):
        # system with no emergency_handler/thread_manager — must not raise
        system = SimpleNamespace(trigger_registry=None)
        text = await format_status(system)
        assert "系統狀態" in text


# === help ===

class TestHelp:
    def test_lists_commands(self):
        text = format_help()
        for cmd in COMMANDS:
            assert cmd in text

    def test_command_menu_built(self):
        menu = build_command_menu()
        assert len(menu) == len(COMMANDS)
        commands = [m.command for m in menu]
        assert "/balance" in commands
        assert "/help" in commands
        assert all(m.description for m in menu)


class TestLastDecision:
    @pytest.mark.asyncio
    async def test_no_coordinator(self):
        system = SimpleNamespace(onbar_thread=None)
        text = await format_last_decision(system)
        assert "尚無決策" in text

    @pytest.mark.asyncio
    async def test_no_history(self):
        coordinator = SimpleNamespace(get_decision_history=lambda: [])
        onbar = SimpleNamespace(_coordinator=coordinator)
        system = SimpleNamespace(onbar_thread=onbar)
        text = await format_last_decision(system)
        assert "尚無決策" in text

    @pytest.mark.asyncio
    async def test_formats_last_decision(self):
        from datetime import datetime, timezone
        decision = SimpleNamespace(
            symbol="BTCUSDT",
            timestamp=int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp() * 1000),
            decision="BUY",
            confidence=0.8,
            rationale="Strong momentum with volume confirmation",
            execution_instructions=None,
            agent_outputs={
                "analysts": {"technical": "Bullish trend detected"},
                "investment_plan": "Add 0.0015 BTC",
                "risk_assessment": "Medium risk",
                "trading_plan": "Limit order at 62000",
            },
        )
        coordinator = SimpleNamespace(get_decision_history=lambda: [decision])
        onbar = SimpleNamespace(_coordinator=coordinator)
        system = SimpleNamespace(onbar_thread=onbar)
        text = await format_last_decision(system)
        assert "BUY" in text
        assert "0.80" in text
        assert "Strong momentum" in text
        assert "technical" in text
        assert "Medium risk" in text


# === update routing ===

class TestNotifierRouting:
    def _make_notifier(self, bot):
        from vibe_trading.notifications.telegram_notifier import TelegramNotifier
        with patch("vibe_trading.notifications.telegram_notifier.Bot", return_value=bot):
            return TelegramNotifier(
                "token", "1001",
                executor=AsyncMock(), system=SimpleNamespace(),
                allowed_chat_ids=["1001"],
            )

    @pytest.mark.asyncio
    async def test_command_authorized_replies(self):
        bot = MagicMock()
        notifier = self._make_notifier(bot)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=1001),
            reply_text=AsyncMock(),
            text="/balance",
        )
        await notifier._handle_command(message, "/balance")
        assert message.reply_text.await_count == 1
        call = message.reply_text.await_args
        assert "資金餘額" in call.args[0]
        assert call.kwargs["parse_mode"] == "HTML"
        assert "refresh:balance" in str(call.kwargs["reply_markup"])

    @pytest.mark.asyncio
    async def test_command_unauthorized_ignored(self):
        bot = MagicMock()
        notifier = self._make_notifier(bot)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=9999),
            reply_text=AsyncMock(),
            text="/balance",
        )
        await notifier._handle_command(message, "/balance")
        assert message.reply_text.await_count == 0

    @pytest.mark.asyncio
    async def test_refresh_callback_edits(self):
        bot = MagicMock()
        notifier = self._make_notifier(bot)
        cb = SimpleNamespace(
            data="refresh:balance",
            edit_message_text=AsyncMock(),
            answer=AsyncMock(),
        )
        await notifier._handle_callback_query(cb)
        assert cb.edit_message_text.await_count == 1
        call = cb.edit_message_text.await_args
        assert "資金餘額" in call.args[0]
        assert call.kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_query_failure_replies_error(self):
        bot = MagicMock()
        executor = AsyncMock()
        executor.get_balance.side_effect = RuntimeError("API down")
        from vibe_trading.notifications.telegram_notifier import TelegramNotifier
        with patch("vibe_trading.notifications.telegram_notifier.Bot", return_value=bot):
            notifier = TelegramNotifier(
                "token", "1001", executor=executor, system=SimpleNamespace(),
                allowed_chat_ids=["1001"],
            )
        text = await notifier._run_query("balance")
        assert "查詢失敗" in text

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        bot = MagicMock()
        notifier = self._make_notifier(bot)
        text = await notifier._run_query("nonexistent")
        assert "未知指令" in text

    @pytest.mark.asyncio
    async def test_update_loop_offset_monotonic(self):
        bot = MagicMock()
        notifier = self._make_notifier(bot)
        update = SimpleNamespace(update_id=42, callback_query=None, message=None)
        await notifier._handle_update(update)
        assert notifier._update_offset == 43
