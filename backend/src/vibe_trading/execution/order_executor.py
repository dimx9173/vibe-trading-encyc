"""
订单执行模块

提供订单执行的抽象层，支持 Paper Trading 和 Binance 实盘。
"""
import logging
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import uuid

from vibe_trading.data_sources.binance_client import (
    BinanceClient,
    BinanceConfig,
    Position,
    OrderSide,
    OrderType,
    PositionSide,
)
from vibe_trading.config.binance_config import BinanceEnvironment
from vibe_trading.config.settings import get_settings
from vibe_trading.execution.exchange_filters import ExchangeFilterValidator

logger = logging.getLogger(__name__)


class TradingMode(str, Enum):
    """交易模式"""
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"


@dataclass
class OrderResult:
    """订单执行结果"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float]
    filled_price: Optional[float]
    filled_quantity: float
    status: str
    timestamp: int
    is_paper: bool


@dataclass
class PaperPosition:
    """Paper Trading 持仓"""
    symbol: str
    position_side: PositionSide
    entry_price: float
    quantity: float
    leverage: int = 5
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @property
    def notional(self) -> float:
        """持仓价值"""
        return self.quantity * self.entry_price

    def update_unrealized_pnl(self, current_price: float) -> None:
        """更新未实现盈亏"""
        if self.position_side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity


class OrderExecutor(ABC):
    """订单执行器抽象基类"""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """下单"""
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消订单"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """获取持仓"""
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """获取余额"""
        pass


class PaperOrderExecutor(OrderExecutor):
    """Paper Trading 订单执行器"""

    def __init__(
        self,
        initial_balance: float = 10000.0,
        state_file: Optional[str] = None,
        reset: bool = False,
    ):
        self._positions: Dict[str, PaperPosition] = {}
        self._balance = initial_balance
        self._realized_pnl = 0.0  # 累計已實現盈虧（跨平倉保留，避免 del 後丟失）
        self._orders: Dict[str, OrderResult] = {}
        self._current_prices: Dict[str, float] = {}
        self._state_file = state_file
        if state_file and os.path.exists(state_file) and not reset:
            self._load_state()
        elif state_file and reset:
            logger.info(
                f"Paper account reset requested; starting fresh (balance={initial_balance})"
            )

    # ------------------------------------------------------------------
    # 持久化：balance + positions + realized_pnl 跨重啟保留
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        """從 state 檔還原帳戶狀態（balance / positions / realized_pnl）。"""
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._balance = float(data.get("balance", self._balance))
            self._realized_pnl = float(data.get("realized_pnl", 0.0))
            for p in data.get("positions", []):
                pos = PaperPosition(
                    symbol=p["symbol"],
                    position_side=PositionSide(p["position_side"]),
                    entry_price=float(p["entry_price"]),
                    quantity=float(p["quantity"]),
                    leverage=int(p.get("leverage", 5)),
                    realized_pnl=float(p.get("realized_pnl", 0.0)),
                )
                self._positions[f"{pos.symbol}_{pos.position_side.value}"] = pos
            logger.info(
                f"Paper state restored: balance={self._balance:.2f}, "
                f"positions={len(self._positions)}, realized_pnl={self._realized_pnl:.2f}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to load paper state from {self._state_file}: {e}; starting fresh"
            )

    def _save_state(self) -> None:
        """序列化帳戶狀態到 state 檔（atomic write）。"""
        if not self._state_file:
            return
        try:
            state = {
                "balance": self._balance,
                "realized_pnl": self._realized_pnl,
                "positions": [
                    {
                        "symbol": pos.symbol,
                        "position_side": pos.position_side.value,
                        "entry_price": pos.entry_price,
                        "quantity": pos.quantity,
                        "leverage": pos.leverage,
                        "realized_pnl": pos.realized_pnl,
                    }
                    for pos in self._positions.values()
                ],
            }
            os.makedirs(os.path.dirname(self._state_file) or ".", exist_ok=True)
            tmp = f"{self._state_file}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._state_file)
        except Exception as e:
            logger.warning(f"Failed to save paper state to {self._state_file}: {e}")

    def update_price(self, symbol: str, price: float) -> None:
        """更新当前价格（模拟市场价格）"""
        self._current_prices[symbol] = price
        # 更新所有持仓的未实现盈亏
        for pos in self._positions.values():
            if pos.symbol == symbol:
                pos.update_unrealized_pnl(price)

    def get_reference_price(self, symbol: str) -> Optional[float]:
        """Return the latest paper-market reference price for risk checks."""
        return self._current_prices.get(symbol)

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """下单（模拟）"""
        order_id = f"paper_{uuid.uuid4().hex[:8]}"
        timestamp = int(datetime.now().timestamp() * 1000)

        # 获取执行价格
        if price is None:
            execution_price = self._current_prices.get(symbol, 0)
        else:
            execution_price = price

        if execution_price == 0:
            logger.warning(f"No price available for {symbol}, using mock price 50000")
            execution_price = 50000.0  # 模拟价格

        filled_quantity = quantity
        status = "FILLED"

        # 更新持仓
        if position_side:
            pos_key = f"{symbol}_{position_side.value}"

            if side == OrderSide.BUY:
                if position_side == PositionSide.SHORT and pos_key in self._positions:
                    # 平空仓：BUY + SHORT
                    pos = self._positions[pos_key]
                    close_qty = min(quantity, pos.quantity)
                    realized = (pos.entry_price - execution_price) * close_qty
                    pos.realized_pnl += realized
                    self._realized_pnl += realized
                    self._balance += (
                        pos.entry_price * close_qty / pos.leverage + realized
                    )
                    pos.quantity -= close_qty
                    if pos.quantity <= 0:
                        del self._positions[pos_key]
                else:
                    # 开/加多仓：BUY + LONG
                    if pos_key in self._positions:
                        # 加仓
                        self._positions[pos_key].quantity += quantity
                        avg_price = (
                            self._positions[pos_key].entry_price * (self._positions[pos_key].quantity - quantity)
                            + execution_price * quantity
                        ) / self._positions[pos_key].quantity
                        self._positions[pos_key].entry_price = avg_price
                    else:
                        # 新建仓位
                        self._positions[pos_key] = PaperPosition(
                            symbol=symbol,
                            position_side=position_side,
                            entry_price=execution_price,
                            quantity=quantity,
                        )
                    # 扣保证金（名义价值 / 杠杆）
                    self._balance -= (
                        execution_price * quantity / self._positions[pos_key].leverage
                    )
            else:
                # SELL
                if position_side == PositionSide.LONG and pos_key in self._positions:
                    # 平多仓：SELL + LONG
                    pos = self._positions[pos_key]
                    close_qty = min(quantity, pos.quantity)
                    realized = (execution_price - pos.entry_price) * close_qty
                    pos.realized_pnl += realized
                    self._realized_pnl += realized
                    # 退回原保证金（按开仓价计算）+ 已实现盈亏入账
                    self._balance += (
                        pos.entry_price * close_qty / pos.leverage + realized
                    )
                    pos.quantity -= close_qty
                    if pos.quantity <= 0:
                        del self._positions[pos_key]
                elif pos_key in self._positions:
                    # 空仓加仓：SELL + SHORT
                    self._positions[pos_key].quantity += quantity
                    avg_price = (
                        self._positions[pos_key].entry_price * (self._positions[pos_key].quantity - quantity)
                        + execution_price * quantity
                    ) / self._positions[pos_key].quantity
                    self._positions[pos_key].entry_price = avg_price
                    self._balance -= (
                        execution_price * quantity / self._positions[pos_key].leverage
                    )
                elif position_side == PositionSide.SHORT:
                    # 新建空仓：SELL + SHORT
                    self._positions[pos_key] = PaperPosition(
                        symbol=symbol,
                        position_side=position_side,
                        entry_price=execution_price,
                        quantity=quantity,
                    )
                    self._balance -= (
                        execution_price * quantity / self._positions[pos_key].leverage
                    )
                else:
                    logger.warning(f"No position to close for {pos_key}")

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            filled_price=execution_price,
            filled_quantity=filled_quantity,
            status=status,
            timestamp=timestamp,
            is_paper=True,
        )

        self._orders[order_id] = result
        logger.info(f"Paper order placed: {side.value} {quantity} {symbol} @ {execution_price}")

        # 每次成交後持久化帳戶狀態（跨重啟保留）
        self._save_state()

        return result

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消订单（模拟）"""
        if order_id in self._orders:
            self._orders[order_id].status = "CANCELED"
            logger.info(f"Paper order canceled: {order_id}")
            return True
        return False

    async def get_positions(self) -> List[Position]:
        """获取持仓（转换为标准格式）"""
        positions = []
        for pos in self._positions.values():
            current_price = self._current_prices.get(pos.symbol, pos.entry_price)
            pos.update_unrealized_pnl(current_price)

            positions.append(
                Position(
                    symbol=pos.symbol,
                    position_amount=pos.quantity,
                    entry_price=pos.entry_price,
                    mark_price=current_price,
                    unrealized_profit=pos.unrealized_pnl,
                    liquidation_price=0.0,  # Paper trading 不计算强平价
                    leverage=pos.leverage,
                    position_side=pos.position_side,
                    notional=pos.notional,
                    isolated=False,
                    adl_quantile=0,
                )
            )
        return positions

    async def get_balance(self) -> Dict[str, float]:
        """获取余额（真实账本：现金余额已含已实现盈亏，realized 跨平仓保留）"""
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self._positions.values())

        return {
            "USDT": {
                "balance": self._balance,
                "available": self._balance + total_unrealized_pnl,
                "unrealized_pnl": total_unrealized_pnl,
                "realized_pnl": self._realized_pnl,
            }
        }


