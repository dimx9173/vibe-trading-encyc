"""
API Rate Limiter

防止 Binance API 封禁的限流器
"""
import asyncio
import time
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """限流配置"""
    max_requests: int = 60          # 每分鐘最大請求數
    window_seconds: int = 60        # 時間窗口（秒）
    retry_delay: float = 1.0        # 初始重試延遲（秒）
    max_retry_delay: float = 60.0   # 最大重試延遲（秒）
    exponential_base: float = 2.0   # 指數退避基數


class RateLimiter:
    """API 限流器"""

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._requests: list[float] = []  # 請求時間戳列表
        self._lock = asyncio.Lock()
        self._retry_count = 0

    async def acquire(self) -> bool:
        """
        獲取請求許可

        Returns:
            True 如果允許請求，False 如果超過限制
        """
        async with self._lock:
            now = time.time()

            # 清除過期的請求記錄
            cutoff = now - self.config.window_seconds
            self._requests = [t for t in self._requests if t > cutoff]

            # 檢查是否超過限制
            if len(self._requests) >= self.config.max_requests:
                # 計算需要等待的時間
                oldest_request = min(self._requests)
                wait_time = oldest_request + self.config.window_seconds - now

                if wait_time > 0:
                    logger.warning(
                        f"Rate limit reached. Waiting {wait_time:.2f}s "
                        f"({len(self._requests)}/{self.config.max_requests} requests)"
                    )
                    await asyncio.sleep(wait_time)

            # 記錄請求
            self._requests.append(now)
            self._retry_count = 0
            return True

    def get_remaining_requests(self) -> int:
        """獲取剩餘請求數"""
        now = time.time()
        cutoff = now - self.config.window_seconds
        active_requests = [t for t in self._requests if t > cutoff]
        return max(0, self.config.max_requests - len(active_requests))

    def get_reset_time(self) -> float:
        """獲取限流重置時間（秒）"""
        if not self._requests:
            return 0.0

        now = time.time()
        oldest_request = min(self._requests)
        reset_time = oldest_request + self.config.window_seconds - now
        return max(0.0, reset_time)

    def calculate_retry_delay(self) -> float:
        """計算指數退避重試延遲"""
        delay = self.config.retry_delay * (
            self.config.exponential_base ** self._retry_count
        )
        self._retry_count += 1
        return min(delay, self.config.max_retry_delay)

    def reset(self):
        """重置限流器"""
        self._requests.clear()
        self._retry_count = 0


class APIRetryHandler:
    """API 重試處理器"""

    def __init__(self, max_retries: int = 3, rate_limiter: Optional[RateLimiter] = None):
        self.max_retries = max_retries
        self.rate_limiter = rate_limiter or RateLimiter()

    async def execute_with_retry(self, func, *args, **kwargs):
        """
        執行函數並自動重試

        Args:
            func: 異步函數
            *args, **kwargs: 函數參數

        Returns:
            函數執行結果

        Raises:
            Exception: 超過最大重試次數後拋出異常
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                # 等待限流器許可
                await self.rate_limiter.acquire()

                # 執行函數
                result = await func(*args, **kwargs)
                return result

            except Exception as e:
                last_exception = e

                # 檢查是否是 rate limit 錯誤
                if "1003" in str(e) or "Way too many requests" in str(e):
                    # Binance rate limit ban
                    delay = self.rate_limiter.calculate_retry_delay()
                    logger.error(
                        f"API rate limit ban detected. "
                        f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue

                # 其他錯誤，立即重試
                if attempt < self.max_retries:
                    delay = self.rate_limiter.calculate_retry_delay()
                    logger.warning(
                        f"API error: {e}. "
                        f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        raise last_exception


# 全局實例
_global_rate_limiter: Optional[RateLimiter] = None
_global_retry_handler: Optional[APIRetryHandler] = None


def get_rate_limiter() -> RateLimiter:
    """獲取全局限流器"""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter()
    return _global_rate_limiter


def get_retry_handler() -> APIRetryHandler:
    """獲取全局重試處理器"""
    global _global_retry_handler
    if _global_retry_handler is None:
        _global_retry_handler = APIRetryHandler()
    return _global_retry_handler


# =============================================================================
# 兼容性接口（供 market_data_tools.py 使用）
# =============================================================================

class MultiEndpointRateLimiter:
    """多端點限流器（兼容舊接口）"""
    
    def __init__(self):
        self._limiters = {}
    
    async def acquire(self, endpoint: str, tokens: int = 1):
        """獲取請求許可"""
        if endpoint not in self._limiters:
            self._limiters[endpoint] = RateLimiter()
        return await self._limiters[endpoint].acquire()
    
    def get_limiter(self, endpoint: str) -> RateLimiter:
        """獲取指定端點的限流器"""
        if endpoint not in self._limiters:
            self._limiters[endpoint] = RateLimiter()
        return self._limiters[endpoint]


_multi_endpoint_limiter: Optional[MultiEndpointRateLimiter] = None


def get_multi_endpoint_limiter() -> MultiEndpointRateLimiter:
    """獲取全局多端點限流器"""
    global _multi_endpoint_limiter
    if _multi_endpoint_limiter is None:
        _multi_endpoint_limiter = MultiEndpointRateLimiter()
    return _multi_endpoint_limiter
