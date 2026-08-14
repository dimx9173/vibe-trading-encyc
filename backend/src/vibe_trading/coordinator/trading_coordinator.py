"""
交易协调器

负责协调所有 Agent 的工作流，实现完整的交易决策流程。
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from pi_logger import get_logger, info, success, separator

from vibe_trading.config.agent_config import AgentRole, AgentTeamConfig
from vibe_trading.config.settings import get_settings
from vibe_trading.agents.agent_factory import ToolContext
from vibe_trading.agents.analysts.technical_analyst import create_technical_analyst
from vibe_trading.agents.analysts.base_analyst import create_analyst
from vibe_trading.agents.researchers.researcher_agents import (
    BullResearcherAgent,
    BearResearcherAgent,
    ResearchManagerAgent,
    run_debate_round,
)
from vibe_trading.agents.risk_mgmt.risk_agents import (
    run_risk_debate,
    create_risk_analyst,
)
from vibe_trading.agents.decision.decision_agents import (
    create_trader,
    create_portfolio_manager,
)
from vibe_trading.agents.decision.trading_tools import TradingPlan
from vibe_trading.memory.hybrid_memory import HybridMemory
from vibe_trading.data_sources.kline_storage import KlineStorage
from vibe_trading.data_sources.checkpoint_storage import DecisionCheckpointStore

# 改进工具导入
from vibe_trading.coordinator.state_machine import (
    DecisionStateMachine,
    DecisionState,
    get_state_machine_manager,
)
from vibe_trading.agents.messaging import (
    get_message_broker,
    MessageType,
)
from vibe_trading.coordinator.parallel_executor import get_parallel_executor
from vibe_trading.data_sources.rate_limiter import get_multi_endpoint_limiter
from vibe_trading.data_sources.cache import get_global_cache
from vibe_trading.agents.token_optimizer import get_token_optimizer
from vibe_trading.config.logging_config import PerformanceLogger

from vibe_trading.coordinator.state_propagator import (
    StatePropagator,
    EnhancedDecisionContext,
)
from vibe_trading.coordinator.signal_processor import (
    SignalProcessor,
    TradingSignal,
)
from vibe_trading.coordinator.quality_tracker import (
    get_quality_tracker,
)
from vibe_trading.memory.reflection import (
    TradeReflector,
    compute_return_pct,
    reflect_on_matured_snapshot,
)
from vibe_trading.memory.decision_snapshots import (
    DecisionSnapshot,
    DecisionSnapshotStore,
    interval_to_ms,
)
from vibe_trading.execution.order_executor import OrderExecutor, PaperOrderExecutor
from vibe_trading.execution.order_audit import ExecutionAuditStorage
from vibe_trading.execution.pre_trade_risk import PreTradeRiskGate, RiskPolicy

logger = logging.getLogger(__name__)
log = get_logger("TradingCoordinator")

# ========== 執行對帳 helper (VBT B6) ==========
_VALID_ORDER_STATUSES = ("FILLED", "SUBMITTED", "PENDING", "NEW", "PARTIALLY_FILLED")


def _has_valid_order(
    orders: list,
    cycle_start: Optional[Any] = None,
) -> bool:
    """對帳判定: 只有有效訂單 (FILLED/SUBMITTED/PENDING 等) 才算 has_order.

    B6 修復: 舊邏輯 `bool(orders)` 把 REJECTED_BY_RISK 的記錄也算 has_order,
    導致 PM approved 無單時保險安全網被誤判「已有訂單」而癱瘓。
    """
    if not orders:
        return False
    for o in orders:
        status = str(o.get("status", ""))
        if status in _VALID_ORDER_STATUSES:
            if cycle_start is not None:
                created = str(o.get("created_at", ""))
                if created and created >= cycle_start.isoformat():
                    return True
                continue
            return True
    return False


def _insurance_on_cooldown(
    last_insurance_at: Optional[float],
    cooldown_s: float,
    now_ts: Optional[float] = None,
) -> bool:
    """保險 cooldown 判定: 上次觸發距今 < cooldown_s 則阻擋重送 (防 04:07 6 秒 3 連砲)."""
    import time as _time

    now = now_ts if now_ts is not None else _time.time()
    if last_insurance_at is None:
        return False
    return (now - last_insurance_at) < cooldown_s


@dataclass
class TradingContext:
    """交易上下文"""
    symbol: str
    interval: str
    current_price: float
    klines: list
    indicators: dict
    market_data: dict
    timestamp: int


@dataclass
class TradingDecision:
    """交易决策结果"""
    symbol: str
    timestamp: int
    decision: str  # STRONG BUY/BUY/WEAK BUY/HOLD/WEAK SELL/SELL/STRONG SELL
    rationale: str
    confidence: Optional[float] = None  # 0-1，PM 決策信心（Fix 2026-08-09）
    execution_instructions: Optional[dict] = None
    agent_outputs: dict = field(default_factory=dict)


class TradingCoordinator:
    """
    交易协调器

    协调所有 Agent 的协作流程，实现完整的交易决策。
    """

    def __init__(
        self,
        symbol: str,
        interval: str = "30m",
        storage: Optional[KlineStorage] = None,
        memory: Optional[HybridMemory] = None,
        agent_config: Optional[AgentTeamConfig] = None,
        executor: Optional[OrderExecutor] = None,
        enable_streaming: bool = True,
    ):
        self.symbol = symbol
        self.interval = interval
        self.storage = storage
        self.memory = memory
        self.agent_config = agent_config or AgentTeamConfig()
        self.executor = executor or PaperOrderExecutor()
        self.enable_streaming = enable_streaming
        # 决策级反思快照队列（仅在启用记忆时工作）
        self._snapshot_store: Optional[DecisionSnapshotStore] = (
            DecisionSnapshotStore() if self.memory is not None else None
        )
        
        # Checkpoint storage for crash recovery
        self._checkpoint_store = DecisionCheckpointStore()

        # 工具上下文
        self._tool_context = ToolContext(
            symbol=symbol,
            interval=interval,
            storage=storage,
            executor=self.executor,
        )
        self._tool_context.risk_gate = PreTradeRiskGate(self.executor, RiskPolicy.from_settings())
        self._tool_context.order_audit = ExecutionAuditStorage()

        # Agents
        self._analysts: Dict[str, Any] = {}
        self._researchers: Dict[str, Any] = {}
        self._risk_analysts: Dict[str, Any] = {}
        self._trader: Optional[Any] = None
        self._portfolio_manager: Optional[Any] = None

        # Agent调用锁（防止并发调用冲突）
        self._agent_locks: Dict[str, asyncio.Lock] = {}

        # 决策历史
        self._decision_history: List[TradingDecision] = []

        # 决策树数据
        self._decision_tree = {
            "root": None,
            "current_phase": None,
            "start_time": None,
        }

        # ========== 改进工具初始化 ==========
        # 状态机管理器
        self._state_manager = get_state_machine_manager()
        self._current_state_machine: Optional[DecisionStateMachine] = None

        # 消息代理
        self._message_broker = get_message_broker()
        self._current_correlation_id: Optional[str] = None

        # 并行执行器
        self._parallel_executor = get_parallel_executor()

        # API限流器
        self._rate_limiter = get_multi_endpoint_limiter()

        # 缓存
        self._cache = get_global_cache()

        # Token优化器
        self._token_optimizer = get_token_optimizer()

        # 性能日志
        self._perf_log = PerformanceLogger("TradingCoordinator")

        # 状态传播器
        self._state_propagator = StatePropagator()
        self._enhanced_context: Optional[EnhancedDecisionContext] = None

        # 信号处理器
        self._signal_processor = SignalProcessor()

        # 质量跟踪器
        self._quality_tracker = get_quality_tracker()

        # 反思器
        self._reflector: Optional[TradeReflector] = None

        logger.info(f"TradingCoordinator initialized for {symbol} {interval}")

        # PHASE_6 SWDD: serialize cycles to prevent agent state leak
        self._cycle_lock: asyncio.Lock = asyncio.Lock()

    async def _update_decision_tree(
        self,
        phase: str,
        status: str = "running",
        agents: Optional[List[dict]] = None,
        content: Optional[str] = None,
        decision: Optional[str] = None,
    ):
        """更新决策树数据并推送到Web UI"""
        from datetime import datetime

        if not self._decision_tree["root"]:
            self._decision_tree["start_time"] = datetime.now().isoformat()
            self._decision_tree["root"] = {
                "label": f"{self.symbol} 新K线到达",
                "phase": "root",
                "status": "running",
                "children": [],
            }

        # 查找或创建当前阶段节点
        def find_or_create_phase(node, phase_name):
            if node.get("phase") == phase_name:
                return node
            if "children" in node:
                for child in node["children"]:
                    result = find_or_create_phase(child, phase_name)
                    if result:
                        return result
            return None

        # 构建阶段节点
        phase_node = {
            "label": self._get_phase_label(phase),
            "phase": phase,
            "status": status,
        }

        if agents:
            phase_node["agents"] = agents
        if content:
            phase_node["content"] = content[:200] + "..." if len(content) > 200 else content
        if decision:
            phase_node["decision"] = decision

        # 更新或添加节点
        root = self._decision_tree["root"]
        existing = find_or_create_phase(root, phase)

        if existing:
            existing.update(phase_node)
        else:
            root["children"].append(phase_node)

        # 推送到Web UI
        try:
            from vibe_trading.web.server import send_decision_tree
            await send_decision_tree(self._decision_tree)
        except Exception:
            pass  # Web服务器未启动时忽略

    def _get_phase_label(self, phase: str) -> str:
        """获取阶段标签"""
        labels = {
            "analysts": "📊 Phase 1: 分析师团队",
            "researchers": "🎭 Phase 2: 研究员辩论",
            "risk": "⚠️ Phase 3: 风控评估",
            "trader": "📋 Phase 4: 执行规划",
            "pm": "🎯 最终决策",
        }
        return labels.get(phase, phase)

    async def initialize(self) -> None:
        """初始化所有 Agent"""
        await self._initialize_exchange_filters()

        # 控制 streaming output (replay mode can disable via --quiet)
        from vibe_trading.agents.agent_factory import StreamPrinter
        StreamPrinter.enabled = self.enable_streaming

        # 初始化分析师
        if self.agent_config.technical_analyst.enabled:
            self._analysts["technical"] = await create_technical_analyst(self._tool_context, enable_streaming=self.enable_streaming)

        if self.agent_config.fundamental_analyst.enabled:
            self._analysts["fundamental"] = await create_analyst(
                AgentRole.FUNDAMENTAL_ANALYST, self._tool_context, enable_streaming=self.enable_streaming
            )

        if self.agent_config.news_analyst.enabled:
            self._analysts["news"] = await create_analyst(
                AgentRole.NEWS_ANALYST, self._tool_context, enable_streaming=self.enable_streaming
            )

        if self.agent_config.sentiment_analyst.enabled:
            self._analysts["sentiment"] = await create_analyst(
                AgentRole.SENTIMENT_ANALYST, self._tool_context, enable_streaming=self.enable_streaming
            )

        # 初始化研究员
        if self.agent_config.bull_researcher.enabled:
            self._researchers["bull"] = BullResearcherAgent()
            await self._researchers["bull"].initialize(self._tool_context, enable_streaming=self.enable_streaming)

        if self.agent_config.bear_researcher.enabled:
            self._researchers["bear"] = BearResearcherAgent()
            await self._researchers["bear"].initialize(self._tool_context, enable_streaming=self.enable_streaming)

        if self.agent_config.research_manager.enabled:
            self._researchers["manager"] = ResearchManagerAgent()
            await self._researchers["manager"].initialize(self._tool_context)

        # 初始化风控
        if self.agent_config.aggressive_debator.enabled:
            self._risk_analysts["aggressive"] = await create_risk_analyst(
                AgentRole.AGGRESSIVE_DEBATOR, self._tool_context, enable_streaming=self.enable_streaming
            )

        if self.agent_config.neutral_debator.enabled:
            self._risk_analysts["neutral"] = await create_risk_analyst(
                AgentRole.NEUTRAL_DEBATOR, self._tool_context, enable_streaming=self.enable_streaming
            )

        if self.agent_config.conservative_debator.enabled:
            self._risk_analysts["conservative"] = await create_risk_analyst(
                AgentRole.CONSERVATIVE_DEBATOR, self._tool_context, enable_streaming=self.enable_streaming
            )

        # 初始化决策层
        if self.agent_config.trader.enabled:
            self._trader = await create_trader(self._tool_context, enable_streaming=self.enable_streaming)

        if self.agent_config.portfolio_manager.enabled:
            self._portfolio_manager = await create_portfolio_manager(
                self._tool_context, self.memory, enable_streaming=self.enable_streaming
            )

        logger.info(f"All agents initialized for {self.symbol}")

    async def _initialize_exchange_filters(self) -> None:
        """Load exchange filters from executors that support them."""
        loader = getattr(self.executor, "get_exchange_filter_validator", None)
        if not callable(loader):
            return
        try:
            self._tool_context.exchange_filter_validator = await loader()
        except Exception as exc:
            logger.warning(f"Failed to load exchange filters: {exc}")

    async def analyze_and_decide(
        self,
        current_price: float,
        account_balance: float = 10000.0,
        current_positions: Optional[List[Dict]] = None,
        bar_open_time_ms: Optional[int] = None,
    ) -> TradingDecision:
        """
        执行完整的分析和决策流程

        流程:
        1. 收集市场数据
        2. 分析师生成报告
        3. 研究员辩论
        4. 风控评估
        5. 交易员制定方案
        6. 投资组合经理最终决策
        """
        async with self._cycle_lock:
            # Defensive: clear pi_agent_core state leak from previous failed cycle
            self._reset_agent_states()
            start_time = datetime.now()
            decision_id = f"{self.symbol}_{int(start_time.timestamp() * 1000)}"

            # ========== 决策级反思：回看此前已成熟的决策快照 ==========
            await self._reflect_on_matured_decisions(current_price, bar_open_time_ms)

            # Fix ②-fix (2026-08-10): 記錄本次 cycle 開始時間，供 audit 回填/保險只認本 cycle 訂單
            # （避免跨 run 污染：replay 多次跑同一 bar 時 trace_id 相同，會誤用上一 run 的舊 order）
            self._cycle_started_at = start_time

            # ========== 改进工具: 状态机初始化 ==========
            self._current_state_machine = self._state_manager.create_machine(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval
            )
            self._current_correlation_id = decision_id

            log.step(f"开始分析 {self.symbol} @ ${current_price:.2f}")
            logger.info(f"[状态机] 创建决策: {decision_id}")

            # 转换到ANALYZING状态
            self._current_state_machine.transition_to(DecisionState.ANALYZING, "开始分析师阶段")
            logger.info("[状态机] PENDING -> ANALYZING")

            # 准备上下文
            context = await self._prepare_context(current_price)
            current_positions = current_positions or []

            # 存储所有 Agent 输出
            agent_outputs = {}

            # 统计信息
            stats = {
                "cache_hits": 0,
                "cache_misses": 0,
                "api_calls": 0,
                "messages_sent": 0,
            }

            # Phase 1: 分析师生成报告
            info("Phase 1: 分析师生成报告...", tag="Analysts")

            # 更新决策树 - 阶段开始
            await self._update_decision_tree("analysts", "running")

            # ========== 改进工具: 并行执行 + 消息记录 + 性能日志 ==========
            import time
            phase_start = time.time()
            analyst_reports = await self._run_analysts_parallel(context, decision_id, stats)
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 1 (分析师) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["analysts"] = analyst_reports

            # 构建Agent状态列表
            agent_statuses = [
                {"name": role, "status": "completed"}
                for role in analyst_reports.keys()
            ]

            # 更新决策树 - 阶段完成
            await self._update_decision_tree("analysts", "completed", agents=agent_statuses)
            # 推送报告到 Web
            try:
                from vibe_trading.web.server import send_report
                for role, report in analyst_reports.items():
                    await send_report(
                        role,
                        report,
                        "analysts",
                        open_time_ms=bar_open_time_ms,
                        symbol=self.symbol,
                        interval=self.interval,
                    )
            except Exception:
                pass  # Web 未启用时忽略

            log.done("分析师报告完成")
            
            # Save checkpoint after Phase 1
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="analyzing",
                context={
                    "analyst_reports": analyst_reports,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )

            # 打印分析师报告
            for role, report in analyst_reports.items():
                print(f"\n[{role.upper()} REPORT]")
                separator("=", 60)
                print(report[:500] + "..." if len(report) > 500 else report)
                separator()
            log.done("分析师报告完成")

            # Phase 2: 研究员辩论
            info("Phase 2: 研究员辩论...", tag="Researchers")

            # ========== 改进工具: 状态机转换 ==========
            self._current_state_machine.transition_to(DecisionState.DEBATING, "开始研究员辩论")
            logger.info("[状态机] ANALYZING -> DEBATING")

            # 更新决策树 - 阶段开始
            await self._update_decision_tree("researchers", "running")

            import time
            phase_start = time.time()
            investment_plan = await self._run_research_debate(context, analyst_reports, decision_id, stats)
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 2 (研究员) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["investment_plan"] = investment_plan

            # 更新决策树 - 阶段完成
            await self._update_decision_tree(
                "researchers",
                "completed",
                content=investment_plan[:500] if len(investment_plan) > 500 else investment_plan
            )

            # 推送投资计划到 Web
            try:
                from vibe_trading.web.server import send_report
                await send_report(
                    "Research Manager",
                    investment_plan,
                    "researchers",
                    open_time_ms=bar_open_time_ms,
                    symbol=self.symbol,
                    interval=self.interval,
                )
            except Exception:
                pass

            # 打印投资计划
            print("\n[INVESTMENT PLAN]")
            separator("=", 60)
            print(investment_plan[:500] + "..." if len(investment_plan) > 500 else investment_plan)
            separator()
            log.done("研究员辩论完成")
            
            # Save checkpoint after Phase 2
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="debating",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )

            # Phase 3: 风控评估
            info("Phase 3: 风控评估...", tag="Risk")

            # ========== 改进工具: 状态机转换 ==========
            self._current_state_machine.transition_to(DecisionState.ASSESSING_RISK, "开始风控评估")
            logger.info("[状态机] DEBATING -> ASSESSING_RISK")

            # 更新决策树 - 阶段开始
            await self._update_decision_tree("risk", "running")

            import time
            phase_start = time.time()
            risk_assessment = await self._run_risk_assessment(
                investment_plan, current_positions, account_balance, decision_id, stats
            )
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 3 (风控) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["risk_assessment"] = risk_assessment

            # 更新决策树 - 阶段完成
            await self._update_decision_tree(
                "risk",
                "completed",
                agents=[
                    {"name": role, "status": "completed"}
                    for role in risk_assessment.keys() if role != "error"
                ]
            )

            # 推送风控报告到 Web
            try:
                from vibe_trading.web.server import send_report
                for role, assessment in risk_assessment.items():
                    if role != "error":
                        await send_report(
                            role.capitalize(),
                            assessment,
                            "risk",
                            open_time_ms=bar_open_time_ms,
                            symbol=self.symbol,
                            interval=self.interval,
                        )
            except Exception:
                pass

            # 打印风控评估
            print("\n[RISK ASSESSMENT]")
            separator("=", 60)
            for role, assessment in risk_assessment.items():
                if role != "error":
                    print(f"[{role}]: {assessment[:200]}..." if len(assessment) > 200 else f"[{role}]: {assessment}")
            log.done("风控评估完成")
            
            # Save checkpoint after Phase 3
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="assessing_risk",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "risk_assessment": risk_assessment,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )

            # Phase 4: 交易员制定方案
            info("Phase 4: 交易员制定方案...", tag="Trader")

            # ========== 改进工具: 状态机转换 ==========
            self._current_state_machine.transition_to(DecisionState.PLANNING, "开始执行规划")
            logger.info("[状态机] ASSESSING_RISK -> PLANNING")

            # 更新决策树 - 阶段开始
            await self._update_decision_tree("trader", "running")

            import time
            phase_start = time.time()
            trading_plan = await self._run_trader(
                investment_plan, risk_assessment, context, account_balance
            )
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 4 (交易员) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["trading_plan"] = trading_plan

            # 转换为字符串用于显示
            trading_plan_str = str(trading_plan)
            trading_plan_display = trading_plan_str[:500] + "..." if len(trading_plan_str) > 500 else trading_plan_str

            # 更新决策树 - 阶段完成
            await self._update_decision_tree(
                "trader",
                "completed",
                content=trading_plan_display
            )

            # 推送交易方案到 Web
            try:
                from vibe_trading.web.server import send_report
                await send_report(
                    "Trader",
                    trading_plan_display,
                    "trader",
                    open_time_ms=bar_open_time_ms,
                    symbol=self.symbol,
                    interval=self.interval,
                )
            except Exception:
                pass

            # 打印交易方案
            print("\n[TRADING PLAN]")
            separator("=", 60)
            print(trading_plan_display)
            log.done("交易方案制定完成")
            
            # Save checkpoint after Phase 4
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="planning",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "risk_assessment": risk_assessment,
                    "trading_plan": trading_plan,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )

            # Phase 5: 投资组合经理最终决策
            info("Phase 5: 投资组合经理最终决策...", tag="PM")

            # ========== 改进工具: 状态机转换 ==========
            self._current_state_machine.transition_to(DecisionState.COMPLETED, "决策完成")
            logger.info("[状态机] PLANNING -> COMPLETED")

            # 更新决策树 - 阶段开始
            await self._update_decision_tree("pm", "running")

            import time
            phase_start = time.time()
            self._tool_context.current_bar_open_time_ms = bar_open_time_ms
            self._tool_context.current_trace_id = f"{self.symbol}:{self.interval}:{bar_open_time_ms or int(time.time() * 1000)}"
            final_decision = await self._run_portfolio_manager(
                analyst_reports,
                investment_plan,
                trading_plan,
                risk_assessment,
                current_positions,
                account_balance,
                context,
            )
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 5 (投资组合经理) 耗时: {phase_elapsed:.2f}s")

            # 更新决策树 - 最终决策
            await self._update_decision_tree(
                "pm",
                "completed",
                decision=final_decision.get("decision", "HOLD"),
                content=final_decision.get("rationale", "")[:300]
            )

            # 推送最终决策到 Web
            try:
                from vibe_trading.web.server import send_report
                decision_text = f"决策: {final_decision.get('decision', 'HOLD')}\n\n理由:\n{final_decision.get('rationale', '')}"
                await send_report(
                    "Portfolio Manager",
                    decision_text,
                    "pm",
                    open_time_ms=bar_open_time_ms,
                    symbol=self.symbol,
                    interval=self.interval,
                )
            except Exception:
                pass

            # 打印最终决策
            print("\n[FINAL DECISION]")
            separator("=", 60)
            print(f"决策: {final_decision.get('decision', 'HOLD')}")
            print(f"\n理由:\n{final_decision.get('rationale', '')}")
            separator()
            log.done("投资组合经理决策完成")
            
            # Save checkpoint after Phase 5 (final)
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="completed",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "risk_assessment": risk_assessment,
                    "trading_plan": trading_plan,
                    "final_decision": final_decision,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )

            # 创建决策结果
            decision = TradingDecision(
                symbol=self.symbol,
                timestamp=int(datetime.now().timestamp() * 1000),
                decision=final_decision.get("decision", "HOLD"),
                rationale=final_decision.get("rationale", ""),
                confidence=final_decision.get("confidence"),
                execution_instructions=final_decision.get("execution_instructions"),
                agent_outputs=agent_outputs,
            )

            self._decision_history.append(decision)

            # ========== P0 & P1 改进: 信号处理和质量跟踪 ==========
            # 1. 提取结构化信号
            processed_signal = self._signal_processor.process_signal(
                decision_text=final_decision.get("rationale", ""),
                agent_name="Portfolio Manager",
            )

            logger.info(f"[信号处理] 提取信号: {processed_signal.signal.value} "
                       f"(置信度: {processed_signal.confidence:.2f}, 强度: {processed_signal.strength.value})")

            # ========== 一致性防護：PM 明確聲明 vs 全文掃描（Fix C 重寫） ==========
            # parse_decision 優先回傳明確欄位，若欄位存在則恆等 — 必須用
            # 「不含欄位短路的全文掃描」比對，才能抓到欄位-missing 時的誤判。
            try:
                from vibe_trading.tools.signal_parser import _parse_field, _scan_full, to_signal_enum
                rationale = final_decision.get("rationale", "")
                declared = _parse_field(rationale)
                if declared:
                    declared_enum = to_signal_enum(declared)
                    recorded_enum = processed_signal.signal.value
                    if declared_enum != recorded_enum:
                        logger.warning(
                            f"[一致性] PM 明確聲明 {declared!r} ({declared_enum}) "
                            f"但 parse 記錄 {recorded_enum} — 決策記錄可能不正確！"
                        )
                else:
                    # 無明確欄位 → 檢查全文掃描結果與記錄是否一致
                    full = to_signal_enum(_scan_full(rationale))
                    if full != processed_signal.signal.value:
                        logger.warning(
                            f"[一致性] 無明確欄位，全文掃描={full} 但記錄="
                            f"{processed_signal.signal.value} — 可能漏判！"
                        )
            except Exception as _e:
                logger.warning(f"[一致性] 檢查失敗: {_e}")

            # 2. 计算Agent贡献度
            # 转换 trading_plan 为字符串（可能是 TradingPlan 对象）
            trading_plan_str = str(trading_plan) if trading_plan else ""
            agent_contributions = self._calculate_agent_contributions(
                analyst_reports, investment_plan, trading_plan_str, risk_assessment
            )

            # 3. 确定市场状态
            market_condition = self._determine_market_condition(context)

            # 4. 记录决策到质量跟踪器
            await self._quality_tracker.record_decision(
                decision_id=decision_id,
                symbol=self.symbol,
                signal=processed_signal,
                agent_contributions=agent_contributions,
                market_condition=market_condition,
                interval=self.interval,
                bar_open_time_ms=bar_open_time_ms,
            )

            logger.info(f"[质量跟踪] 决策已记录: {decision_id}")

            # ========== 執行對帳 + 保險（Fix B 安全網升級）：決策=BUY/SELL 但該 bar 無訂單 → coordinator 自動執行 ==========
            # 下單優先路徑是 PM agent 呼叫 submit_trade_order tool；若 LLM 漏呼叫，
            # coordinator 保險在 code 層補執行（避免「PM 說買但靜默沒單」）。
            # 查詢 key 用 current_trace_id（與 submit_trade_order 記錄一致），
            # 避免 decision_id 格式不同導致誤報。
            try:
                # Fix ③ (2026-08-09 SWDA P1): 保險只在 PM 明確 BUY/SELL（非 WEAK）時觸發。
                # processed_signal.signal.value 是 to_signal_enum 收斂結果（WEAK_BUY→BUY），
                # 用原始 decision.decision（parse_decision 保留 WEAK）判斷，避免 WEAK BUY 誤觸發保險暴衝。
                pm_decision = getattr(decision, "decision", "HOLD")
                trade_decision = pm_decision in ("BUY", "SELL", "STRONG BUY", "STRONG SELL")
                if trade_decision and self._tool_context.order_audit is not None:
                    trace_id = self._tool_context.current_trace_id or decision_id
                    trace = await self._tool_context.order_audit.get_trace(trace_id)
                    # Fix ②-fix (2026-08-10): 只認本 cycle 的訂單 — audit DB 共用，
                    # 不同 run 同一 bar 的 trace_id 相同，舊 run 訂單會誤判「已有訂單」而跳過保險。
                    orders = (trace or {}).get("orders", []) or []
                    cycle_start = getattr(self, "_cycle_started_at", None)
                    if cycle_start is not None:
                        orders = [
                            o for o in orders
                            if o.get("created_at", "") >= cycle_start.isoformat()
                        ]
                    # Fix B6 (2026-08-13 SWDA): 只認有效訂單 (FILLED/SUBMITTED/PENDING 等)。
                    # 舊邏輯 bool(orders) 把 REJECTED_BY_RISK 記錄也算 has_order,
                    # 導致 approved 無單時保險安全網被誤判「已有訂單」而癱瘓。
                    has_order = _has_valid_order(orders)
                    # Fix B6b (2026-08-13 SWDA): 保險 cooldown — 防 04:07 式
                    # 6 秒 3 連砲 (每次 rejected 都再觸發保險重送)。
                    if not has_order and _insurance_on_cooldown(
                        getattr(self, "_last_insurance_at", None),
                        getattr(self, "_insurance_cooldown_s", 300.0),
                    ):
                        logger.warning(
                            f"[執行對帳] 保險 cooldown 中 (上次 {getattr(self, '_last_insurance_at', None)}), "
                            f"跳過自動執行 decision={decision_id}"
                        )
                    elif not has_order:
                        logger.warning(
                            f"[執行對帳] 決策={processed_signal.signal.value} 但 trace_id={trace_id} "
                            f"無任何有效訂單 — PM agent 可能漏呼叫 submit_trade_order tool，啟動 coordinator 保險..."
                        )
                        import time as _time

                        self._last_insurance_at = _time.time()
                        await self._auto_execute_insurance(
                            decision_id=decision_id,
                            signal_value=processed_signal.signal.value,
                            trading_plan=trading_plan,
                        )
            except Exception as _e:
                logger.warning(f"[執行對帳] 檢查失敗: {_e}")

            # 5. 保存决策ID和信号供后续反思使用
            self._last_decision_id = decision_id
            self._last_processed_signal = processed_signal
            self._last_analyst_reports = analyst_reports
            self._last_decision_context = {
                "market_condition": market_condition,
                "final_decision": final_decision,
                "investment_plan": investment_plan,
                "risk_assessment": risk_assessment,
            }

            # 6. 记录决策快照（含 HOLD），供 N 根 bar 后回看评估
            if self._snapshot_store is not None:
                benchmark_price_at_decision = await self._fetch_benchmark_price()
                self._snapshot_store.record(
                    DecisionSnapshot(
                        decision_id=decision_id,
                        symbol=self.symbol,
                        decision=decision.decision,
                        price_at_decision=current_price,
                        bar_open_time_ms=bar_open_time_ms or int(start_time.timestamp() * 1000),
                        benchmark_price_at_decision=benchmark_price_at_decision,
                        confidence=getattr(processed_signal, "confidence", 0.0),
                        context_digest=market_condition,
                    )
                )

            elapsed = (datetime.now() - start_time).total_seconds()
            success(f"分析完成: {decision.decision} (耗时 {elapsed:.2f}s)", tag="Coordinator")

            # ========== 改进工具: 统计信息输出 ==========
            self._log_improvements_stats(elapsed, stats)

            return decision
    def _reset_agent_states(self) -> None:
        """Defensive reset for pi_agent_core state leak (PHASE_5 SYNTHESIS spec).

        TradingCoordinator stores agents in dicts (self._analysts etc.) plus
        a few individual attributes (_trader, _portfolio_manager).
        """
        for agents_dict in (self._analysts, self._researchers, self._risk_analysts):
            for wrapper in agents_dict.values():
                inner = getattr(wrapper, "_agent", None)
                if inner is None:
                    continue
                try:
                    inner.reset()
                except Exception:
                    try:
                        inner._state.is_streaming = False
                    except Exception:
                        pass
        for attr in ("_trader", "_portfolio_manager"):
            wrapper = getattr(self, attr, None)
            if wrapper is None:
                continue
            inner = getattr(wrapper, "_agent", None)
            if inner is None:
                continue
            try:
                inner.reset()
            except Exception:
                try:
                    inner._state.is_streaming = False
                except Exception:
                    pass

    def _log_improvements_stats(self, elapsed: float, stats: dict) -> None:
        """输出改进工具统计信息"""
        logger.info("=" * 60)
        logger.info("📊 [改进工具效果统计]")

        # 状态机摘要
        state_summary = self._current_state_machine.get_state_summary()
        logger.info(f"  📊 [状态机] 决策ID: {state_summary['decision_id']}")
        logger.info(f"     状态转换数: {len(state_summary['state_history'])}")

        # 消息统计
        msg_stats = self._message_broker.get_statistics()
        logger.info(f"  📨 [消息] 总消息数: {msg_stats['total_messages']}")

        # 缓存统计
        cache_stats = self._cache.get_stats()
        memory_stats = cache_stats.get('memory', {})
        hit_rate = memory_stats.get('hit_rate', 0)
        logger.info(f"  💾 [缓存] 命中率: {hit_rate:.1%}, 大小: {memory_stats.get('size', 0)}")

        # API限流统计
        limiter = self._rate_limiter.get_limiter("binance_rest")
        remaining = limiter.get_remaining_requests()
        logger.info(f"  🚦 [限流] 剩余令牌: {remaining}/分钟")

        # Token统计
        token_stats = self._token_optimizer.get_stats()
        logger.info(f"  🤖 [Token] 总消耗: {token_stats.get('total_tokens', 0)}")

        # 性能日志摘要
        logger.info(f"  ⏱  [性能] 总耗时: {elapsed:.2f}s")
        logger.info("=" * 60)

    async def _prepare_context(self, current_price: float) -> TradingContext:
        """准备交易上下文"""
        # 获取 K线数据
        klines = []
        if self.storage:
            from vibe_trading.data_sources.kline_storage import KlineQuery
            query = KlineQuery(symbol=self.symbol, interval=self.interval, limit=100)
            klines = await self.storage.query_klines(query)

        # 获取技术指标
        indicators = {}
        if klines:
            closes = [k.close for k in klines]
            highs = [k.high for k in klines]
            lows = [k.low for k in klines]
            opens = [k.open for k in klines]
            volumes = [k.volume for k in klines]

            from vibe_trading.data_sources.technical_indicators import TechnicalIndicators
            ti = TechnicalIndicators()
            ti.load_data(opens, highs, lows, closes, volumes)
            indicators_data = ti.get_latest_indicators()
            indicators = {
                # 趋势指标
                "sma_20": indicators_data.sma_20,
                "sma_50": indicators_data.sma_50,
                # 动量指标
                "rsi": indicators_data.rsi,
                "macd": indicators_data.macd,
                "macd_signal": indicators_data.macd_signal,
                "macd_histogram": indicators_data.macd_hist,
                # 波动率指标
                "bollinger_upper": indicators_data.bollinger_upper,
                "bollinger_middle": indicators_data.bollinger_middle,
                "bollinger_lower": indicators_data.bollinger_lower,
                "atr": indicators_data.atr,
                # 成交量指标
                "volume_sma": indicators_data.volume_sma,
                # 当前价格（方便计算）
                "current_price": closes[-1] if closes else None,
                "current_volume": volumes[-1] if volumes else None,
            }

        return TradingContext(
            symbol=self.symbol,
            interval=self.interval,
            current_price=current_price,
            klines=klines,
            indicators=indicators,
            market_data={},
            timestamp=int(datetime.now().timestamp() * 1000),
        )

    async def _run_analysts(self, context: TradingContext) -> Dict[str, str]:
        """运行分析师团队 (串行版本，保留兼容性)"""
        return await self._run_analysts_parallel(context, "default", {})

    async def _run_analysts_parallel(self, context: TradingContext, correlation_id: str, stats: dict) -> Dict[str, str]:
        """运行分析师团队 (并行执行版本)"""
        reports = {}

        # 使用并行执行器运行分析师
        analyst_list = []
        for role, analyst in self._analysts.items():
            if hasattr(analyst, 'analyze') or hasattr(analyst, 'analyze_with_indicators'):
                analyst_list.append((role, analyst))

        if not analyst_list:
            return reports

        # ========== 改进工具: 并行执行 ==========
        logger.info(f"🚀 [并行执行] 启动 {len(analyst_list)} 个分析师...")

        import time
        start_time = time.time()

        # 创建分析任务
        async def run_analyst_task(role: str, analyst):
            try:
                # 获取或创建Agent锁
                if role not in self._agent_locks:
                    self._agent_locks[role] = asyncio.Lock()

                # 使用锁保护Agent调用（防止并发冲突）
                async with self._agent_locks[role]:
                    if role == "technical" and hasattr(analyst, 'analyze_with_indicators'):
                        market_data = {
                            "symbol": context.symbol,
                            "interval": context.interval,
                            "current_price": context.current_price,
                            "indicators": context.indicators,
                        }
                        result = await analyst.analyze_with_indicators(market_data)
                    else:
                        data = await self._get_analyst_data(role, context, stats)
                        result = await analyst.analyze(data)

                # ========== 改进工具: 消息记录 ==========
                self._message_broker.send(
                    sender=f"{role}_analyst",
                    receiver="coordinator",
                    message_type=MessageType.ANALYSIS_REPORT,
                    content={"role": role, "report": result},
                    correlation_id=correlation_id,
                )
                stats["messages_sent"] += 1

                return role, result, None
            except Exception as e:
                logger.warning(f"Error running {role} analyst: {e}")
                return role, f"{role} analysis unavailable: {str(e)}", str(e)

        # 并行执行所有分析师
        tasks = [run_analyst_task(role, analyst) for role, analyst in analyst_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start_time

        # 处理结果
        successful = 0
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Analyst task failed: {result}")
                continue
            role, report, error = result
            reports[role] = report
            if not error:
                successful += 1
            logger.info(f"  ✅ {role}: 完成")

        # 计算加速比 (假设串行执行时间 = 并行时间 * Agent数量)
        if len(analyst_list) > 1:
            estimated_serial_time = elapsed * len(analyst_list)
            speedup = estimated_serial_time / elapsed if elapsed > 0 else 1
            logger.info(f"⚡ [性能] 并行加速比: {speedup:.1f}x, 总耗时: {elapsed:.1f}s")

        return reports

    async def _get_analyst_data(self, role: str, context: TradingContext, stats: dict) -> dict:
        """获取分析师所需的数据 (带缓存和限流)"""
        from vibe_trading.tools.fundamental_tools import (
            get_funding_rates,
            get_long_short_ratio,
            get_open_interest,
        )
        from vibe_trading.tools.sentiment_tools import (
            get_fear_and_greed_index,
            get_social_sentiment,
            get_news_sentiment,
        )

        data = {
            "symbol": context.symbol,
            "current_price": context.current_price,
            "timestamp": context.timestamp,
        }

        # ========== 改进工具: 缓存装饰器 (通过检查缓存键) ==========
        cache_key = f"{role}_data_{context.symbol}_{context.timestamp}"
        cached_data = await self._cache.get(cache_key)
        if cached_data is not None:
            stats["cache_hits"] += 1
            return cached_data
        stats["cache_misses"] += 1

        if role == "fundamental":
            # ========== 改进工具: API限流 ==========
            await self._rate_limiter.acquire("binance_rest", tokens=1)
            stats["api_calls"] += 1

            funding = await get_funding_rates(context.symbol)

            await self._rate_limiter.acquire("binance_rest", tokens=1)
            stats["api_calls"] += 1
            long_short = await get_long_short_ratio(context.symbol)

            await self._rate_limiter.acquire("binance_rest", tokens=1)
            stats["api_calls"] += 1
            open_interest = await get_open_interest(context.symbol)

            data["funding_rate"] = funding
            data["long_short_ratio"] = long_short
            data["open_interest"] = open_interest

        elif role == "news":
            await self._rate_limiter.acquire("crypto_compare", tokens=1)
            stats["api_calls"] += 1
            news_data = await get_news_sentiment(context.symbol, limit=15)
            data["news"] = news_data

        elif role == "sentiment":
            await self._rate_limiter.acquire("alternative_me", tokens=1)
            stats["api_calls"] += 1
            fear_greed = await get_fear_and_greed_index()

            await self._rate_limiter.acquire("binance_rest", tokens=1)
            stats["api_calls"] += 1
            social = await get_social_sentiment(context.symbol)

            await self._rate_limiter.acquire("binance_rest", tokens=1)
            stats["api_calls"] += 1
            funding = await get_funding_rates(context.symbol)

            data["fear_greed"] = fear_greed
            data["social_sentiment"] = social
            data["funding_rate"] = funding

        # 缓存结果 (TTL 60秒)
        await self._cache.set(cache_key, data, ttl=60)

        return data

    async def _run_research_debate(
        self, context: TradingContext, analyst_reports: Dict[str, str], correlation_id: str, stats: dict
    ) -> str:
        """运行研究员辩论"""
        if "manager" not in self._researchers:
            return "No investment plan (research manager not enabled)"

        settings = get_settings()
        
        # Fix 3: skip_debate option — 跳過 debate，直接 risk → trader（debug/測試用）
        if settings.skip_debate:
            logger.info("[Fix 3] skip_debate=True, 跳過 debate phase")
            # 用分析師報告組成簡單 investment plan
            simple_plan = "Research debate SKIPPED (skip_debate=True). Direct to risk phase.\n\n"
            for role, report in analyst_reports.items():
                simple_plan += f"{role.upper()}:\n{report[:500]}...\n\n"
            return simple_plan

        # 准备上下文
        context_str = f"Symbol: {context.symbol}\nPrice: {context.current_price}\n"
        for role, report in analyst_reports.items():
            context_str += f"\n{role.upper()} Report:\n{report}\n"

        # ========== 改进工具: Token优化 ==========
        # 压缩分析师报告以减少Token使用
        compressed_context = self._token_optimizer.compress_prompt(context_str, target_ratio=0.8)

        # 运行辩论
        bull_history = ""
        bear_history = ""

        for round_num in range(settings.debate_rounds):
            logger.info(f"Research debate round {round_num + 1}")
            bull_resp, bear_resp = await run_debate_round(
                self._researchers.get("bull"),
                self._researchers.get("bear"),
                compressed_context,
                bull_history,
                bear_history,
            )
            bull_history += f"\n{bull_resp}"
            bear_history += f"\n{bear_resp}"

            # ========== 改进工具: 消息记录 ==========
            self._message_broker.send(
                sender="bull_researcher",
                receiver="coordinator",
                message_type=MessageType.DEBATE_SPEECH,
                content={"round": round_num + 1, "speech": bull_resp},
                correlation_id=correlation_id,
            )
            self._message_broker.send(
                sender="bear_researcher",
                receiver="coordinator",
                message_type=MessageType.DEBATE_SPEECH,
                content={"round": round_num + 1, "speech": bear_resp},
                correlation_id=correlation_id,
            )
            stats["messages_sent"] += 2

        # 研究经理裁决
        result = await self._researchers["manager"].make_decision(
            context=compressed_context,
            bull_agent=self._researchers.get("bull"),
            bear_agent=self._researchers.get("bear"),
            bull_history=bull_history,
            bear_history=bear_history,
            analyst_reports=analyst_reports,
            market_data=context.market_data,
        )

        # ========== 改进工具: 消息记录 ==========
        self._message_broker.send(
            sender="research_manager",
            receiver="coordinator",
            message_type=MessageType.INVESTMENT_ADVICE,
            content={"decision": result},
            correlation_id=correlation_id,
        )
        stats["messages_sent"] += 1

        # 返回决策文本
        return result.get("decision_text", "No decision made")

    async def _run_risk_assessment(
        self, investment_plan: str, current_positions: List[Dict], account_balance: float, correlation_id: str, stats: dict
    ) -> Dict[str, str]:
        """运行风控评估"""
        if not self._risk_analysts:
            return {"error": "No risk analysts enabled"}

        results = await run_risk_debate(
            self._risk_analysts.get("aggressive"),
            self._risk_analysts.get("neutral"),
            self._risk_analysts.get("conservative"),
            investment_plan,
            current_positions,
            account_balance,
            rounds=1,
        )

        # ========== 改进工具: 消息记录 ==========
        for role, assessment in results.items():
            if role != "error":
                self._message_broker.send(
                    sender=f"{role}_analyst",
                    receiver="coordinator",
                    message_type=MessageType.RISK_ASSESSMENT,
                    content={"role": role, "assessment": assessment},
                    correlation_id=correlation_id,
                )
                stats["messages_sent"] += 1

        return results

    async def _run_trader(
        self, investment_plan: str, risk_assessment: Dict, context: TradingContext, account_balance: float
    ) -> TradingPlan:
        """运行交易员"""
        if not self._trader:
            return "No trading plan (trader not enabled)"

        # 从投资计划中提取方向
        direction = "HOLD"  # 默认
        plan_lower = investment_plan.lower()

        if "做多" in plan_lower or "long" in plan_lower or "买入" in plan_lower or "看涨" in plan_lower:
            direction = "LONG"
        elif "做空" in plan_lower or "short" in plan_lower or "卖出" in plan_lower or "看跌" in plan_lower:
            direction = "SHORT"
        elif "观望" in plan_lower or "hold" in plan_lower:
            direction = "HOLD"

        return await self._trader.create_trading_plan(
            direction=direction,
            investment_recommendation=investment_plan,
            risk_assessment=risk_assessment,
            current_price=context.current_price,
            account_balance=account_balance,
        )

    async def _run_portfolio_manager(
        self,
        analyst_reports: Dict[str, str],
        investment_plan: str,
        trading_plan: str,
        risk_assessment: Dict[str, str],
        current_positions: List[Dict],
        account_balance: float,
        context: TradingContext,
    ) -> Dict[str, Any]:
        """运行投资组合经理"""
        if not self._portfolio_manager:
            return {"decision": "HOLD", "rationale": "Portfolio manager not enabled"}

        pm_response = await self._portfolio_manager.make_final_decision(
            analyst_reports=analyst_reports,
            investment_plan=investment_plan,
            trading_plan=trading_plan,
            risk_debate=risk_assessment,
            current_positions=current_positions,
            account_balance=account_balance,
            current_price=context.current_price,
        )

        # 从响应中提取决策文本
        decision_text = pm_response.get("decision_text", "") if isinstance(pm_response, dict) else str(pm_response)

        # Fix 2026-08-09: 從 scorecard 帶出 confidence（原本丟失）
        pm_confidence = None
        if isinstance(pm_response, dict):
            scorecard = pm_response.get("scorecard")
            if scorecard is not None:
                pm_confidence = getattr(scorecard, "confidence", None)

        # 解析决策文本 — 走共享 parser，与 signal_processor 保持一致
        from vibe_trading.tools.signal_parser import parse_decision
        decision = parse_decision(decision_text)

        # Fix ② (2026-08-09 SWDA P0): 決策 UNKNOWN/HOLD 但 audit 已顯示成交訂單 → 回填實際執行。
        # bar 2 案例：PM 在 45s timeout 前已 submit_trade_order 成交（FILLED），
        # 但 timeout 切斷決策輸出 → 記錄 UNKNOWN 卻實際有倉。
        # 這裡用訂單 rationale 提取 PM 原決策（如 WEAK BUY），找不到再 fallback 到 side。
        if decision in ("UNKNOWN", "HOLD") or not decision_text.strip():
            fallback = await self._decision_fallback_from_audit()
            if fallback:
                logger.warning(
                    f"[決策回填] 決策={decision!r} 但 audit 有成交訂單，回填為 "
                    f"{fallback['decision']!r} (order_id={fallback['order_id']})"
                )
                decision_text = fallback["text"]
                decision = fallback["decision"]

        return {
            "decision": decision,
            "rationale": decision_text,
            "confidence": pm_confidence,
            "execution_instructions": None,  # 可以从 decision_text 中解析
        }

    async def _decision_fallback_from_audit(self) -> Optional[Dict[str, Any]]:
        """audit 已成交訂單存在但決策 UNKNOWN/HOLD 時，依實際執行回填。

        Returns:
            {"decision": str, "text": str, "order_id": str} 或 None（無成交訂單）。
        """
        try:
            audit = getattr(self._tool_context, "order_audit", None)
            trace_id = getattr(self._tool_context, "current_trace_id", None)
            if not audit or not trace_id:
                return None
            trace = await audit.get_trace(trace_id)
            orders = trace.get("orders", []) or []
            # Fix ②-fix (2026-08-10): 只認本 cycle 產生的訂單 — audit DB 是共用的，
            # 不同 replay run 同一 bar 的 trace_id 相同，會誤用上一 run 的舊 order。
            cycle_start = getattr(self, "_cycle_started_at", None)
            if cycle_start is not None:
                orders = [
                    o for o in orders
                    if o.get("created_at", "") >= cycle_start.isoformat()
                ]
            filled = [o for o in orders if o.get("status") == "FILLED"]
            if not filled:
                return None
            last = filled[-1]
            result = last.get("result") or {}
            rationale = result.get("rationale", "") or ""
            # 優先從訂單 rationale 提取 PM 原決策（如 WEAK BUY）
            from vibe_trading.tools.signal_parser import parse_decision
            parsed = parse_decision(rationale) if rationale else "UNKNOWN"
            if parsed in ("UNKNOWN", "HOLD"):
                side = str(last.get("side", "")).upper()
                parsed = "BUY" if side == "BUY" else ("SELL" if side == "SELL" else "HOLD")
            qty = last.get("quantity")
            oid = last.get("order_id")
            text = (
                f"Decision: {parsed}\n"
                f"Rationale: PM LLM timeout/決策缺失 — audit 顯示訂單已成交 "
                f"{qty} {self.symbol} (order_id={oid})，決策由實際執行回填。"
            )
            return {"decision": parsed, "text": text, "order_id": oid}
        except Exception as e:
            logger.warning(f"[決策回填] audit 檢查失敗: {e}")
            return None

    def get_decision_history(self) -> List[TradingDecision]:
        """获取决策历史"""
        return self._decision_history.copy()

    async def _auto_execute_insurance(
        self,
        decision_id: str,
        signal_value: str,
        trading_plan: Optional[TradingPlan],
    ) -> Optional[dict]:
        """coordinator 層保險：PM 決策 BUY/SELL 但未呼叫 submit_trade_order tool 時自動執行。

        重用 submit_trade_order tool 的完整執行鏈（風控 → exchange filter → executor → audit），
        確保與 PM 主動呼叫走同一路徑、風控仍是最終把關。

        Returns:
            order details dict（含 status/order_id）；無法執行時回傳 None。
        """
        try:
            if trading_plan is None:
                logger.warning(f"[執行保險] trading_plan 為 None，無法自動執行 decision={decision_id}")
                return None

            entry_orders = getattr(trading_plan, "entry_orders", None) or []
            if not entry_orders:
                logger.warning(f"[執行保險] trading_plan 無 entry_orders，無法自動執行 decision={decision_id}")
                return None

            entry = entry_orders[0]
            order_type = str(entry.get("order_type", "market")).upper()

            # ===== VBT B1-B4 修復 (2026-08-13 SWDA): 改用 OrderBuilder 統一建構 =====
            # 舊邏輯 (Fix ④ 手工 cap + 未 floor stepSize + position_side 預設 BOTH
            # + reference_price 用原始 entry 而非 fallback) 造成 4 連拒。
            # OrderBuilder 保證 A1-A4: qty 對齊 step / reference_price 必填 /
            # hedge→LONG/SHORT / notional ≤ cap。
            reference_price = entry.get("price") or getattr(entry, "price", None)
            if not reference_price:
                # fallback: 用 executor 目前參考價（PaperOrderExecutor 已 update_price）
                try:
                    reference_price = self._tool_context.executor.get_reference_price(self.symbol)
                except Exception:
                    reference_price = None

            if not reference_price or float(reference_price) <= 0:
                logger.warning(
                    f"[執行保險] 無法取得 reference_price，跳過自動執行 decision={decision_id} "
                    f"(B2 修復: 不送無價單給風控)"
                )
                return None

            from vibe_trading.execution.order_builder import (
                OrderBuilder,
            )
            from vibe_trading.config.settings import get_settings as _get_settings

            _settings = _get_settings()
            from vibe_trading.data_sources.binance_client import OrderSide

            try:
                side = OrderSide(signal_value.upper())
            except ValueError:
                logger.warning(f"[執行保險] 無法解析 side={signal_value!r}，跳過自動執行 decision={decision_id}")
                return None

            try:
                builder = OrderBuilder(
                    reference_price=float(reference_price),
                    position_mode=_settings.execution_position_mode,
                    step_size=0.0001,
                    min_qty=0.0001,
                    min_notional=50.0,
                    notional_cap=_settings.execution_max_single_order_notional,
                )
                built = builder.build(
                    symbol=self.symbol,
                    side=side,
                    order_type=order_type,
                    price=entry.get("price") if order_type == "LIMIT" else None,
                    rationale=(
                        f"coordinator 保險自動執行（PM 未呼叫 submit_trade_order tool, "
                        f"decision={decision_id}）"
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"[執行保險] OrderBuilder 建構失敗 decision={decision_id}: {e} "
                    f"(B1/B4 修復: 參數不合法不送單)"
                )
                return None

            stop_price = None
            stop_loss_orders = getattr(trading_plan, "stop_loss_orders", None) or []
            if stop_loss_orders:
                stop_price = stop_loss_orders[0].get("trigger_price")

            from vibe_trading.agents.agent_tools import (
                create_submit_trade_order_tool,
                SubmitTradeOrderParams,
            )

            params = SubmitTradeOrderParams(
                symbol=built.symbol,
                side=built.side.value,
                order_type=built.order_type,
                quantity=built.quantity,
                position_side=built.position_side.value,
                price=built.price,
                reference_price=built.reference_price,
                stop_price=stop_price or built.stop_price,
                reduce_only=False,
                rationale=built.rationale,
            )

            tool = create_submit_trade_order_tool(self._tool_context)
            result = await tool.execute(f"insurance_{decision_id}", params)
            details = getattr(result, "details", None) or {}
            status = details.get("status", "UNKNOWN")
            logger.info(
                f"[執行保險] 自動執行完成 decision={decision_id} status={status} "
                f"order_id={details.get('order_id')}"
            )
            return details
        except Exception as e:
            logger.warning(f"[執行保險] 自動執行失敗 decision={decision_id}: {e}", exc_info=True)
            return None

    async def on_new_kline(self, kline) -> None:
        """
        处理新 K线数据

        当新的 K线数据到达时被调用，触发完整的分析和决策流程。
        """
        try:
            logger.info(f"New {kline.symbol} {kline.interval} kline received: close={kline.close}")

            # 执行分析和决策
            decision = await self.analyze_and_decide(
                current_price=kline.close,
                account_balance=10000.0,  # TODO: 从实际账户获取
                current_positions=[],  # TODO: 从实际持仓获取
            )

            # 记录决策
            logger.info(f"Decision for {kline.symbol}: {decision.decision}")
            if self.memory and decision.decision != "HOLD":
                # 存储到记忆系统（add_memory 为同步接口）
                self.memory.add_memory(
                    situation=f"{kline.symbol} price {kline.close}, {decision.rationale}",
                    advice=decision.decision,
                    outcome="pending",  # 实际收益在后续反思中更新
                    pnl=None,
                )

        except Exception as e:
            logger.error(f"Error in on_new_kline: {e}", exc_info=True)

    # ========== P0 & P1 改进功能集成 ==========
    async def on_trade_completed(
        self,
        entry_price: float,
        exit_price: float,
        position_size: float,
        hold_duration_hours: float = 1.0,
    ) -> None:
        """
        交易完成后调用

        执行反思和质量评估
        """
        if not hasattr(self, '_last_decision_id') or not self._last_decision_id:
            logger.warning("没有可反思的决策", tag="Reflection")
            return

        logger.info(
            f"交易完成: 入场 ${entry_price:.2f} → 出场 ${exit_price:.2f} "
           f"(PnL: {(exit_price - entry_price) * position_size:.2f})",
            tag="Reflection"
        )

        # 初始化反思器
        if not self._reflector and self.memory:
            self._reflector = TradeReflector(memory=self.memory)

        # ========== 执行反思 ==========
        if self._reflector:
            try:
                from vibe_trading.memory.reflection import TradeResult

                trade_result = TradeResult(
                    symbol=self.symbol,
                    decision=self._last_processed_signal.signal.value,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    position_size=position_size,
                    pnl=(exit_price - entry_price) * position_size
                        if self._last_processed_signal.signal == TradingSignal.BUY
                        else (entry_price - exit_price) * position_size,
                    pnl_percentage=((exit_price - entry_price) / entry_price) * 100
                        if self._last_processed_signal.signal == TradingSignal.BUY
                        else ((entry_price - exit_price) / entry_price) * 100,
                    hold_duration_hours=hold_duration_hours,
                    market_condition=self._determine_market_condition(
                        await self._prepare_context(exit_price)
                    ),
                )

                # 获取所有Agent报告（从agent_outputs）
                all_reports = {}
                if hasattr(self, '_last_agent_outputs'):
                    all_reports = self._last_agent_outputs

                # 执行反思
                reflections = await self._reflector.reflect_on_trade(
                    trade_result=trade_result,
                    agent_reports=all_reports,
                    decision_context={
                        "decision_id": self._last_decision_id,
                        "signal": self._last_processed_signal.signal.value,
                        "confidence": self._last_processed_signal.confidence,
                    },
                )

                logger.info(
                    f"反思完成: 生成了 {len(reflections)} 条反思",
                    tag="Reflection"
                )

                # 持久化反思记忆，跨会话保留
                if hasattr(self.memory, "save"):
                    try:
                        self.memory.save()
                    except Exception as save_err:
                        logger.warning(f"反思记忆保存失败: {save_err}", tag="Memory")

            except Exception as e:
                logger.error(f"反思失败: {e}", tag="Reflection")

        # ========== 记录交易结果到质量评估 ==========
        try:
            await self._quality_tracker.record_outcome(
                decision_id=self._last_decision_id,
                entry_price=entry_price,
                exit_price=exit_price,
                position_size=position_size,
                hold_duration_hours=hold_duration_hours,
            )

            logger.info(
                "质量评估: 交易结果已记录",
                tag="QualityTracker"
            )

        except Exception as e:
            logger.error(f"质量评估失败: {e}", tag="QualityTracker")

    # ========== 决策级反思（P0.1 C4）==========

    def _maturation_window_ms(self) -> int:
        """成熟窗口 = maturation_bars * 单根 bar 时长。"""
        settings = get_settings()
        return settings.reflection_maturation_bars * interval_to_ms(self.interval)

    def _get_reflector(self) -> Optional[TradeReflector]:
        if not self.memory:
            return None
        if self._reflector is None:
            self._reflector = TradeReflector(memory=self.memory)
        return self._reflector

    async def _fetch_benchmark_price(self) -> Optional[float]:
        """
        尽力获取基准（默认 BTC）当前价格。

        反思时再用快照记录的基准入场价和当前价格计算收益率。
        """
        settings = get_settings()
        benchmark = settings.reflection_benchmark_symbol
        if benchmark == self.symbol:
            return None  # 与本币种相同，无 alpha 意义
        try:
            from vibe_trading.tools.market_data_tools import get_current_price

            data = await get_current_price(benchmark, storage=self.storage)
            if isinstance(data, dict):
                price = data.get("price")
                return float(price) if price is not None else None
        except Exception as exc:
            logger.warning(
                f"获取基准({benchmark})价格失败，alpha 将缺失: {exc}",
                tag="Reflection",
            )
        return None

    async def _reflect_on_matured_decisions(
        self, current_price: float, current_bar_open_time_ms: Optional[int]
    ) -> None:
        """回看此前已成熟的决策快照（含 HOLD），生成反思并写入记忆。"""
        if self._snapshot_store is None or self.memory is None:
            return

        matured = self._snapshot_store.get_matured(
            current_bar_open_time_ms, self._maturation_window_ms()
        )
        if not matured:
            return

        reflector = self._get_reflector()
        if reflector is None:
            return

        benchmark_price = await self._fetch_benchmark_price()

        reflected = 0
        for snap in matured:
            try:
                benchmark_return = compute_return_pct(
                    snap.benchmark_price_at_decision, benchmark_price
                )
                await reflect_on_matured_snapshot(
                    reflector=reflector,
                    snapshot=snap,
                    exit_price=current_price,
                    benchmark_return=benchmark_return,
                )
                self._snapshot_store.discard(snap.decision_id)
                reflected += 1
            except Exception as exc:
                logger.warning(
                    f"决策快照反思失败 {snap.decision_id}: {exc}", tag="Reflection"
                )

        if reflected:
            try:
                self.memory.save()
            except Exception as exc:
                logger.warning(f"反思记忆保存失败: {exc}", tag="Memory")
        logger.info(
            f"决策级反思: 回看 {len(matured)} 条，成功 {reflected} 条",
            tag="Reflection",
        )

    def _determine_market_condition(self, context: TradingContext) -> str:
        """判断市场状态"""
        # 简化版判断逻辑
        if hasattr(context, 'indicators'):
            indicators = context.indicators
            # 检查趋势
            if indicators.get('trend') == 'uptrend':
                return "trending"
            elif indicators.get('volatility', 0) > 0.02:
                return "volatile"
        return "ranging"

    def _calculate_agent_contributions(
        self,
        analyst_reports: Dict[str, str],
        investment_plan: str,
        trading_plan: str,
        risk_assessment: Dict[str, str],
    ) -> Dict[str, float]:
        """
        计算各Agent的贡献度

        基于报告长度、关键词匹配等因素计算
        """
        contributions = {}

        # 分析师贡献（基于报告长度和质量）
        total_length = sum(len(r) for r in analyst_reports.values())
        if total_length > 0:
            for name, report in analyst_reports.items():
                contributions[name] = len(report) / total_length * 0.4

        # 研究员贡献（基于投资决策采纳度）
        investment_keywords = ["buy", "sell", "long", "short", "做多", "做空"]
        investment_str = str(investment_plan) if investment_plan else ""
        investment_lower = investment_str.lower()
        for keyword in investment_keywords:
            if keyword in investment_lower:
                contributions["Research Manager"] = contributions.get("Research Manager", 0) + 0.3
                break

        # 交易员贡献
        trader_keywords = ["execution", "entry", "exit", "order"]
        trader_str = str(trading_plan) if trading_plan else ""
        trader_lower = trader_str.lower()
        for keyword in trader_keywords:
            if keyword in trader_lower:
                contributions["Trader"] = contributions.get("Trader", 0) + 0.3
                break

        # 归一化
        total = sum(contributions.values())
        if total > 0:
            contributions = {k: v/total for k, v in contributions.items()}

        return contributions

    async def get_quality_report(self) -> str:
        """获取质量评估报告"""
        try:
            await self._quality_tracker.get_quality_metrics(force_refresh=True)
            return self._quality_tracker.generate_report()
        except Exception as e:
            return f"无法生成质量报告: {e}"

    async def get_agent_rankings(self) -> List[Tuple[str, float]]:
        """获取Agent排名"""
        try:
            return self._quality_tracker.get_agent_ranking()
        except Exception as e:
            logger.error(f"获取Agent排名失败: {e}", tag="QualityTracker")
            return []

    async def get_top_performers(self, top_n: int = 3) -> List[str]:
        """获取表现最好的Agent"""
        try:
            return self._quality_tracker.get_top_performers(top_n=top_n)
        except Exception as e:
            logger.error(f"获取最佳Agent失败: {e}", tag="QualityTracker")
            return []

    async def get_underperformers(self, threshold: float = 0.4) -> List[str]:
        """获取表现不佳的Agent"""
        try:
            return self._quality_tracker.get_underperformers(threshold=threshold)
        except Exception as e:
            logger.error(f"获取不佳Agent失败: {e}", tag="QualityTracker")
            return []

    async def resume_from_checkpoint(
        self,
        decision_id: str,
        current_price: float,
        account_balance: float = 10000.0,
        current_positions: Optional[List[Dict]] = None,
        bar_open_time_ms: Optional[int] = None,
    ) -> Optional[TradingDecision]:
        """从 checkpoint 恢复决策流程
        
        Args:
            decision_id: 要恢复的决策 ID
            current_price: 当前价格
            account_balance: 账户余额
            current_positions: 当前持仓
            bar_open_time_ms: K线开盘时间
            
        Returns:
            TradingDecision 如果恢复成功，否则 None
        """
        checkpoint = self._checkpoint_store.get_latest_checkpoint(decision_id)
        if not checkpoint:
            logger.warning(f"No checkpoint found for decision_id: {decision_id}")
            return None
        
        completed_phase = checkpoint["completed_phase"]
        context = checkpoint["context"]
        
        logger.info(f"Resuming from checkpoint: decision_id={decision_id}, completed_phase={completed_phase}")
        
        # 根据完成的阶段决定从哪个阶段继续
        if completed_phase == "completed":
            # 已完成，直接返回结果
            logger.info(f"Decision {decision_id} already completed")
            return self._reconstruct_decision_from_checkpoint(context)
        
        # 设置状态机
        self._current_state_machine = self._state_manager.create_machine(
            decision_id=decision_id,
            symbol=self.symbol,
            interval=self.interval
        )
        self._current_correlation_id = decision_id
        
        # 恢复上下文
        analyst_reports = context.get("analyst_reports", {})
        investment_plan = context.get("investment_plan")
        risk_assessment = context.get("risk_assessment")
        trading_plan = context.get("trading_plan")
        
        # 根据完成阶段设置状态机
        if completed_phase == "analyzing":
            self._current_state_machine.transition_to(DecisionState.ANALYZING, "Resumed from checkpoint")
        elif completed_phase == "debating":
            self._current_state_machine.transition_to(DecisionState.DEBATING, "Resumed from checkpoint")
        elif completed_phase == "assessing_risk":
            self._current_state_machine.transition_to(DecisionState.ASSESSING_RISK, "Resumed from checkpoint")
        elif completed_phase == "planning":
            self._current_state_machine.transition_to(DecisionState.PLANNING, "Resumed from checkpoint")
        
        # 继续执行未完成的阶段
        try:
            return await self._continue_from_checkpoint(
                completed_phase=completed_phase,
                analyst_reports=analyst_reports,
                investment_plan=investment_plan,
                risk_assessment=risk_assessment,
                trading_plan=trading_plan,
                current_price=current_price,
                account_balance=account_balance,
                current_positions=current_positions or [],
                bar_open_time_ms=bar_open_time_ms,
                decision_id=decision_id,
            )
        except Exception as e:
            logger.error(f"Failed to resume from checkpoint: {e}", exc_info=True)
            return None
    
    async def _continue_from_checkpoint(
        self,
        completed_phase: str,
        analyst_reports: Dict,
        investment_plan: Optional[str],
        risk_assessment: Optional[Dict],
        trading_plan: Optional[Any],
        current_price: float,
        account_balance: float,
        current_positions: List[Dict],
        bar_open_time_ms: Optional[int],
        decision_id: str,
    ) -> TradingDecision:
        """从指定阶段继续执行"""
        import time
        stats = {"cache_hits": 0, "cache_misses": 0, "api_calls": 0, "messages_sent": 0}
        agent_outputs = {}
        context = await self._prepare_context(current_price)
        
        # Phase 2: 研究员辩论（如果 Phase 1 已完成）
        if completed_phase == "analyzing" and investment_plan is None:
            info("Phase 2: 研究员辩论...", tag="Researchers")
            self._current_state_machine.transition_to(DecisionState.DEBATING, "Continuing from checkpoint")
            phase_start = time.time()
            investment_plan = await self._run_research_debate(context, analyst_reports, decision_id, stats)
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 2 (研究员) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["investment_plan"] = investment_plan
            
            # 保存 checkpoint
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="debating",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )
        
        # Phase 3: 风控评估（如果 Phase 2 已完成）
        if completed_phase in ["analyzing", "debating"] and risk_assessment is None:
            info("Phase 3: 风控评估...", tag="Risk")
            self._current_state_machine.transition_to(DecisionState.ASSESSING_RISK, "Continuing from checkpoint")
            phase_start = time.time()
            risk_assessment = await self._run_risk_assessment(
                investment_plan, current_positions, account_balance, decision_id, stats
            )
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 3 (风控) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["risk_assessment"] = risk_assessment
            
            # 保存 checkpoint
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="assessing_risk",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "risk_assessment": risk_assessment,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )
        
        # Phase 4: 交易员制定方案（如果 Phase 3 已完成）
        if completed_phase in ["analyzing", "debating", "assessing_risk"] and trading_plan is None:
            info("Phase 4: 交易员制定方案...", tag="Trader")
            self._current_state_machine.transition_to(DecisionState.PLANNING, "Continuing from checkpoint")
            phase_start = time.time()
            trading_plan = await self._run_trader(
                investment_plan, risk_assessment, context, account_balance
            )
            phase_elapsed = time.time() - phase_start
            logger.info(f"[性能] Phase 4 (交易员) 耗时: {phase_elapsed:.2f}s")
            agent_outputs["trading_plan"] = trading_plan
            
            # 保存 checkpoint
            self._checkpoint_store.save_checkpoint(
                decision_id=decision_id,
                symbol=self.symbol,
                interval=self.interval,
                completed_phase="planning",
                context={
                    "analyst_reports": analyst_reports,
                    "investment_plan": investment_plan,
                    "risk_assessment": risk_assessment,
                    "trading_plan": trading_plan,
                    "current_price": current_price,
                    "account_balance": account_balance,
                    "current_positions": current_positions,
                }
            )
        
        # Phase 5: 投资组合经理最终决策（如果 Phase 4 已完成）
        info("Phase 5: 投资组合经理最终决策...", tag="PM")
        self._current_state_machine.transition_to(DecisionState.COMPLETED, "Continuing from checkpoint")
        phase_start = time.time()
        self._tool_context.current_bar_open_time_ms = bar_open_time_ms
        self._tool_context.current_trace_id = f"{self.symbol}:{self.interval}:{bar_open_time_ms or int(time.time() * 1000)}"
        final_decision = await self._run_portfolio_manager(
            analyst_reports,
            investment_plan,
            trading_plan,
            risk_assessment,
            current_positions,
            account_balance,
            context,
        )
        phase_elapsed = time.time() - phase_start
        logger.info(f"[性能] Phase 5 (投资组合经理) 耗时: {phase_elapsed:.2f}s")
        
        # 保存最终 checkpoint
        self._checkpoint_store.save_checkpoint(
            decision_id=decision_id,
            symbol=self.symbol,
            interval=self.interval,
            completed_phase="completed",
            context={
                "analyst_reports": analyst_reports,
                "investment_plan": investment_plan,
                "risk_assessment": risk_assessment,
                "trading_plan": trading_plan,
                "final_decision": final_decision,
                "current_price": current_price,
                "account_balance": account_balance,
                "current_positions": current_positions,
            }
        )
        
        # 构建决策结果
        decision = TradingDecision(
            symbol=self.symbol,
            timestamp=int(datetime.now().timestamp() * 1000),
            decision=final_decision.get("decision", "HOLD"),
            rationale=final_decision.get("rationale", ""),
            confidence=final_decision.get("confidence"),
            execution_instructions=final_decision.get("execution_instructions"),
            agent_outputs=agent_outputs,
        )
        
        self._decision_history.append(decision)
        return decision
    
    def _reconstruct_decision_from_checkpoint(self, context: Dict) -> TradingDecision:
        """从 checkpoint context 重建 TradingDecision"""
        final_decision = context.get("final_decision", {})
        return TradingDecision(
            symbol=self.symbol,
            timestamp=int(datetime.now().timestamp() * 1000),
            decision=final_decision.get("decision", "HOLD"),
            rationale=final_decision.get("rationale", ""),
            confidence=final_decision.get("confidence"),
            execution_instructions=final_decision.get("execution_instructions"),
            agent_outputs={},
        )
    async def close(self) -> None:
        """关闭所有资源"""
        # 关闭所有Agent
        for agent in list(self._analysts.values()):
            if hasattr(agent, 'close'):
                await agent.close()

        for agent in list(self._researchers.values()):
            if hasattr(agent, 'close'):
                await agent.close()

        for agent in list(self._risk_analysts.values()):
            if hasattr(agent, 'close'):
                await agent.close()

        if self._trader and hasattr(self._trader, 'close'):
            await self._trader.close()

        if self._portfolio_manager and hasattr(self._portfolio_manager, 'close'):
            await self._portfolio_manager.close()

        logger.info("TradingCoordinator 已关闭")
