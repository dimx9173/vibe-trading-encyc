"""
消息格式化器

將各種事件格式化為 Telegram 通知消息
"""
from typing import Optional
from datetime import datetime


class MessageFormatter:
    """消息格式化器"""

    @staticmethod
    def format_trade_decision(
        symbol: str,
        action: str,
        price: float,
        quantity: float,
        reason: str,
        pnl: Optional[float] = None
    ) -> tuple[str, str]:
        """格式化交易決策通知"""
        action_emoji = {
            "BUY": "🟢",
            "SELL": "🔴",
            "HOLD": "⚪"
        }
        emoji = action_emoji.get(action, "📌")

        title = f"{emoji} 交易決策: {action} {symbol}"

        message = f"<b>操作:</b> {action}\n"
        message += f"<b>價格:</b> {price:,.2f}\n"
        message += f"<b>數量:</b> {quantity:.6f}\n"
        message += f"<b>原因:</b> {reason}\n"

        if pnl is not None:
            pnl_emoji = "📈" if pnl > 0 else "📉"
            message += f"<b>預期 PnL:</b> {pnl_emoji} {pnl:+.2f}%\n"

        return title, message

    @staticmethod
    def format_stop_loss_triggered(
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        pnl: float
    ) -> tuple[str, str]:
        """格式化止損觸發通知"""
        title = f"🚨 止損觸發: {symbol}"

        pnl_emoji = "📉" if pnl < 0 else "📈"
        message = f"<b>入場價:</b> {entry_price:,.2f}\n"
        message += f"<b>出場價:</b> {exit_price:,.2f}\n"
        message += f"<b>數量:</b> {quantity:.6f}\n"
        message += f"<b>PnL:</b> {pnl_emoji} {pnl:+.2f}%\n\n"
        message += "⚠️ <i>請確認是否調整策略</i>"

        return title, message

    @staticmethod
    def format_take_profit_triggered(
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        pnl: float
    ) -> tuple[str, str]:
        """格式化止盈觸發通知"""
        title = f"💰 止盈觸發: {symbol}"

        message = f"<b>入場價:</b> {entry_price:,.2f}\n"
        message += f"<b>出場價:</b> {exit_price:,.2f}\n"
        message += f"<b>數量:</b> {quantity:.6f}\n"
        message += f"<b>PnL:</b> 📈 {pnl:+.2f}%\n\n"
        message = "✅ <i>恭喜！利潤已鎖定</i>"

        return title, message

    @staticmethod
    def format_emergency_mode(
        event_type: str,
        description: str,
        action_taken: str
    ) -> tuple[str, str]:
        """格式化緊急模式通知"""
        title = f"🚨 緊急模式啟動: {event_type}"

        message = f"<b>事件:</b> {description}\n"
        message += f"<b>行動:</b> {action_taken}\n\n"
        message = "⚠️ <i>系統已自動處理，請盡快確認</i>"

        return title, message

    @staticmethod
    def format_daily_summary(
        date: str,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        total_pnl: float,
        win_rate: float,
        positions: list[dict]
    ) -> tuple[str, str]:
        """格式化每日摘要"""
        title = f" 每日交易摘要 ({date})"

        message = f"<b>總交易次數:</b> {total_trades}\n"
        message += f"<b>盈利:</b> {winning_trades} | <b>虧損:</b> {losing_trades}\n"
        message += f"<b>勝率:</b> {win_rate:.1f}%\n"
        message += f"<b>總 PnL:</b> {total_pnl:+.2f}%\n\n"

        if positions:
            message += "<b>當前持倉:</b>\n"
            for pos in positions:
                message += f"• {pos['symbol']}: {pos['quantity']:.6f} @ {pos['entry_price']:,.2f}\n"
        else:
            message += "<i>無持倉</i>\n"

        return title, message

    @staticmethod
    def format_error_notification(
        error_type: str,
        description: str,
        timestamp: Optional[str] = None
    ) -> tuple[str, str]:
        """格式化錯誤通知"""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        title = f"❌ 系統錯誤: {error_type}"

        message = f"<b>時間:</b> {timestamp}\n"
        message += f"<b>錯誤:</b> {description}\n\n"
        message += "⚠️ <i>請檢查系統日誌</i>"

        return title, message

    @staticmethod
    def format_system_status(
        status: str,
        uptime: str,
        active_threads: int,
        pending_events: int
    ) -> tuple[str, str]:
        """格式化系統狀態通知"""
        status_emoji = {
            "RUNNING": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌"
        }
        emoji = status_emoji.get(status, "")

        title = f"{emoji} 系統狀態: {status}"

        message = f"<b>運行時間:</b> {uptime}\n"
        message += f"<b>活躍線程:</b> {active_threads}\n"
        message += f"<b>待處理事件:</b> {pending_events}\n"

        return title, message
