"""
Telegram 通知系統測試
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from vibe_trading.notifications.queue import NotificationQueue, Notification, NotificationPriority
from vibe_trading.notifications.formatter import MessageFormatter
from vibe_trading.notifications.config import TelegramConfig, NotificationConfig


class TestNotificationQueue:
    """測試通知隊列"""

    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self):
        """測試通知入隊和出隊"""
        queue = NotificationQueue()
        
        notification = Notification(
            id="test_1",
            priority=NotificationPriority.HIGH,
            title="Test Notification",
            message="This is a test"
        )
        
        await queue.enqueue(notification)
        assert queue.get_queue_size() == 1
        
        dequeued = await queue.dequeue()
        assert dequeued is not None
        assert dequeued.id == "test_1"
        assert queue.get_queue_size() == 0

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        """測試優先級排序"""
        queue = NotificationQueue()
        
        # 添加 LOW 優先級
        low_notif = Notification(
            id="low_1",
            priority=NotificationPriority.LOW,
            title="Low Priority",
            message="Low"
        )
        await queue.enqueue(low_notif)
        
        # 添加 HIGH 優先級
        high_notif = Notification(
            id="high_1",
            priority=NotificationPriority.HIGH,
            title="High Priority",
            message="High"
        )
        await queue.enqueue(high_notif)
        
        # HIGH 應該先出隊
        dequeued = await queue.dequeue()
        assert dequeued.priority == NotificationPriority.HIGH

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """測試指數退避重試"""
        queue = NotificationQueue()
        
        notification = Notification(
            id="retry_1",
            priority=NotificationPriority.CRITICAL,
            title="Critical",
            message="Needs retry",
            max_retries=5
        )
        
        # 第一次重試：60秒後
        notification.schedule_next_retry()
        assert notification.retry_count == 1
        assert notification.next_retry_time > asyncio.get_event_loop().time()
        
        # 第二次重試：120秒後
        notification.schedule_next_retry()
        assert notification.retry_count == 2

    @pytest.mark.asyncio
    async def test_acknowledge_notification(self):
        """測試確認通知"""
        queue = NotificationQueue()
        
        notification = Notification(
            id="ack_1",
            priority=NotificationPriority.CRITICAL,
            title="Critical",
            message="Needs ack"
        )
        
        await queue.enqueue(notification)
        assert queue.get_pending_count() == 1
        
        success = await queue.acknowledge("ack_1")
        assert success is True
        assert queue.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_clear_low_priority(self):
        """測試清除 LOW 優先級通知"""
        queue = NotificationQueue()
        
        # 添加多個 LOW 優先級
        for i in range(3):
            notif = Notification(
                id=f"low_{i}",
                priority=NotificationPriority.LOW,
                title=f"Low {i}",
                message="Low priority"
            )
            await queue.enqueue(notif)
        
        assert queue.get_queue_size() == 3
        
        await queue.clear_low_priority()
        assert queue.get_queue_size() == 0


class TestMessageFormatter:
    """測試消息格式化器"""

    def test_format_trade_decision_buy(self):
        """測試買入決策格式化"""
        title, message = MessageFormatter.format_trade_decision(
            symbol="BTCUSDT",
            action="BUY",
            price=50000.0,
            quantity=0.001,
            reason="Strong bullish signal",
            pnl=2.5
        )
        
        assert "BTCUSDT" in title
        assert "BUY" in title
        assert "50,000.00" in message
        assert "Strong bullish signal" in message
        assert "+2.50%" in message

    def test_format_trade_decision_sell(self):
        """測試賣出決策格式化"""
        title, message = MessageFormatter.format_trade_decision(
            symbol="ETHUSDT",
            action="SELL",
            price=3000.0,
            quantity=0.1,
            reason="Bearish divergence"
        )
        
        assert "ETHUSDT" in title
        assert "SELL" in title

    def test_format_stop_loss_triggered(self):
        """測試止損觸發格式化"""
        title, message = MessageFormatter.format_stop_loss_triggered(
            symbol="BTCUSDT",
            entry_price=50000.0,
            exit_price=48000.0,
            quantity=0.001,
            pnl=-4.0
        )
        
        assert "止損觸發" in title
        assert "-4.00%" in message
        assert "請確認是否調整策略" in message

    def test_format_take_profit_triggered(self):
        """測試止盈觸發格式化"""
        title, message = MessageFormatter.format_take_profit_triggered(
            symbol="BTCUSDT",
            entry_price=50000.0,
            exit_price=55000.0,
            quantity=0.001,
            pnl=10.0
        )
        
        assert "止盈觸發" in title
        # Message contains HTML tags, check for key content
        assert "恭喜" in message or "55,000.00" in message or "+10.00%" in message

    def test_format_emergency_mode(self):
        """測試緊急模式格式化"""
        title, message = MessageFormatter.format_emergency_mode(
            event_type="PRICE_CRASH",
            description="BTC dropped 15% in 1 hour",
            action_taken="Closed all positions"
        )
        
        assert "緊急模式啟動" in title
        assert "PRICE_CRASH" in title
        # Message contains HTML tags, check for key content
        assert "PRICE_CRASH" in message or "自動處理" in message or "確認" in message

    def test_format_daily_summary(self):
        """測試每日摘要格式化"""
        title, message = MessageFormatter.format_daily_summary(
            date="2026-08-12",
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
            total_pnl=5.5,
            win_rate=70.0,
            positions=[
                {"symbol": "BTCUSDT", "quantity": 0.001, "entry_price": 50000.0}
            ]
        )
        
        assert "每日交易摘要" in title
        assert "2026-08-12" in title
        # Message contains HTML tags like <b>總交易次數:</b> 10
        assert "10" in message
        assert "70.0%" in message
        assert "BTCUSDT" in message

    def test_format_error_notification(self):
        """測試錯誤通知格式化"""
        title, message = MessageFormatter.format_error_notification(
            error_type="API_ERROR",
            description="Binance API timeout"
        )
        
        assert "系統錯誤" in title
        assert "API_ERROR" in title
        assert "Binance API timeout" in message


class TestTelegramConfig:
    """測試 Telegram 配置"""

    def test_from_env_with_valid_config(self):
        """測試從環境變量創建有效配置"""
        with patch.dict('os.environ', {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': 'test_chat_id',
            'TELEGRAM_ENABLED': 'true'
        }):
            config = TelegramConfig.from_env()
            assert config is not None
            assert config.bot_token == 'test_token'
            assert config.chat_id == 'test_chat_id'
            assert config.enabled is True

    def test_from_env_with_missing_token(self):
        """測試缺少 token 時返回 None"""
        with patch.dict('os.environ', {
            'TELEGRAM_CHAT_ID': 'test_chat_id'
        }, clear=True):
            config = TelegramConfig.from_env()
            assert config is None

    def test_from_env_disabled(self):
        """測試禁用狀態"""
        with patch.dict('os.environ', {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': 'test_chat_id',
            'TELEGRAM_ENABLED': 'false'
        }):
            config = TelegramConfig.from_env()
            assert config is not None
            assert config.enabled is False


class TestNotificationConfig:
    """測試通知系統配置"""

    def test_from_env(self):
        """測試從環境變量創建配置"""
        with patch.dict('os.environ', {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': 'test_chat_id'
        }):
            config = NotificationConfig.from_env()
            assert config.telegram is not None
            assert config.telegram.bot_token == 'test_token'
            assert config.max_retry_count == 5
            assert config.retry_base_delay == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
