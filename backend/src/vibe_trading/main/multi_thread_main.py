"""
Multi-threaded Trading System Main Entry Point

Launches and manages all threads:
1. Macro Analysis Thread (2hr polling, 24hr 30m K線投喂)
2. On Bar Thread (30m K-line triggered)
3. Event Driven Thread (Trigger monitoring)
"""
import asyncio
import logging
import signal
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional

from pi_logger import get_logger, info, success, warning, separator

from vibe_trading.coordinator.thread_manager import get_thread_manager
from vibe_trading.coordinator.shared_state import get_shared_state_manager
from vibe_trading.coordinator.event_queue import get_event_queue
from vibe_trading.coordinator.emergency_handler import EmergencyHandler
from vibe_trading.config.settings import get_settings
from vibe_trading.data_sources.kline_storage import KlineStorage
from vibe_trading.data_sources.macro_storage import get_macro_storage
from vibe_trading.rule_engine.config import RuleEngineConfig
from vibe_trading.rule_engine.loop import RuleEngineLoop
from vibe_trading.threads.macro_thread import MacroAnalysisThread
from vibe_trading.threads.onbar_thread import OnBarThread
from vibe_trading.triggers.trigger_registry import get_trigger_registry
from vibe_trading.triggers.price_triggers import (
    PriceDropTrigger,
    PriceSpikeTrigger,
)
from vibe_trading.triggers.risk_triggers import (
    MarginRatioTrigger,
    DrawdownTrigger,
)
from vibe_trading.triggers.base_trigger import TriggerContext
from vibe_trading.tools import market_data_tools
from vibe_trading.data_sources.ws_price_cache import get_price_cache
from vibe_trading.execution.order_executor import OrderExecutor

if TYPE_CHECKING:
    from vibe_trading.notifications.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)
log = get_logger("MultiThreadMain")


