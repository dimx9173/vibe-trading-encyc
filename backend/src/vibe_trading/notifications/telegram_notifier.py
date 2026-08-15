"""
Telegram Notifier 核心

使用 python-telegram-bot 實現異步通知推送
"""
import asyncio
import logging
import uuid
from typing import Any, List, Optional, Set
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter

from .queue import NotificationQueue, Notification, NotificationPriority
from .commands import format_balance, format_positions, format_status, format_help

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram 通知推送器"""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        executor: Any = None,
        system: Any = None,
        allowed_chat_ids: Optional[List[str]] = None,
    ):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.executor = executor
        self.system = system
        self.allowed_chat_ids: Set[str] = set(allowed_chat_ids or [chat_id])
        self.queue = NotificationQueue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._updates_task: Optional[asyncio.Task] = None
        self._update_offset: Optional[int] = None

        # 訂閱通知隊列
        self.queue.subscribe(self._on_notification)

    async def start(self):
        """啟動通知推送循環 + update 接收循環"""
        self._running = True
        self._task = asyncio.create_task(self._notification_loop())
        self._updates_task = asyncio.create_task(self._updates_loop())
        # 設定指令選單 (輸入 / 時彈出); 失敗不阻擋啟動
        try:
            from .commands import build_command_menu
            await self.bot.set_my_commands(build_command_menu())
            logger.info("Telegram command menu set")
        except Exception as e:
            logger.warning(f"Failed to set command menu: {e}")
        logger.info("Telegram Notifier started")

    async def stop(self):
        """停止通知推送 + update 接收"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._updates_task:
            self._updates_task.cancel()
            try:
                await self._updates_task
            except asyncio.CancelledError:
                pass
        # Flush notifications still queued (e.g. shutdown notice enqueued just
        # before stop). LOW items are batched; CRITICAL/HIGH go through dequeue.
        low_priority = await self.queue.get_pending_notifications()
        if low_priority:
            await self._send_batch_notifications(low_priority)
            await self.queue.clear_low_priority()
        while True:
            notification = await self.queue.dequeue()
            if notification is None:
                break
            await self._send_notification(notification)
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

    # ============================================================================
    # 入站 update 接收 (grill Q2: Bot.get_updates 長輪詢, 唯一 consumer)
    # ============================================================================

    async def _updates_loop(self):
        """Long-poll Telegram updates; route commands/callbacks. One consumer per token."""
        while self._running:
            try:
                updates = await self.bot.get_updates(offset=self._update_offset, timeout=20)
                for update in updates:
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except (TelegramError, RetryAfter) as e:
                logger.warning(f"get_updates error: {e}")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"update loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _handle_update(self, update) -> None:
        """Route a single update: callback_query or command message."""
        # Advance offset first: even on handler failure, don't re-process
        self._update_offset = update.update_id + 1
        try:
            if update.callback_query:
                await self._handle_callback_query(update.callback_query)
            elif update.message and getattr(update.message, "text", None):
                text = update.message.text.strip()
                if text.startswith("/"):
                    await self._handle_command(update.message, text)
                # 非指令文字 → 忽略
        except Exception as e:
            logger.error(f"update handling failed: {e}", exc_info=True)

    def _is_allowed(self, chat_id) -> bool:
        """Authorization gate (grill Q3): only owner chat executes commands."""
        return str(chat_id) in self.allowed_chat_ids

    def _refresh_kb(self, query: str) -> InlineKeyboardMarkup:
        """Refresh inline button for a command reply (grill Q4/Q8)."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 刷新", callback_data=f"refresh:{query}")]
        ])

    async def _run_query(self, query: str) -> str:
        """Execute a query handler; on error return an error message (grill Q7)."""
        try:
            if query == "balance":
                return await format_balance(self.executor)
            if query == "positions":
                return await format_positions(self.executor)
            if query == "status":
                return await format_status(self.system)
            if query == "help":
                return format_help()
            return "未知指令。使用 /help 查看可用指令"
        except Exception as e:
            logger.warning(f"Query {query} failed: {e}")
            return f"⚠️ 查詢失敗: {e}"

    async def _handle_command(self, message, text: str) -> None:
        """Answer a /command from an authorized chat."""
        if not self._is_allowed(message.chat.id):
            logger.warning(f"Ignored command from unauthorized chat {message.chat.id}")
            return
        query = text.lstrip("/").split()[0].lower()
        reply = await self._run_query(query)
        await message.reply_text(
            reply,
            parse_mode="HTML",
            reply_markup=self._refresh_kb(query),
        )

    async def _handle_callback_query(self, callback_query) -> None:
        """Route callback_query: refresh:<query> re-runs; else legacy ack_/detail_."""
        data = callback_query.data or ""
        if data.startswith("refresh:"):
            query = data[len("refresh:"):]
            reply = await self._run_query(query)
            try:
                await callback_query.edit_message_text(
                    reply, parse_mode="HTML", reply_markup=self._refresh_kb(query)
                )
            except Exception as e:
                logger.warning(f"refresh edit failed: {e}")
            return
        # 既有 ack_/detail_ 處理
        await self.handle_callback(callback_query)

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

    async def send_startup_notification(self, symbol: str, interval: str, mode: str) -> None:
        """發送啟動通知"""
        notification = Notification(
            id=f"startup_{uuid.uuid4().hex[:8]}",
            priority=NotificationPriority.LOW,
            title="VBT 啟動完成",
            message=f"交易對: {symbol}\n間隔: {interval}\n模式: {mode}",
            metadata={"type": "startup", "symbol": symbol}
        )
        await self.queue.enqueue(notification)

    async def send_shutdown_notification(self, reason: str = "正常關閉") -> None:
        """發送關閉通知"""
        notification = Notification(
            id=f"shutdown_{uuid.uuid4().hex[:8]}",
            priority=NotificationPriority.LOW,
            title="VBT 已關閉",
            message=f"原因: {reason}",
            metadata={"type": "shutdown"}
        )
        await self.queue.enqueue(notification)

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

    async def send_notification(self, notification: Notification) -> None:
        """發送單條通知

        Args:
            notification: 要發送的通知對象
        """
        await self.queue.enqueue(notification)
