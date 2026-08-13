"""
通知系統配置

從環境變量讀取 Telegram 配置
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class TelegramConfig:
    """Telegram 通知配置"""
    bot_token: str
    chat_id: str
    enabled: bool = True

    @classmethod
    def from_env(cls) -> Optional["TelegramConfig"]:
        """從環境變量創建配置"""
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not bot_token or not chat_id:
            return None

        enabled = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"

        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            enabled=enabled
        )


@dataclass
class NotificationConfig:
    """通知系統配置"""
    telegram: Optional[TelegramConfig]
    max_retry_count: int = 5
    retry_base_delay: int = 60  # 秒
    batch_interval: int = 300  # 秒（5分鐘）

    @classmethod
    def from_env(cls) -> "NotificationConfig":
        """從環境變量創建配置"""
        telegram_config = TelegramConfig.from_env()
        return cls(telegram=telegram_config)
