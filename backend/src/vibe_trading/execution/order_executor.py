"""
订单执行模块

提供订单执行的抽象层，支持 Paper Trading 和 Binance 实盘。
"""
import logging
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
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
    OKX_LIVE = "okx_live"
    OKX_TESTNET = "okx_testnet"


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
        self._pending_orders: List[Dict] = []  # STOP/TP conditional orders
        self._current_prices: Dict[str, float] = {}
        # Phase 2.3: 永續合約保真度
        self._last_funding_settlement: Dict[str, int] = {}  # symbol → hour key
        self._funding_paid = 0.0
        self._liquidation_events: List[Dict] = []
        # Phase 4.2: 退出階梯
        self._exit_states: Dict[str, Any] = {}
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
        
        # Check pending conditional orders
        self._check_pending_orders(symbol, price)
        # Phase 2.3: 分級維持保證金強平檢查
        try:
            self.check_liquidation(symbol, price)
        except Exception as e:
            logger.warning(f"Liquidation check failed: {e}")
        # Phase 4.2: 退出階梯 (trailing/moonbag)
        try:
            self._run_exit_ladder(symbol, price)
        except Exception as e:
            logger.warning(f"Exit ladder failed: {e}")

    # ------------------------------------------------------------------
    # Phase 2.3: 永續合約資金費率結算 + 分級維持保證金強平
    # ------------------------------------------------------------------

    # 資金費率結算點 (UTC 0/8/16 時)
    FUNDING_HOURS = (0, 8, 16)
    # OKX 簡化分級維持保證金表 (HKUDS crypto.py 驗證)
    MAINTENANCE_TIERS = [
        (100_000, 0.004), (500_000, 0.006), (1_000_000, 0.01),
        (5_000_000, 0.02), (10_000_000, 0.05), (float("inf"), 0.10),
    ]

    def _is_funding_hour(self, open_time_ms: int) -> bool:
        """判斷 bar 開盤時間是否落在資金費率結算點 (UTC 0/8/16 時)."""
        hour = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).hour
        return hour in self.FUNDING_HOURS

    def settle_funding(
        self,
        symbol: str,
        open_time_ms: int,
        mark_price: float,
        funding_rate: float = 0.0001,
    ) -> Dict:
        """資金費率結算 (永續合約, Phase 2.3).

        fee = size × mark × rate × direction (long 付正費率)
        per-symbol 去重: 同一 (symbol, hour) 只結算一次.
        Returns: {"fee": float, "settled": bool}
        """
        hour_key = open_time_ms // 3_600_000
        if self._last_funding_settlement.get(symbol) == hour_key:
            return {"fee": 0.0, "settled": False}
        if not self._is_funding_hour(open_time_ms):
            return {"fee": 0.0, "settled": False}

        total_fee = 0.0
        for pos in self._positions.values():
            if pos.symbol != symbol or pos.leverage <= 1.0:
                continue  # 現貨 (槓桿 1) 無 funding
            direction = 1.0 if pos.position_side == PositionSide.LONG else -1.0
            fee = pos.quantity * mark_price * funding_rate * direction
            total_fee += fee

        if abs(total_fee) > 1e-12:
            self._balance -= total_fee
            self._funding_paid += total_fee
            self._last_funding_settlement[symbol] = hour_key
            logger.info(
                f"Funding settled {symbol}: {total_fee:+.4f} USDT "
                f"(hour {datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc):%H})"
            )
        return {"fee": total_fee, "settled": abs(total_fee) > 1e-12}

    def _maintenance_rate(self, notional: float) -> float:
        """OKX 分級維持保證金率."""
        for tier, rate in self.MAINTENANCE_TIERS:
            if notional <= tier:
                return rate
        return 0.10

    def check_liquidation(self, symbol: str, mark_price: float) -> List[Dict]:
        """分級維持保證金強平判定 (Phase 2.3).

        margin = size × entry / leverage
        unrealized = dir × size × (mark − entry)
        強平: margin + unrealized ≤ notional × tier_rate
        Returns: 被強平倉位列表 (已平倉, 記錄 realized).
        """
        liquidated: List[Dict] = []
        for key, pos in list(self._positions.items()):
            if pos.symbol != symbol or pos.leverage <= 1.0:
                continue  # 現貨無強平
            margin = pos.quantity * pos.entry_price / pos.leverage
            if pos.position_side == PositionSide.LONG:
                unrealized = pos.quantity * (mark_price - pos.entry_price)
            else:
                unrealized = pos.quantity * (pos.entry_price - mark_price)
            notional = pos.quantity * mark_price
            if margin + unrealized <= notional * self._maintenance_rate(notional):
                # 強平: 全額平倉, 剩餘保證金退回
                realized = unrealized - margin
                pos.realized_pnl += realized
                self._realized_pnl += realized
                self._balance += margin + unrealized
                del self._positions[key]
                event = {
                    "symbol": symbol,
                    "side": pos.position_side.value,
                    "quantity": pos.quantity,
                    "entry": pos.entry_price,
                    "mark": mark_price,
                    "realized": realized,
                }
                self._liquidation_events.append(event)
                liquidated.append(event)
                logger.warning(
                    f"[強平] {symbol} {pos.position_side.value} {pos.quantity} "
                    f"@ {mark_price:.2f} (realized {realized:+.2f})"
                )
        return liquidated

    def _run_exit_ladder(self, symbol: str, price: float) -> None:
        """退出階梯狀態機 (Phase 4.2): trailing/moonbag.

        純同步 (update_price 是 sync) — 直接更新 balance/positions.
        """
        from vibe_trading.execution.exit_ladder import make_exit_state, update_exit

        for key, pos in list(self._positions.items()):
            if pos.symbol != symbol:
                continue
            state = self._exit_states.get(key)
            if state is None:
                state = make_exit_state(symbol, pos.entry_price)
                self._exit_states[key] = state
            action = update_exit(state, price, pos.quantity)
            if action["action"] == "sell_all":
                self._sync_close(key, price, pos.quantity, action["reason"])
            elif action["action"] == "sell_half":
                self._sync_close(key, price, action["quantity"], action["reason"])

    def _sync_close(self, key: str, price: float, qty: float, reason: str) -> None:
        """同步平倉 (LONG) — 退回保證金 + realized 入帳."""
        pos = self._positions.get(key)
        if pos is None or pos.quantity <= 0:
            return
        close_qty = min(qty, pos.quantity)
        realized = (price - pos.entry_price) * close_qty
        pos.realized_pnl += realized
        self._realized_pnl += realized
        self._balance += pos.entry_price * close_qty / pos.leverage + realized
        pos.quantity -= close_qty
        logger.info(f"[退出階梯] {reason}: close {close_qty} {key} @ {price:.2f} (realized {realized:+.2f})")
        if pos.quantity <= 0:
            del self._positions[key]

    def _check_pending_orders(self, symbol: str, price: float) -> None:
        """Check and execute pending conditional orders when trigger price is hit."""
        triggered = []
        for pending in self._pending_orders:
            if pending['symbol'] != symbol:
                continue
            
            stop_price = pending['stop_price']
            order_type = pending['order_type']
            
            # STOP_MARKET: trigger when price <= stop_price (for LONG positions)
            if order_type == OrderType.STOP_MARKET:
                if price <= stop_price:
                    triggered.append(pending)
            
            # TAKE_PROFIT_MARKET: trigger when price >= stop_price (for LONG positions)
            elif order_type == OrderType.TAKE_PROFIT_MARKET:
                if price >= stop_price:
                    triggered.append(pending)
        
        # Execute triggered orders
        for pending in triggered:
            self._pending_orders.remove(pending)
            # Execute the order at current market price
            self._execute_pending_order(pending, price)
    
    def _execute_pending_order(self, pending: Dict, execution_price: float) -> OrderResult:
        """Execute a pending conditional order."""
        order_id = pending['order_id']
        symbol = pending['symbol']
        side = pending['side']
        order_type = pending['order_type']
        quantity = pending['quantity']
        position_side = pending['position_side']
        reduce_only = pending['reduce_only']
        
        logger.info(
            f"Conditional order triggered: {order_id} {side.value} {quantity} {symbol} "
            f"@ {execution_price} (stop_price={pending['stop_price']})"
        )
        
        # Update position
        if position_side:
            pos_key = f"{symbol}_{position_side.value}"
            
            if side == OrderSide.BUY:
                if position_side == PositionSide.SHORT and pos_key in self._positions:
                    # Close short position
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
                    # Open/add long position
                    if pos_key in self._positions:
                        # Add to position
                        self._positions[pos_key].quantity += quantity
                        avg_price = (
                            self._positions[pos_key].entry_price * (self._positions[pos_key].quantity - quantity)
                            + execution_price * quantity
                        ) / self._positions[pos_key].quantity
                        self._positions[pos_key].entry_price = avg_price
                    else:
                        # New position
                        self._positions[pos_key] = PaperPosition(
                            symbol=symbol,
                            position_side=position_side,
                            entry_price=execution_price,
                            quantity=quantity,
                        )
                    # Deduct margin
                    self._balance -= (
                        execution_price * quantity / self._positions[pos_key].leverage
                    )
            else:
                # SELL
                if position_side == PositionSide.LONG and pos_key in self._positions:
                    # Close long position
                    pos = self._positions[pos_key]
                    close_qty = min(quantity, pos.quantity)
                    realized = (execution_price - pos.entry_price) * close_qty
                    pos.realized_pnl += realized
                    self._realized_pnl += realized
                    # Return margin + realized PnL
                    self._balance += (
                        pos.entry_price * close_qty / pos.leverage + realized
                    )
                    pos.quantity -= close_qty
                    if pos.quantity <= 0:
                        del self._positions[pos_key]
                elif pos_key in self._positions:
                    # Add to short position
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
                    # New short position
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
            price=None,
            filled_price=execution_price,
            filled_quantity=quantity,
            status="FILLED",
            timestamp=int(datetime.now().timestamp() * 1000),
            is_paper=True,
        )
        
        self._orders[order_id] = result
        self._save_state()
        
        return result

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

        # Conditional orders (STOP/TP) are stored as pending until trigger price is hit
        if order_type in (OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET):
            if stop_price is None:
                logger.warning(f"Conditional order {order_id} has no stop_price, rejecting")
                return OrderResult(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    filled_price=None,
                    filled_quantity=0,
                    status="REJECTED",
                    timestamp=timestamp,
                    is_paper=True,
                )
            
            pending_order = {
                'order_id': order_id,
                'symbol': symbol,
                'side': side,
                'order_type': order_type,
                'quantity': quantity,
                'stop_price': stop_price,
                'position_side': position_side,
                'reduce_only': reduce_only,
                'created_at': timestamp,
            }
            self._pending_orders.append(pending_order)
            logger.info(
                f"Conditional order stored: {order_id} {side.value} {quantity} {symbol} "
                f"stop_price={stop_price} type={order_type.value}"
            )
            
            # Check if trigger is already hit (e.g., price already past stop)
            current_price = self._current_prices.get(symbol)
            if current_price is not None:
                self._check_pending_orders(symbol, current_price)
            
            return OrderResult(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                filled_price=None,
                filled_quantity=0,
                status="PENDING",
                timestamp=timestamp,
                is_paper=True,
            )

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
        mode: 交易模式 (PAPER, TESTNET, LIVE, OKX_LIVE, OKX_TESTNET)
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
    elif mode == TradingMode.OKX_LIVE:
        from vibe_trading.execution.broker_connector import BrokerConfig, BrokerType
        from vibe_trading.execution.okx_executor import OkxOrderExecutor

        if not settings.okx_api_key or not settings.okx_api_secret or not settings.okx_passphrase:
            raise ValueError("OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE are required for OKX live trading")

        if dry_run:
            logger.info("Creating OKX Live executor (DRY-RUN mode)")
        else:
            logger.info("Creating OKX Live executor")

        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key=settings.okx_api_key,
            api_secret=settings.okx_api_secret,
            passphrase=settings.okx_passphrase,
            testnet=False,
            dry_run=dry_run,
        )
        return OkxOrderExecutor(config)

    elif mode == TradingMode.OKX_TESTNET:
        from vibe_trading.execution.broker_connector import BrokerConfig, BrokerType
        from vibe_trading.execution.okx_executor import OkxOrderExecutor

        if not settings.okx_api_key or not settings.okx_api_secret or not settings.okx_passphrase:
            raise ValueError("OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE are required for OKX testnet trading")

        logger.info("Creating OKX Testnet executor")

        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key=settings.okx_api_key,
            api_secret=settings.okx_api_secret,
            passphrase=settings.okx_passphrase,
            testnet=True,
            dry_run=dry_run,
        )
        return OkxOrderExecutor(config)

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