class BinanceOrderExecutor(OrderExecutor):
    """Binance 实盘订单执行器"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True, dry_run: bool = False):
        config = BinanceConfig(
            environment=BinanceEnvironment.TESTNET if testnet else BinanceEnvironment.MAINNET,
            api_key=api_key,
            api_secret=api_secret,
        )
        self._client = BinanceClient(config)
        self._dry_run = dry_run  # dry-run模式：只打印订单不执行
        self._exchange_filter_validator: Optional[ExchangeFilterValidator] = None

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """下单"""
        if self._dry_run:
            # ========== dry-run模式：只打印不执行 ==========
            order_id = f"dryrun_{uuid.uuid4().hex[:8]}"
            timestamp = int(datetime.now().timestamp() * 1000)

            logger.info("=" * 60)
            logger.info("🚨 [DRY-RUN] 订单打印 (不会实际执行)")
            logger.info(f"  Symbol: {symbol}")
            logger.info(f"  Side: {side.value}")
            logger.info(f"  Type: {order_type.value}")
            logger.info(f"  Quantity: {quantity}")
            logger.info(f"  Price: {price}")
            logger.info(f"  Position Side: {position_side.value if position_side else 'N/A'}")
            logger.info("=" * 60)

            return OrderResult(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                filled_price=price,  # dry-run假设立即成交
                filled_quantity=quantity,
                status="FILLED",  # dry-run假设立即成交
                timestamp=timestamp,
                is_paper=False,  # 不是paper，是dry-run
            )

        # 真实执行
        order = await self._client.rest.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            position_side=position_side,
            reduce_only=reduce_only,
        )

        return OrderResult(
            order_id=str(order.order_id),
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
            filled_price=order.price if order.status == "FILLED" else None,
            filled_quantity=order.executed_qty,
            status=order.status,
            timestamp=int(datetime.now().timestamp() * 1000),
            is_paper=False,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消订单"""
        if self._dry_run:
            logger.info(f"🚨 [DRY-RUN] 取消订单: {order_id} (不会实际执行)")
            return True

        try:
            await self._client.rest.cancel_order(symbol, order_id=int(order_id))
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False

    async def get_positions(self) -> List[Position]:
        """获取持仓"""
        return await self._client.rest.get_position()

    async def get_balance(self) -> Dict[str, float]:
        """获取余额"""
        balance = await self._client.rest.get_balance()
        return {k: v["balance"] for k, v in balance.items()}

    async def get_exchange_filter_validator(self) -> ExchangeFilterValidator:
        """Load and cache Binance symbol filters for local validation."""
        if self._exchange_filter_validator is None:
            self._exchange_filter_validator = ExchangeFilterValidator(
                await self._client.rest.get_symbol_filters()
            )
        return self._exchange_filter_validator

    async def close(self) -> None:
        """关闭连接"""
        await self._client.close()


