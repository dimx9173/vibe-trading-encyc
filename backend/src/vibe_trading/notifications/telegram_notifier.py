"""
Telegram Notifier 核心

使用 python-telegram-bot 實現異步通知推送
"""
import asyncio
import logging
import uuid
from typing import Optional
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter

from .queue import NotificationQueue, Notification, NotificationPriority

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram 通知推送器"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.queue = NotificationQueue()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 訂閱通知隊列
        self.queue.subscribe(self._on_notification)

    async def start(self):
        """啟動通知推送循環"""
        self._running = True
        self._task = asyncio.create_task(self._notification_loop())
        logger.info("Telegram Notifier started")

    async def stop(self):
        """停止通知推送"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Telegram Notifier stopped")

    async def _notification_loop(self):
        """通知推送主循環"""
        while self._running:
            try:
                # 處理 CRITICAL 和 HIGH 級別通知
                notification = await self.queue.dequeue()
                if notification:
                    await self._send_notification(notification)

                # 每 5 分鐘批量發送 LOW 級別通知
                low_priority = await self.queue.get_pending_notifications()
                if low_priority:
                    await self._send_batch_notifications(low_priority)
                    await self.queue.clear_low_priority()

            except Exception as e:
                logger.error(f"Error in notification loop: {e}", exc_info=True)

            await asyncio.sleep(1)  # 每秒檢查一次

    async def _on_notification(self, notification: Notification):
        """通知隊列回調"""
        if notification.priority in [NotificationPriority.CRITICAL, NotificationPriority.HIGH]:
            # 立即處理
            pass  # 會在主循環中處理

    async def _send_notification(self, notification: Notification):
        """發送單條通知"""
        try:
            # 構建消息文本
            text = self._format_notification(notification)

            # 構建 inline keyboard（僅 CRITICAL 級別）
            reply_markup = None
            if notification.priority == NotificationPriority.CRITICAL:
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 已確認", callback_data=f"ack_{notification.id}"),
                        InlineKeyboardButton("📋 查看詳情", callback_data=f"detail_{notification.id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

            # 發送消息
            message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_notification=(notification.priority == NotificationPriority.LOW)
            )

            logger.info(f"Notification sent: {notification.id}")

            # 如果是 CRITICAL 且未確認，安排重試
            if notification.priority == NotificationPriority.CRITICAL and not notification.acknowledged:
                notification.schedule_next_retry()
                await self.queue.enqueue(notification)

        except RetryAfter as e:
            logger.warning(f"Rate limited, retry after {e.retry_after}s")
            notification.schedule_next_retry()
            await self.queue.enqueue(notification)

        except TelegramError as e:
            logger.error(f"Telegram error: {e}")
            if notification.retry_count < notification.max_retries:
                notification.schedule_next_retry()
                await self.queue.enqueue(notification)

    async def _send_batch_notifications(self, notifications: list[Notification]):
        """批量發送 LOW 級別通知"""
        if not notifications:
            return

        # 構建批量消息
        text = "📊 <b>通知摘要</b>\n\n"
        for notif in notifications:
            text += f"• <b>{notif.title}</b>\n{notif.message}\n\n"

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML"
            )
            logger.info(f"Batch notification sent: {len(notifications)} items")
        except TelegramError as e:
            logger.error(f"Failed to send batch notification: {e}")

    def _format_notification(self, notification: Notification) -> str:
        """格式化通知消息"""
        priority_emoji = {
            NotificationPriority.CRITICAL: "🚨",
            NotificationPriority.HIGH: "⚠️",
            NotificationPriority.LOW: ""
        }

        emoji = priority_emoji.get(notification.priority, "📌")
        timestamp = datetime.fromtimestamp(notification.timestamp).strftime("%H:%M:%S")

        text = f"{emoji} <b>{notification.title}</b>\n\n"
        text += f"{notification.message}\n\n"
        text += f"<i>時間: {timestamp}</i>"

        if notification.retry_count > 0:
            text += f"\n<i>重試次數: {notification.retry_count}/{notification.max_retries}</i>"

        return text

    async def send_test_message(self) -> bool:
        """發送測試消息"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="✅ VBT Telegram 通知測試成功！"
            )
            return True
        except TelegramError as e:
            logger.error(f"Test message failed: {e}")
            return False

    async def handle_callback(self, callback_query) -> bool:
        """處理 inline keyboard 回調"""
        data = callback_query.data
        if data.startswith("ack_"):
            notification_id = data[4:]
            success = await self.queue.acknowledge(notification_id)
            if success:
                await callback_query.answer("✅ 已確認")
                await callback_query.edit_message_text("✅ 通知已確認")
            return success
        elif data.startswith("detail_"):
            notification_id = data[7:]
            # TODO: 發送詳細信息
            await callback_query.answer("查看詳情")
            return True
        return False
