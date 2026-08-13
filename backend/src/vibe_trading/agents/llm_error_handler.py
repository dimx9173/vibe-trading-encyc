"""
LLM 錯誤處理與降級策略

處理 LLM API 500 錯誤、結構化輸出解析失敗等問題
"""
import asyncio
import logging
from typing import Optional, Any, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LLMRetryConfig:
    """LLM 重試配置"""
    max_retries: int = 3
    retry_delay: float = 2.0  # 秒
    exponential_base: float = 2.0
    fallback_enabled: bool = True


class LLMErrorHandler:
    """LLM 錯誤處理器"""
    
    def __init__(self, config: Optional[LLMRetryConfig] = None):
        self.config = config or LLMRetryConfig()
        self._error_count = 0
        self._fallback_count = 0
    
    async def execute_with_retry(
        self,
        func,
        *args,
        fallback_func=None,
        **kwargs
    ) -> Any:
        """
        執行 LLM 調用並自動重試
        
        Args:
            func: LLM 調用函數（異步）
            *args, **kwargs: 函數參數
            fallback_func: 降級函數（當重試失敗時使用）
        
        Returns:
            LLM 響應結果
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                # 執行 LLM 調用
                result = await func(*args, **kwargs)
                
                # 成功，重置錯誤計數
                if attempt > 0:
                    logger.info(f"LLM call succeeded after {attempt} retries")
                self._error_count = 0
                
                return result
                
            except Exception as e:
                last_exception = e
                self._error_count += 1
                
                # 檢查是否是 500 錯誤
                if "500" in str(e) or "Internal server error" in str(e):
                    if attempt < self.config.max_retries:
                        # 計算指數退避延遲
                        delay = self.config.retry_delay * (
                            self.config.exponential_base ** attempt
                        )
                        logger.warning(
                            f"LLM 500 error (attempt {attempt + 1}/{self.config.max_retries}). "
                            f"Retrying in {delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(f"LLM 500 error after {self.config.max_retries} retries")
                        break
                else:
                    # 其他錯誤，立即重試
                    if attempt < self.config.max_retries:
                        delay = self.config.retry_delay * (attempt + 1)
                        logger.warning(
                            f"LLM error: {e} (attempt {attempt + 1}/{self.config.max_retries}). "
                            f"Retrying in {delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                    else:
                        break
        
        # 所有重試失敗，使用降級方案
        if fallback_func and self.config.fallback_enabled:
            self._fallback_count += 1
            logger.warning(
                f"Using fallback function (fallback #{self._fallback_count})"
            )
            try:
                return await fallback_func(*args, **kwargs)
            except Exception as fallback_error:
                logger.error(f"Fallback function also failed: {fallback_error}")
        
        # 沒有降級方案或降級也失敗，重新拋出異常
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("LLM call failed with no exception captured")
    
    def get_stats(self) -> Dict[str, int]:
        """獲取錯誤統計"""
        return {
            "total_errors": self._error_count,
            "fallback_count": self._fallback_count
        }
    
    def reset_stats(self):
        """重置統計"""
        self._error_count = 0
        self._fallback_count = 0


class StructuredOutputParser:
    """結構化輸出解析器（帶容錯）"""
    
    @staticmethod
    async def parse_with_fallback(
        response_text: str,
        schema_class,
        fallback_text: str = ""
    ) -> Any:
        """
        解析結構化輸出，失敗時返回降級結果
        
        Args:
            response_text: LLM 響應文本
            schema_class: Pydantic schema 類
            fallback_text: 降級時的默認文本
        
        Returns:
            解析後的對象或降級結果
        """
        try:
            # 嘗試解析 JSON
            import json
            json_data = json.loads(response_text)
            
            # 嘗試使用 Pydantic schema 驗證
            if schema_class:
                return schema_class(**json_data)
            
            return json_data
            
        except Exception as e:
            logger.warning(f"Structured output parsing failed: {e}")
            
            # 返回降級結果
            if fallback_text:
                return {"text": fallback_text, "parsed": False}
            
            return {"text": response_text, "parsed": False}


# 全局實例
_global_llm_error_handler: Optional[LLMErrorHandler] = None


def get_llm_error_handler() -> LLMErrorHandler:
    """獲取全局 LLM 錯誤處理器"""
    global _global_llm_error_handler
    if _global_llm_error_handler is None:
        _global_llm_error_handler = LLMErrorHandler()
    return _global_llm_error_handler
