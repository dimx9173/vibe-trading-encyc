"""
通知隊列模組

支持優先級分級、指數退避重試、內存隊列
"""
import asyncio
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationPriority(Enum):
    """通知優先級"""
    CRITICAL = "critical"  # 立即推送 + 重複提醒直到確認
    HIGH = "high"          # 立即推送，不重複
    LOW = "low"            # 定時批量推送


@dataclass
class Notification:
    """通知消息"""
    id: str
    priority: NotificationPriority
    title: str
    message: str
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 5
    next_retry_time: float = 0.0
    acknowledged: bool = False
    metadata: dict = field(default_factory=dict)

    def should_retry(self) -> bool:
        """是否應該重試"""
        if self.acknowledged:
            return False
        if self.retry_count >= self.max_retries:
            return False
        if self.priority == NotificationPriority.LOW:
            return False  # LOW 級別不重試
        return time.time() >= self.next_retry_time

    def schedule_next_retry(self):
        """安排下次重試時間（指數退避）"""
        if self.priority == NotificationPriority.CRITICAL:
            # CRITICAL: 1min, 2min, 4min, 8min, 16min
            delay = 60 * (2 ** self.retry_count)
        else:
            # HIGH: 5min, 10min, 20min, 40min, 80min
            delay = 300 * (2 ** self.retry_count)

        self.next_retry_time = time.time() + delay
        self.retry_count += 1


class NotificationQueue:
    """通知隊列管理器"""

    def __init__(self):
        self._queue: list[Notification] = []
        self._lock = asyncio.Lock()
        self._subscribers: list[Callable[[Notification], Awaitable[None]]] = []

    async def enqueue(self, notification: Notification):
        """添加通知到隊列"""
        async with self._lock:
            self._queue.append(notification)
            logger.info(f"Notification queued: {notification.id} ({notification.priority.value})")

            # 通知訂閱者
            for subscriber in self._subscribers:
                try:
                    await subscriber(notification)
                except Exception as e:
                    logger.error(f"Error notifying subscriber: {e}")

    async def dequeue(self) -> Optional[Notification]:
        """獲取下一個待發送的通知"""
        async with self._lock:
            for i, notif in enumerate(self._queue):
                if notif.should_retry():
                    return self._queue.pop(i)
            return None

    async def get_pending_notifications(self) -> list[Notification]:
        """獲取所有待發送的通知（用於批量發送 LOW 級別）"""
        async with self._lock:
            return [n for n in self._queue if not n.acknowledged and n.priority == NotificationPriority.LOW]

    async def clear_low_priority(self):
        """清除所有 LOW 級別通知（已批量發送後）"""
        async with self._lock:
            self._queue = [n for n in self._queue if n.priority != NotificationPriority.LOW]

    async def acknowledge(self, notification_id: str) -> bool:
        """確認通知"""
        async with self._lock:
            for notif in self._queue:
                if notif.id == notification_id:
                    notif.acknowledged = True
                    logger.info(f"Notification acknowledged: {notification_id}")
                    return True
            return False

    def subscribe(self, callback: Callable[[Notification], Awaitable[None]]):
        """訂閱通知事件"""
        self._subscribers.append(callback)

    def get_queue_size(self) -> int:
        """獲取隊列大小"""
        return len(self._queue)

    def get_pending_count(self) -> int:
        """獲取待發送通知數量"""
        return sum(1 for n in self._queue if not n.acknowledged)