class MultiThreadedTradingSystem:
    """
    Multi-threaded trading system
    
    Manages all threads and their lifecycle.
    """
    
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        interval: str = "30m",
        executor: Optional[OrderExecutor] = None,
        mode: str = "paper",
        symbol: Optional[str] = None,
    ):
        """
        Initialize multi-threaded trading system

        Args:
            symbols: 交易对列表 (Phase 1: 每 symbol 一个 OnBarThread + RuleEngineLoop)
            interval: Time interval for On Bar thread
            symbol: legacy 单标的参数 (backward-compat)
        """
        if symbols is None:
            symbols = [symbol] if symbol else list(get_settings().symbols)
        self.symbols: List[str] = list(symbols)
        self.symbol = self.symbols[0]
        self.interval = interval
        self.executor = executor
        self.mode = mode
        
        # Core components
        self.thread_manager = get_thread_manager()
        self.shared_state = get_shared_state_manager()
        self.event_queue = get_event_queue()
        self.trigger_registry = get_trigger_registry()
        
        # Threads
        self.macro_thread: Optional[MacroAnalysisThread] = None
        self.onbar_thread: Optional[OnBarThread] = None
        self.onbar_threads: List[OnBarThread] = []
        self.event_thread: Optional[asyncio.Task] = None
        
        # Emergency handler
        self.emergency_handler: Optional[EmergencyHandler] = None
        
        # Telegram notifier
        self.notifier: Optional["TelegramNotifier"] = None
        
        # State
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._last_price: Optional[float] = None
        self._last_price_update: Optional[float] = None  # timestamp
        self._price_cache = get_price_cache()
        log.info(f"MultiThreadedTradingSystem initialized for {symbol}")
    
    async def initialize(self) -> None:
        """Initialize all components"""
        info("Initializing multi-threaded trading system...", tag="INIT")
        
        # Initialize shared state cleanup task
        await self.shared_state.start_cleanup_task(interval_seconds=60)
        
        rule_config = RuleEngineConfig.from_env()
        rule_config.interval = self.interval
        storage = KlineStorage()
        macro_storage = get_macro_storage()
        self.macro_thread = MacroAnalysisThread(
            symbol=self.symbol,
            interval_seconds=rule_config.macro_interval_seconds,
            kline_storage=storage,
            kline_lookback_hours=rule_config.macro_lookback_hours,
            kline_interval=self.interval,
        )
        await self.macro_thread.initialize()
        for sym in self.symbols:
            loop = RuleEngineLoop(
                symbol=sym,
                interval=self.interval,
                storage=storage,
                executor=self.executor,
                macro_storage=macro_storage,
                config=rule_config,
            )
            onbar = OnBarThread(
                symbol=sym,
                interval=self.interval,
                thread_manager=self.thread_manager,
                executor=self.executor,
                rule_engine_loop=loop,
            )
            await onbar.initialize()
            self.onbar_threads.append(onbar)
        if self.onbar_threads:
            self.onbar_thread = self.onbar_threads[0]
        
        # Initialize Telegram notifier
        from vibe_trading.notifications.config import TelegramConfig
        from vibe_trading.notifications.telegram_notifier import TelegramNotifier
        
        telegram_config = TelegramConfig.from_env()
        if telegram_config and telegram_config.enabled:
            try:
                self.notifier = TelegramNotifier(
                    bot_token=telegram_config.bot_token,
                    chat_id=telegram_config.chat_id,
                    executor=self.executor,
                    system=self,
                )
                log.info("Telegram notifier initialized", tag="NOTIFIER")
            except Exception as e:
                logger.warning(f"Failed to initialize Telegram notifier: {e}")
                self.notifier = None

        # Initialize emergency handler
        self.emergency_handler = EmergencyHandler(
            thread_manager=self.thread_manager,
            shared_state=self.shared_state,
            event_queue=self.event_queue,
            notifier=self.notifier,
        )
        await self.emergency_handler.initialize(symbol=self.symbol)
        
        # Register default triggers
        await self._register_default_triggers()
        
        success("System initialization complete")
    
    async def _register_default_triggers(self) -> None:
        """Register default triggers (price triggers per symbol, risk triggers once)."""
        info("Registering default triggers...", tag="TRIGGERS")

        for sym in self.symbols:
            self.trigger_registry.register(PriceDropTrigger(
                threshold_pct=0.03,
                symbol=sym,
            ))
            self.trigger_registry.register(PriceSpikeTrigger(
                threshold_pct=0.03,
                symbol=sym,
            ))

        # Risk triggers
        margin_trigger = MarginRatioTrigger(threshold_ratio=0.5)
        self.trigger_registry.register(margin_trigger)

        drawdown_trigger = DrawdownTrigger(threshold_drawdown=0.2)
        self.trigger_registry.register(drawdown_trigger)

        log.info(f"Registered {len(self.trigger_registry.get_all())} triggers")
    
    async def start(self) -> None:
        """Start all threads"""
        if self._running:
            warning("System already running")
            return
        
        self._running = True
        info("Starting multi-threaded trading system...", tag="START")
        
        # Register threads with thread manager
        await self.thread_manager.register_thread(
            name="macro_thread",
            coroutine=self.macro_thread.start,
        )

        onbar_threads = list(self.onbar_threads)
        if not onbar_threads and self.onbar_thread is not None:
            onbar_threads = [self.onbar_thread]
        for thread in onbar_threads:
            await self.thread_manager.register_thread(
                name=f"onbar_{thread.symbol}",
                coroutine=thread.start,
            )
        
        # Start macro thread
        await self.thread_manager.start_thread("macro_thread")
        await self.thread_manager.run_thread(
            "macro_thread",
            self.macro_thread.start,
        )
        
        # Start On Bar thread(s)
        for thread in onbar_threads:
            thread_name = f"onbar_{thread.symbol}"
            await self.thread_manager.start_thread(thread_name)
            await self.thread_manager.run_thread(
                thread_name,
                thread.start,
            )
        
        # Start event thread
        self.event_thread = asyncio.create_task(self._run_event_thread())
        
        success("All threads started")
        
        # Start Telegram notifier and send startup notification
        if self.notifier:
            try:
                await self.notifier.start()
                await self.notifier.send_startup_notification(
                    symbol=self.symbol,
                    interval=self.interval,
                    mode=self.mode
                )
                log.info("Telegram notifier started and startup notification sent", tag="NOTIFIER")
            except Exception as e:
                logger.warning(f"Failed to start Telegram notifier: {e}")
        
        # Print system status
        await self._print_system_status()
    
    async def _run_event_thread(self) -> None:
        """Run event thread"""
        log.info("Starting event thread")
        
        while self._running:
            try:
                # Process event queue
                await self.emergency_handler.process_event_queue()
                
                # Check triggers periodically
                await self._check_triggers()
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in event thread: {e}", exc_info=True)
                await asyncio.sleep(10)
    
    async def _check_triggers(self) -> None:
        """Check all triggers"""
        try:
            # 获取当前价格和持仓
            current_price = await self._get_current_price()
            if current_price is None:
                logger.debug("无法获取当前价格，跳过触发器检查")
                return

            previous_price = self._last_price or current_price

            # 获取持仓和账户余额
            positions = await self._get_positions()
            account_balance = await self._get_account_balance()

            # 构建触发器上下文
            context = TriggerContext(
                symbol=self.symbol,
                current_price=current_price,
                previous_price=previous_price,
                timestamp=int(datetime.now().timestamp() * 1000),
                positions=positions,
                account_balance=account_balance,
            )

            # 添加额外的上下文数据
            context.set("last_price_update", self._last_price_update)
            context.set("open", self._last_price)  # 简化，实际应该获取开盘价
            context.set("high", current_price * 1.01)  # 简化
            context.set("low", current_price * 0.99)  # 简化

            # 更新价格记录
            self._last_price = current_price
            self._last_price_update = datetime.now().timestamp()

            # 评估触发器
            events = await self.trigger_registry.evaluate_all(context)

            # 处理触发的事件
            for event in events:
                await self._handle_trigger_event(event)

        except Exception as e:
            logger.error(f"检查触发器时出错: {e}", exc_info=True)

    async def _get_current_price(self) -> Optional[float]:
        """
        获取当前价格（优先使用 WebSocket 缓存）

        Returns:
            当前价格或None
        """
        try:
            # 优先使用 WebSocket 缓存
            price = await self._price_cache.get_price_with_fallback(
                self.symbol,
                fallback_func=lambda: self._get_price_from_rest()
            )
            return price
        except Exception as e:
            logger.warning(f"获取当前价格失败: {e}")
        return None
    
    async def _get_price_from_rest(self) -> Optional[float]:
        """从 REST API 获取价格（降級方案）"""
        try:
            result = await market_data_tools.get_current_price(self.symbol)
            if result and "price" in result:
                return float(result["price"])
        except Exception as e:
            logger.warning(f"REST API 获取价格失败: {e}")
        return None

    async def _get_positions(self) -> List[Dict]:
        """
        获取当前持仓

        Returns:
            持仓列表
        """
        if not self.executor:
            return []
        positions = await self.executor.get_positions()
        return [
            {
                "symbol": pos.symbol,
                "position_amount": pos.position_amount,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price,
                "unrealized_profit": pos.unrealized_profit,
                "liquidation_price": pos.liquidation_price,
                "leverage": pos.leverage,
                "position_side": pos.position_side.value,
                "notional": pos.notional,
            }
            for pos in positions
        ]

    async def _get_account_balance(self) -> float:
        """
        获取账户余额

        Returns:
            账户余额
        """
        if not self.executor:
            return 10000.0
        balances = await self.executor.get_balance()
        usdt = balances.get("USDT", 10000.0)
        if isinstance(usdt, dict):
            return float(usdt.get("available", usdt.get("balance", 10000.0)))
        return float(usdt)

    async def _handle_trigger_event(self, event) -> None:
        """
        处理触发事件

        Args:
            event: 触发事件
        """
        try:
            logger.warning(
                f"触发器激活: {event.trigger_name} "
                f"(严重程度={event.severity.value}, symbol={event.symbol})"
            )

            # 将事件添加到事件队列
            await self.event_queue.put(event)

            # 记录事件到共享状态
            await self.shared_state.set(
                f"last_trigger_{event.trigger_name}",
                event.to_dict(),
                ttl_seconds=3600,  # 保留1小时
                notify=True,
            )

            # 如果是CRITICAL或HIGH级别，发送警告消息
            if event.severity.value in ["critical", "high"]:
                from vibe_trading.agents.messaging import get_message_broker, MessageType

                message_broker = get_message_broker()
                message_broker.send(
                    sender="event_thread",
                    receiver="all",
                    message_type=MessageType.WARNING,
                    content={
                        "type": "trigger_fired",
                        "trigger_name": event.trigger_name,
                        "severity": event.severity.value,
                        "data": event.data,
                    },
                    correlation_id=event.event_id,
                )

        except Exception as e:
            logger.error(f"处理触发事件时出错: {e}", exc_info=True)
    
    async def stop(self) -> None:
        """Stop all threads"""
        if not self._running:
            warning("System not running")
            return
        
        info("Stopping multi-threaded trading system...", tag="STOP")
        
        self._running = False
        self._shutdown_event.set()
        
        # Stop Telegram notifier first (before threads)
        if self.notifier:
            try:
                await self.notifier.send_shutdown_notification()
                await self.notifier.stop()
                log.info("Telegram notifier stopped", tag="NOTIFIER")
            except Exception as e:
                logger.warning(f"Failed to stop Telegram notifier: {e}")
        
        # Cancel event thread
        if self.event_thread:
            self.event_thread.cancel()
            try:
                await self.event_thread
            except asyncio.CancelledError:
                pass
        
        # Stop macro thread
        if self.macro_thread:
            await self.macro_thread.stop()
        
        # Stop On Bar thread(s)
        onbar_threads = list(self.onbar_threads)
        if not onbar_threads and self.onbar_thread is not None:
            onbar_threads = [self.onbar_thread]
        for thread in onbar_threads:
            await thread.stop()
        
        # Stop shared state cleanup
        await self.shared_state.stop_cleanup_task()
        
        success("All threads stopped")
    
    async def _print_system_status(self) -> None:
        """Print system status"""
        separator("=", 60)
        info("SYSTEM STATUS", tag="STATUS")
        separator("-", 60)
        
        # Thread manager stats
        thread_stats = await self.thread_manager.get_statistics()
        log.info(f"Thread Manager: {thread_stats['total_threads']} threads")
        
        # Macro thread stats
        if self.macro_thread:
            macro_stats = self.macro_thread.get_statistics()
            log.info(f"Macro Thread: {macro_stats['total_runs']} runs")
        
        # On Bar thread stats
        if self.onbar_thread:
            onbar_stats = self.onbar_thread.get_statistics()
            log.info(f"On Bar Thread: {onbar_stats['total_bars']} bars")
        
        # Trigger registry stats
        trigger_stats = self.trigger_registry.get_statistics()
        log.info(f"Triggers: {trigger_stats.total_triggers} registered")
        
        # Emergency handler stats
        if self.emergency_handler:
            emergency_stats = self.emergency_handler.get_statistics()
            log.info(f"Emergency Handler: {emergency_stats['total_handled']} handled")
        
        # Shared state stats
        state_stats = await self.shared_state.get_statistics()
        log.info(f"Shared State: {state_stats['total_keys']} keys")
        
        # Event queue stats
        queue_stats = await self.event_queue.get_statistics()
        log.info(f"Event Queue: {queue_stats['queue_size']} pending")
        
        separator("=", 60)
    
    async def run(self) -> None:
        """Run the system (blocking)"""
        await self.initialize()
        await self.start()
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        # Stop system
        await self.stop()
    
    def setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            log.info(f"Received signal {signum}, initiating shutdown...")
            # 只觸發關閉事件; stop() 內部會設置 _running=False 並
            # 執行 notifier shutdown 通知 (若在此提前設 False, stop() 會直接 return)
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main entry point"""
    log.info("Starting Vibe Trading Multi-Threaded System")
    separator("=", 60)
    
    # Create system
    system = MultiThreadedTradingSystem(
        symbol="BTCUSDT",
        interval="3m",
    )
    
    # Setup signal handlers
    system.setup_signal_handlers()
    
    try:
        # Run system
        await system.run()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
        await system.stop()
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        await system.stop()
    
    log.info("System shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
