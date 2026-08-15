"""Tests for TelegramNotifier (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.notifications.queue import Notification, NotificationPriority
from vibe_trading.notifications.telegram_notifier import TelegramNotifier


@pytest.fixture
def notifier():
    with patch("vibe_trading.notifications.telegram_notifier.Bot"):
        n = TelegramNotifier(bot_token="token", chat_id="123")
        yield n


class TestInit:
    def test_defaults(self, notifier):
        assert notifier.chat_id == "123"
        assert "123" in notifier.allowed_chat_ids
        assert notifier._running is False


class TestFormatNotification:
    def test_format_critical(self, notifier):
        from datetime import datetime
        n = Notification(
            id="n1", priority=NotificationPriority.CRITICAL,
            title="暴跌", message="BTC -10%", timestamp=datetime.now().timestamp(),
        )
        text = notifier._format_notification(n)
        assert "暴跌" in text
        assert "BTC -10%" in text

    def test_format_with_retry(self, notifier):
        from datetime import datetime
        n = Notification(
            id="n1", priority=NotificationPriority.HIGH,
            title="警告", message="m", timestamp=datetime.now().timestamp(),
            retry_count=2, max_retries=3,
        )
        text = notifier._format_notification(n)
        assert "重試次數" in text


class TestSend:
    @pytest.mark.asyncio
    async def test_send_test_message_success(self, notifier):
        notifier.bot.send_message = AsyncMock(return_value=True)
        assert await notifier.send_test_message() is True

    @pytest.mark.asyncio
    async def test_send_test_message_error(self, notifier):
        from telegram.error import TelegramError
        notifier.bot.send_message = AsyncMock(side_effect=TelegramError("down"))
        assert await notifier.send_test_message() is False

    @pytest.mark.asyncio
    async def test_send_startup_notification(self, notifier):
        await notifier.send_startup_notification("BTCUSDT", "30m", "paper")
        pending = await notifier.queue.get_pending_notifications()
        assert len(pending) >= 1

    @pytest.mark.asyncio
    async def test_send_shutdown_notification(self, notifier):
        await notifier.send_shutdown_notification("測試")
        pending = await notifier.queue.get_pending_notifications()
        assert len(pending) >= 1


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_send_notification_calls_bot(self, notifier):
        from datetime import datetime
        notifier.bot.send_message = AsyncMock(return_value=True)
        n = Notification(
            id="n1", priority=NotificationPriority.HIGH,
            title="t", message="m", timestamp=datetime.now().timestamp(),
        )
        await notifier._send_notification(n)
        notifier.bot.send_message.assert_called_once()


class TestIsAllowed:
    def test_allowed(self, notifier):
        assert notifier._is_allowed("123") is True
        assert notifier._is_allowed("999") is False

    def test_allowed_custom(self):
        with patch("vibe_trading.notifications.telegram_notifier.Bot"):
            n = TelegramNotifier(bot_token="t", chat_id="1", allowed_chat_ids=["1", "2"])
        assert n._is_allowed("2") is True
        assert n._is_allowed("3") is False


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_stop(self, notifier):
        with patch.object(notifier, "_notification_loop",
                          new=AsyncMock(side_effect=__import__("asyncio").CancelledError)), \
             patch.object(notifier, "_updates_loop",
                          new=AsyncMock(side_effect=__import__("asyncio").CancelledError)), \
             patch.object(notifier.bot, "set_my_commands", new=AsyncMock()):
            await notifier.start()
            assert notifier._running is True
            await notifier.stop()
            assert notifier._running is False

    @pytest.mark.asyncio
    async def test_start_command_menu_fail(self, notifier):
        with patch.object(notifier, "_notification_loop",
                          new=AsyncMock(side_effect=__import__("asyncio").CancelledError)), \
             patch.object(notifier, "_updates_loop",
                          new=AsyncMock(side_effect=__import__("asyncio").CancelledError)), \
             patch.object(notifier.bot, "set_my_commands",
                          new=AsyncMock(side_effect=RuntimeError("down"))):
            await notifier.start()  # 不 raise
            await notifier.stop()


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_ack_callback(self, notifier):
        cb = MagicMock()
        cb.data = "ack_n1"
        cb.answer = AsyncMock()
        cb.edit_message_text = AsyncMock()
        # 無此 notification → ack 失敗
        result = await notifier.handle_callback(cb)
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_callback(self, notifier):
        cb = MagicMock()
        cb.data = "unknown"
        assert await notifier.handle_callback(cb) is False
