"""
API 數據緩存與降級策略

當 API 失敗時使用緩存數據，避免系統癱瘓
"""
import asyncio
import time
import logging
from typing import Optional, Any, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """緩存條目"""
    data: Any
    timestamp: float
    ttl: float  # Time-to-live in seconds

    def is_expired(self) -> bool:
        """檢查是否過期"""
        return time.time() - self.timestamp > self.ttl


class DataCache:
    """數據緩存管理器"""

    def __init__(self, default_ttl: float = 300.0):  # 5 分鐘默認 TTL
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Any]:
        """
        獲取緩存數據

        Args:
            key: 緩存鍵

        Returns:
            緩存數據，如果不存在或已過期則返回 None
        """
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None

            if entry.is_expired():
                # 過期數據刪除
                del self._cache[key]
                logger.debug(f"Cache expired: {key}")
                return None

            logger.debug(f"Cache hit: {key} (age: {time.time() - entry.timestamp:.1f}s)")
            return entry.data

    async def set(self, key: str, data: Any, ttl: Optional[float] = None):
        """
        設置緩存數據

        Args:
            key: 緩存鍵
            data: 數據
            ttl: 過期時間（秒），None 使用默認值
        """
        async with self._lock:
            self._cache[key] = CacheEntry(
                data=data,
                timestamp=time.time(),
                ttl=ttl if ttl is not None else self.default_ttl
            )
            logger.debug(f"Cache set: {key} (ttl: {ttl or self.default_ttl}s)")

    async def delete(self, key: str):
        """刪除緩存"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]

    async def clear(self):
        """清空所有緩存"""
        async with self._lock:
            self._cache.clear()

    def get_stats(self) -> Dict[str, int]:
        """獲取緩存統計"""
        now = time.time()
        total = len(self._cache)
        expired = sum(1 for e in self._cache.values() if now - e.timestamp > e.ttl)
        active = total - expired

        return {
            "total": total,
            "active": active,
            "expired": expired
        }


class CachedAPIClient:
    """
    帶緩存的 API 客戶端包裝器

    當 API 失敗時自動降級使用緩存數據
    """

    def __init__(self, cache: Optional[DataCache] = None, cache_ttl: float = 300.0):
        self.cache = cache or DataCache(default_ttl=cache_ttl)
        self._fallback_count = 0

    async def fetch_with_fallback(
        self,
        api_func,
        cache_key: str,
        *args,
        use_cache_on_error: bool = True,
        update_cache: bool = True,
        **kwargs
    ) -> Any:
        """
        獲取數據，失敗時使用緩存降級

        Args:
            api_func: API 調用函數（異步）
            cache_key: 緩存鍵
            *args, **kwargs: API 函數參數
            use_cache_on_error: 錯誤時是否使用緩存
            update_cache: 成功時是否更新緩存

        Returns:
            API 數據或緩存數據
        """
        # 嘗試從緩存獲取
        cached_data = await self.cache.get(cache_key)

        try:
            # 調用 API
            data = await api_func(*args, **kwargs)

            # 更新緩存
            if update_cache:
                await self.cache.set(cache_key, data)

            return data

        except Exception as e:
            logger.warning(f"API call failed: {cache_key} - {e}")

            if use_cache_on_error and cached_data is not None:
                self._fallback_count += 1
                logger.info(
                    f"Using cached data for {cache_key} "
                    f"(fallback #{self._fallback_count})"
                )
                return cached_data

            # 沒有緩存或禁用降級，重新拋出異常
            raise

    def get_fallback_count(self) -> int:
        """獲取降級次數"""
        return self._fallback_count

    def reset_fallback_count(self):
        """重置降級計數"""
        self._fallback_count = 0


# 全局實例
_global_cache: Optional[DataCache] = None
_global_cached_client: Optional[CachedAPIClient] = None


def get_data_cache() -> DataCache:
    """獲取全局數據緩存"""
    global _global_cache
    if _global_cache is None:
        _global_cache = DataCache()
    return _global_cache


def get_cached_client() -> CachedAPIClient:
    """獲取全局緩存客戶端"""
    global _global_cached_client
    if _global_cached_client is None:
        _global_cached_client = CachedAPIClient()
    return _global_cached_client
