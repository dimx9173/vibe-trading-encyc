"""RuleEngineLoop — on-bar rule-driven trading loop (spec phase1 §3.3).

Per closed bar (fixed order, no step may be skipped):
1. store_kline (store-before-decide, no look-ahead)
2. executor.update_price (paper fill for this bar)
3. exit evaluation (ExitLadderEngine is the single exit authority; reduce-only orders)
4. regime gate (RISK_OFF blocks new entries only)
5. signal (AlphaZoo -> generate_signal; FLAT ends bar)
6. sizing (Half-Kelly ATR; NEUTRAL x0.5)
7. grounding (validate_trading_plan_prices)
8. PreTradeRiskGate -> place_order (MARKET only — no conditional SL/TP, avoiding a
   second exit path via executor pending orders) + ExecutionAuditStorage record

Does not import TradingCoordinator. Exit orders bypass PreTradeRiskGate so
RISK_OFF can never block an exit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional, Tuple

from pi_logger import get_logger

from vibe_trading.data_sources.alphas.zoo import AlphaZoo
from vibe_trading.data_sources.base import Kline as BaseKline
from vibe_trading.data_sources.binance_client import (
    OrderSide,
    OrderType,
    Position,
    PositionSide,
)
from vibe_trading.data_sources.kline_storage import Kline, KlineQuery, KlineStorage
from vibe_trading.data_sources.macro_storage import MacroStorage, get_macro_storage
from vibe_trading.execution.exit_ladder import ExitLadderConfig, ExitLadderEngine, LadderStage
from vibe_trading.execution.grounding_gate import validate_trading_plan_prices
from vibe_trading.execution.order_audit import ExecutionAuditStorage
from vibe_trading.execution.order_executor import OrderExecutor, PaperOrderExecutor
from vibe_trading.execution.position_sizing import calculate_atr_position_size
from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate, PreTradeRiskResult, RiskPolicy
from vibe_trading.rule_engine.config import RuleEngineConfig
from vibe_trading.rule_engine.regime_gate import Regime, current_regime
from vibe_trading.rule_engine.signal import RuleSignal, generate_signal

logger = get_logger(__name__)

_KLINE_LIMIT = 60


@dataclass
class RuleDecision:
    """每 bar 全貌 (日志 / replay JSONL / 测试断言)."""

    symbol: str
    bar_open_time: int
    bar_close: float
    regime: Optional[str]
    signal: Optional[RuleSignal] = None
    direction: Literal["LONG", "SHORT", "FLAT"] = "FLAT"
    qty: float = 0.0
    action: str = "hold"             # hold | open | exit | reduce
    blocked_by: Optional[str] = None # RISK_OFF | grounding | risk_gate | None
    ladder_stage: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _LadderState:
    stage: LadderStage = LadderStage.INITIAL
    entry: float = 0.0
    highest: float = 0.0
    lowest: float = 0.0
    stop: Optional[float] = None


class RuleEngineLoop:
    def __init__(
        self,
        symbol: str,
        interval: str = "30m",
        storage: Optional[KlineStorage] = None,
        executor: Optional[OrderExecutor] = None,
        macro_storage: Optional[MacroStorage] = None,
        config: Optional[RuleEngineConfig] = None,
        audit_storage: Optional[ExecutionAuditStorage] = None,
        risk_policy: Optional[RiskPolicy] = None,
    ):
        self.symbol = symbol
        self.interval = interval
        self.config = config or RuleEngineConfig.from_env()
        self.storage = storage or KlineStorage()
        self.executor = executor
        self.macro_storage = macro_storage or get_macro_storage()
        self._audit = audit_storage
        # 出场阶梯与 RuleEngineConfig 对齐（阶段2 修复: tp_atr_mult 此前未生效）:
        # R = sl_atr_mult×ATR（风险单位 = 硬止损距离）; TP1 = 0.6×tp_atr_mult×ATR;
        # TP2 = tp_atr_mult×ATR（完整目标）; stage 30/40/30 拆分不变.
        ladder_cfg = ExitLadderConfig(
            r_atr_multiple=self.config.sl_atr_mult,
            tp1_r_multiple=0.6 * self.config.tp_atr_mult / self.config.sl_atr_mult,
            tp2_r_multiple=self.config.tp_atr_mult / self.config.sl_atr_mult,
        )
        self._ladder = ExitLadderEngine(ladder_cfg)
        self._ladder_states: Dict[str, _LadderState] = {}
        # 风控门策略与 RuleEngineConfig 对齐（阶段2 修复）:
        # - max_single_order_notional = 仓位上限 (同 sizing 口径, 否则全部订单被默认 100U 拒绝)
        # - min_confidence = 0 (信号已由 entry_threshold ±0.3 把关; strength 即信号幅度)
        # - max_total_exposure = 3 标的同时持仓
        # 可经 risk_policy 显式覆写 (测试/回测注入). 默认对齐 = 策略参数, 非新增功能.
        self._risk_gate: Optional[PreTradeRiskGate] = None
        if executor is not None:
            policy = risk_policy or RiskPolicy(
                max_single_order_notional=self.config.max_single_notional,
                max_total_exposure=self.config.max_single_notional * 3,
                max_margin_fraction=0.5,
                position_mode="hedge",
                min_confidence=0.0,
            )
            self._risk_gate = PreTradeRiskGate(executor, policy)
        self._interval_ms = self._parse_interval_ms(interval)

    @staticmethod
    def _parse_interval_ms(interval: str) -> int:
        unit_map = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
        unit = interval[-1]
        num = int(interval[:-1])
        return num * unit_map.get(unit, 60_000)

    # ------------------------------------------------------------------
    # 辅助: kline 归一化 / 因子 / 结构价 / 下单方位
    # ------------------------------------------------------------------

    def _normalize_kline(self, k: Any) -> Kline:
        open_time = int(getattr(k, "open_time", 0) or 0)
        ct = getattr(k, "close_time", None)
        if ct is None:
            ct = open_time + self._interval_ms - 1
        elif isinstance(ct, (int, float)):
            ct = int(ct)
        else:
            ct = int(ct.timestamp() * 1000)
        return Kline(
            symbol=getattr(k, "symbol", self.symbol),
            interval=getattr(k, "interval", self.interval),
            open_time=open_time,
            open=float(getattr(k, "open", 0.0)),
            high=float(getattr(k, "high", 0.0)),
            low=float(getattr(k, "low", 0.0)),
            close=float(getattr(k, "close", 0.0)),
            volume=float(getattr(k, "volume", 0.0)),
            close_time=ct,
            quote_volume=float(getattr(k, "quote_volume", 0.0)),
            trades=int(getattr(k, "trades", 0) or 0),
            taker_buy_base=float(getattr(k, "taker_buy_base", 0.0)),
            taker_buy_quote=float(getattr(k, "taker_buy_quote", 0.0)),
            is_final=bool(getattr(k, "is_final", True)),
        )

    @staticmethod
    def _to_base_kline(k: Kline) -> BaseKline:
        return BaseKline(
            symbol=k.symbol,
            interval=k.interval,
            open_time=datetime.fromtimestamp(k.open_time / 1000),
            open=k.open,
            high=k.high,
            low=k.low,
            close=k.close,
            volume=k.volume,
        )

    async def _recent_klines(self) -> List[Kline]:
        return await self.storage.query_klines(
            KlineQuery(symbol=self.symbol, interval=self.interval, limit=_KLINE_LIMIT)
        )

    async def _recent_factors(self) -> Dict[str, float]:
        rows = await self._recent_klines()
        return AlphaZoo.calculate([self._to_base_kline(r) for r in rows])

    @staticmethod
    def _atr(factors: Dict[str, float], price: float) -> float:
        atr = float(factors.get("atr", 0.0) or 0.0)
        if atr <= 0:
            atr = max(price * 0.005, 1e-9)
        return atr

    def _structure_prices(
        self, direction: Literal["LONG", "SHORT", "FLAT"], entry: float, atr: float
    ) -> Tuple[float, float]:
        sl_dist = self.config.sl_atr_mult * atr
        tp_dist = self.config.tp_atr_mult * atr
        if direction == "SHORT":
            return entry + sl_dist, entry - tp_dist
        return entry - sl_dist, entry + tp_dist

    @staticmethod
    def _order_sides(direction: str) -> Tuple[OrderSide, PositionSide]:
        if direction == "SHORT":
            return OrderSide.SELL, PositionSide.SHORT
        return OrderSide.BUY, PositionSide.LONG

    @staticmethod
    def _directional_gain(side: str, entry: float, price: float) -> float:
        return entry - price if side == "SHORT" else price - entry

    async def _get_equity(self) -> float:
        if self.executor is None:
            return 10000.0
        balances = await self.executor.get_balance()
        usdt = balances.get("USDT", 10000.0)
        if isinstance(usdt, dict):
            return float(usdt.get("available", usdt.get("balance", 10000.0)))
        return float(usdt)

    # ------------------------------------------------------------------
    # 审计 (ExecutionAuditStorage 复用)
    # ------------------------------------------------------------------

    def _audit_store(self) -> ExecutionAuditStorage:
        if self._audit is None:
            self._audit = ExecutionAuditStorage()
        return self._audit

    async def _record_risk_check(
        self, k: Kline, risk: PreTradeRiskResult, qty: float
    ) -> None:
        try:
            await self._audit_store().record_risk_check(
                trace_id=f"rule_{self.symbol}_{k.open_time}",
                symbol=self.symbol,
                interval=self.interval,
                open_time_ms=k.open_time,
                verdict=risk.verdict.value,
                reason=risk.reason,
                request={"symbol": self.symbol, "quantity": qty},
                metrics=risk.checks,
            )
        except Exception as e:
            logger.warning(f"audit risk record failed: {e}", tag="RuleEngine")

    async def _record_order(self, k: Kline, result: Any) -> None:
        try:
            await self._audit_store().record_order(
                trace_id=f"rule_{self.symbol}_{k.open_time}",
                symbol=self.symbol,
                interval=self.interval,
                open_time_ms=k.open_time,
                order_id=str(result.order_id) if result.order_id else None,
                status=str(result.status),
                side=str(getattr(result.side, "value", result.side)),
                order_type=str(getattr(result.order_type, "value", result.order_type)),
                quantity=float(result.quantity),
                result={
                    "filled_price": result.filled_price,
                    "filled_quantity": result.filled_quantity,
                },
            )
        except Exception as e:
            logger.warning(f"audit order record failed: {e}", tag="RuleEngine")

    # ------------------------------------------------------------------
    # 主回路
    # ------------------------------------------------------------------

    async def on_bar(self, kline: Any) -> RuleDecision:
        if self.executor is None:
            return RuleDecision(
                symbol=self.symbol,
                bar_open_time=0,
                bar_close=float(getattr(kline, "close", 0.0)),
                regime=None,
                action="hold",
                reason="no executor configured",
            )

        executor = self.executor
        k = self._normalize_kline(kline)

        # 1. store-before-decide (replay 防 look-ahead 纪律)
        await self.storage.store_kline(k)

        # 2. 该 bar 撮合 (paper 模式)
        if isinstance(executor, PaperOrderExecutor):
            executor.update_price(self.symbol, k.close)

        # 3. 出场评估 (单一权威: ExitLadderEngine)
        # no-pyramiding: 持仓期间步 4–8 跳过 — _evaluate_exit 有持仓即返回（含 hold），本 bar 结束。
        exit_decision = await self._evaluate_exit(k)
        if exit_decision is not None:
            return exit_decision

        # 4. regime gate
        regime = await current_regime(
            self.macro_storage, self.config.macro_max_age_seconds, symbol=self.symbol
        )
        if regime == Regime.RISK_OFF:
            logger.info(
                f"[RuleLoop] {self.symbol} bar {k.open_time}: RISK_OFF blocks new entries",
                tag="RuleEngine",
            )
            return self._decision(
                k, regime, action="hold", blocked_by="RISK_OFF",
                reason="RISK_OFF blocks new entries",
            )

        # 5. 信号
        factors = await self._recent_factors()
        signal = generate_signal(factors, threshold=self.config.entry_threshold)
        if signal.direction == "FLAT":
            return self._decision(
                k, regime, signal=signal, action="hold", reason=signal.reason
            )

        # 6. 仓位 (Half-Kelly ATR; NEUTRAL 半仓)
        atr = self._atr(factors, k.close)
        qty = await self._size_position(k.close, signal, regime, atr)
        if qty <= 0:
            return self._decision(
                k, regime, signal=signal, action="hold",
                reason="sizing returned zero (no positive expectancy)",
            )

        # 7. grounding
        sl, tp = self._structure_prices(signal.direction, k.close, atr)
        plan = SimpleNamespace(
            entry_orders=[{"price": k.close}],
            stop_loss_orders=[{"trigger_price": sl}],
            take_profit_orders=[{"price": tp}],
        )
        grounding = validate_trading_plan_prices(plan, k.low, k.high, k.close)
        if not grounding["passed"]:
            return self._decision(
                k, regime, signal=signal, qty=qty, action="hold",
                blocked_by="grounding",
                reason="grounding violations: " + "; ".join(grounding["violations"]),
            )

        # 8. PreTradeRiskGate -> place_order (仅 MARKET, 无条件单)
        side, position_side = self._order_sides(signal.direction)
        risk_gate = self._risk_gate
        assert risk_gate is not None
        risk = await risk_gate.validate_order(
            symbol=self.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            position_side=position_side,
            price=None,
            reference_price=k.close,
            reduce_only=False,
            confidence=signal.strength,
        )
        await self._record_risk_check(k, risk, qty)
        if not risk.approved:
            return self._decision(
                k, regime, signal=signal, qty=qty, action="hold",
                blocked_by="risk_gate",
                reason=f"pre-trade risk rejected: {risk.reason}",
            )

        result = await executor.place_order(
            self.symbol, side, OrderType.MARKET, qty,
            price=None, position_side=position_side, reduce_only=False,
        )
        await self._record_order(k, result)
        # 开仓即武装初始 hard stop（1.5×ATR），消除 TP1 达成前的零止损窗口（P0-1）。
        # state.entry = 成交价让 _evaluate_exit 命中既有 state（不再重建），stop 逐 bar 生效。
        entry = float(getattr(result, "filled_price", None) or k.close)
        self._ladder_states[self.symbol] = _LadderState(
            stage=LadderStage.INITIAL, entry=entry,
            highest=entry, lowest=entry, stop=sl,
        )
        logger.info(
            f"[RuleLoop] {self.symbol} OPEN {side.value} {qty:.6f} @ {k.close:.2f} "
            f"(regime={regime.value}, composite={signal.composite:+.3f}, stop={sl:.2f})",
            tag="RuleEngine",
        )
        return self._decision(
            k, regime, signal=signal, qty=qty, action="open",
            reason=f"opened {side.value} {qty:.6f} @ {k.close:.2f}",
        )

    # ------------------------------------------------------------------
    # 出场评估 (ExitLadderEngine 单一权威)
    # ------------------------------------------------------------------

    async def _evaluate_exit(self, k: Kline) -> Optional[RuleDecision]:
        assert self.executor is not None
        positions: List[Position] = await self.executor.get_positions()
        pos = next(
            (p for p in positions if p.symbol == self.symbol and abs(p.position_amount) > 0),
            None,
        )
        if pos is None:
            return None

        entry = float(pos.entry_price)
        state = self._ladder_states.get(self.symbol)
        if state is None or state.entry != entry:
            state = _LadderState(
                stage=LadderStage.INITIAL, entry=entry,
                highest=entry, lowest=entry,
            )
            self._ladder_states[self.symbol] = state
        state.highest = max(state.highest, k.close)
        state.lowest = min(state.lowest, k.close)

        side = pos.position_side.value.upper()

        # hard stop (初始 1.5ATR / ExitLadderEngine 上移后的保本、TP1 价位)
        if state.stop is not None:
            hit = (side == "LONG" and k.close <= state.stop) or (
                side == "SHORT" and k.close >= state.stop
            )
            if hit:
                await self._reduce(k, side, pos.position_amount, k.close,
                                   reason=f"stop hit (level {state.stop:.2f})")
                state.stage = LadderStage.CLOSED
                return self._decision(
                    k, None, action="exit", qty=float(pos.position_amount),
                    ladder_stage=state.stage.value,
                    reason=f"stop hit @ {k.close:.2f} (level {state.stop:.2f})",
                )

        factors = await self._recent_factors()
        atr = self._atr(factors, k.close)
        gain = self._directional_gain(side, state.entry, k.close)
        gain_r = gain / (self.config.sl_atr_mult * atr) if atr > 0 else 0.0
        rows = await self._recent_klines()
        is_exhausted = self._ladder.check_volume_exhaustion(
            [r.volume for r in rows], [r.close for r in rows], gain_r, atr
        )

        next_stage, ratio, new_stop, ladder_reason = self._ladder.evaluate_position(
            side, state.entry, k.close, state.stage,
            state.highest, state.lowest, atr, is_exhausted,
        )
        state.stage = next_stage
        if new_stop is not None:
            state.stop = new_stop

        if ratio > 0:
            close_qty = abs(float(pos.position_amount)) * ratio
            await self._reduce(k, side, close_qty, k.close, reason=ladder_reason)
            return self._decision(
                k, None, action="reduce", qty=close_qty,
                ladder_stage=state.stage.value, reason=ladder_reason,
            )
        return self._decision(
            k, None, action="hold", ladder_stage=state.stage.value,
            reason=ladder_reason,
        )

    async def _reduce(
        self, k: Kline, side: str, qty: float, price: float, reason: str
    ) -> None:
        """reduce-only 出单 — 不经 PreTradeRiskGate (出场永不被挡)."""
        if qty <= 0:
            return
        assert self.executor is not None
        if side == "LONG":
            order_side, position_side = OrderSide.SELL, PositionSide.LONG
        else:
            order_side, position_side = OrderSide.BUY, PositionSide.SHORT
        result = await self.executor.place_order(
            self.symbol, order_side, OrderType.MARKET, qty,
            price=None, position_side=position_side, reduce_only=True,
        )
        await self._record_order(k, result)
        logger.info(
            f"[RuleLoop] {self.symbol} EXIT {side} {qty:.6f} @ {price:.2f}: {reason}",
            tag="RuleEngine",
        )

    # ------------------------------------------------------------------
    # 仓位计算
    # ------------------------------------------------------------------

    async def _size_position(
        self, entry: float, signal: RuleSignal, regime: Regime, atr: float
    ) -> float:
        balance = await self._get_equity()
        sl, tp = self._structure_prices(signal.direction, entry, atr)
        qty = calculate_atr_position_size(
            account_equity=balance,
            confidence=signal.strength,
            entry_price=entry,
            stop_loss_price=sl,
            take_profit_price=tp,
            atr_30m=atr,
            max_single_notional=self.config.max_single_notional,
        )
        if regime == Regime.NEUTRAL:
            qty *= self.config.neutral_risk_scale
        return float(qty)

    # ------------------------------------------------------------------
    # RuleDecision 构造
    # ------------------------------------------------------------------

    def _decision(
        self,
        k: Kline,
        regime: Optional[Regime],
        signal: Optional[RuleSignal] = None,
        action: str = "hold",
        blocked_by: Optional[str] = None,
        qty: float = 0.0,
        ladder_stage: Optional[str] = None,
        reason: str = "",
    ) -> RuleDecision:
        return RuleDecision(
            symbol=self.symbol,
            bar_open_time=k.open_time,
            bar_close=k.close,
            regime=regime.value if regime else None,
            signal=signal,
            direction=signal.direction if signal else "FLAT",
            qty=float(qty),
            action=action,
            blocked_by=blocked_by,
            ladder_stage=ladder_stage,
            reason=reason,
        )