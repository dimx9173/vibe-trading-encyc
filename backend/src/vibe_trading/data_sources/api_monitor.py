"""
API 監控與告警

監控 API 調用次數、Rate Limit 狀態，並通過 Telegram 發送告警
"""
import asyncio
import logging
import time
from typing import Optional, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class APIStats:
    """API 調用統計"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rate_limit_hits: int = 0
    last_call_time: float = 0.0
    calls_per_minute: float = 0.0
    
    # 滑動窗口計數
    _recent_calls: list = field(default_factory=list)
    _window_seconds: float = 60.0
    
    def record_call(self, success: bool = True, rate_limited: bool = False):
        """記錄 API 調用"""
        now = time.time()
        self.total_calls += 1
        self.last_call_time = now
        
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
        
        if rate_limited:
            self.rate_limit_hits += 1
        
        # 更新滑動窗口
        self._recent_calls.append(now)
        cutoff = now - self._window_seconds
        self._recent_calls = [t for t in self._recent_calls if t > cutoff]
        self.calls_per_minute = len(self._recent_calls)
    
    def get_success_rate(self) -> float:
        """獲取成功率"""
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100
    
    def get_failure_rate(self) -> float:
        """獲取失敗率"""
        if self.total_calls == 0:
            return 0.0
        return (self.failed_calls / self.total_calls) * 100
    
    def reset(self):
        """重置統計"""
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.rate_limit_hits = 0
        self._recent_calls.clear()
        self.calls_per_minute = 0.0


class APIMonitor:
    """API 監控器"""
    
    def __init__(self):
        self._stats: Dict[str, APIStats] = {}
        self._lock = asyncio.Lock()
        self._alert_threshold = 0.8  # 失敗率超過 80% 告警
        self._rate_limit_threshold = 3  # Rate limit 命中 3 次告警
        self._telegram_notifier = None
    
    async def record_api_call(
        self,
        api_name: str,
        success: bool = True,
        rate_limited: bool = False
    ):
        """
        記錄 API 調用
        
        Args:
            api_name: API 名稱（如 "binance_rest", "cryptocompare_news"）
            success: 是否成功
            rate_limited: 是否被限流
        """
        async with self._lock:
            if api_name not in self._stats:
                self._stats[api_name] = APIStats()
            
            self._stats[api_name].record_call(success, rate_limited)
            
            # 檢查是否需要告警
            await self._check_alerts(api_name)
    
    async def _check_alerts(self, api_name: str):
        """檢查是否需要發送告警"""
        stats = self._stats[api_name]
        
        # 失敗率告警
        if stats.get_failure_rate() > self._alert_threshold * 100:
            await self._send_alert(
                api_name,
                f"API 失敗率過高: {stats.get_failure_rate():.1f}%",
                "HIGH"
            )
        
        # Rate limit 告警
        if stats.rate_limit_hits >= self._rate_limit_threshold:
            await self._send_alert(
                api_name,
                f"Rate limit 命中 {stats.rate_limit_hits} 次",
                "CRITICAL"
            )
    
    async def _send_alert(self, api_name: str, message: str, severity: str):
        """發送告警通知"""
        logger.warning(f"API Alert [{severity}] {api_name}: {message}")
        
        # 通過 Telegram 發送（如果已配置）
        if self._telegram_notifier:
            try:
                from vibe_trading.notifications import Notification, NotificationPriority
                
                priority = NotificationPriority.CRITICAL if severity == "CRITICAL" else NotificationPriority.HIGH
                
                notification = Notification(
                    id=f"api_alert_{api_name}_{int(time.time())}",
                    priority=priority,
                    title=f"API 告警: {api_name}",
                    message=message
                )
                await self._telegram_notifier.queue.enqueue(notification)
            except Exception as e:
                logger.error(f"Failed to send Telegram alert: {e}")
    
    def get_stats(self, api_name: Optional[str] = None) -> Dict:
        """獲取 API 統計"""
        if api_name:
            stats = self._stats.get(api_name)
            if stats:
                return {
                    "total_calls": stats.total_calls,
                    "success_rate": f"{stats.get_success_rate():.1f}%",
                    "failure_rate": f"{stats.get_failure_rate():.1f}%",
                    "rate_limit_hits": stats.rate_limit_hits,
                    "calls_per_minute": stats.calls_per_minute
                }
            return {}
        
        # 返回所有 API 統計
        return {
            name: {
                "total_calls": s.total_calls,
                "success_rate": f"{s.get_success_rate():.1f}%",
                "failure_rate": f"{s.get_failure_rate():.1f}%",
                "rate_limit_hits": s.rate_limit_hits,
                "calls_per_minute": s.calls_per_minute
            }
            for name, s in self._stats.items()
        }
    
    def set_telegram_notifier(self, notifier):
        """設置 Telegram 通知器"""
        self._telegram_notifier = notifier
    
    def set_alert_threshold(self, threshold: float):
        """設置告警閾值（0.0-1.0）"""
        self._alert_threshold = threshold
    
    def set_rate_limit_threshold(self, threshold: int):
        """設置 Rate limit 告警閾值"""
        self._rate_limit_threshold = threshold


# 全局實例
_global_api_monitor: Optional[APIMonitor] = None


def get_api_monitor() -> APIMonitor:
    """獲取全局 API 監控器"""
    global _global_api_monitor
    if _global_api_monitor is None:
        _global_api_monitor = APIMonitor()
    return _global_api_monitor