def create_executor(
    mode: TradingMode = TradingMode.PAPER,
    dry_run: bool = False,
    paper_state_file: Optional[str] = None,
    reset_paper: bool = False,
) -> OrderExecutor:
    """创建订单执行器

    Args:
        mode: 交易模式 (PAPER 或 LIVE)
        dry_run: 是否为dry-run模式 (仅打印订单不执行，仅适用于LIVE模式)
        paper_state_file: paper 模式帳戶狀態檔路徑（跨重啟保留 balance/positions）
        reset_paper: 為 True 時忽略 state 檔，從初始餘額重新開始
    """
    settings = get_settings()

    if mode == TradingMode.PAPER:
        logger.info("Creating Paper Trading executor")
        return PaperOrderExecutor(
            state_file=paper_state_file,
            reset=reset_paper,
        )
    elif mode == TradingMode.TESTNET:
        if not settings.binance_testnet_api_key or not settings.binance_testnet_api_secret:
            raise ValueError("BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET are required for testnet trading")

        logger.info("Creating Binance Testnet executor")
        return BinanceOrderExecutor(
            api_key=settings.binance_testnet_api_key,
            api_secret=settings.binance_testnet_api_secret,
            testnet=True,
            dry_run=dry_run,
        )
    else:
        if dry_run:
            logger.info("Creating Binance Live executor (DRY-RUN mode - orders will be printed but not executed)")
        else:
            logger.info("Creating Binance Live executor (orders will be executed)")

        if not settings.binance_api_key or not settings.binance_api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET are required for live trading")

        return BinanceOrderExecutor(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=False,
            dry_run=dry_run,
        )
