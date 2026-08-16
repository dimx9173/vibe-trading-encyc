"""
Pi Agent Core Tools 包装器

将现有的tools函数包装成pi_agent_core框架的AgentTool格式（pi-py v0.83 Protocol）。

pi-py 的 ``AgentTool`` 是一个 Protocol：类需提供 ``name`` / ``description`` /
``parameters``(JSON Schema dict) / ``label`` / ``execution_mode`` 以及
``async execute(self, tool_call_id, params, cancel_event, on_update) -> AgentToolResult``。

本项目沿用既有的 (Pydantic 参数类, 异步 execute 函数) 写法，通过下方 ``_PyTool``
适配器在运行时转换为 pi-py Protocol 工具。这样 24 个工具的业务逻辑零改动。
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Type
from pydantic import BaseModel, Field

from pi_agent_core import AgentToolResult
from pi_ai import TextContent

from vibe_trading.tools import market_data_tools, technical_tools, fundamental_tools, sentiment_tools

logger = logging.getLogger(__name__)


class _PyTool:
    """适配器：把 (Pydantic 参数类 + 异步 execute 函数) 包装为 pi-py AgentTool Protocol。

    pi-py 在 agent_loop 中会把 LLM 返回的 dict 参数传给 ``execute`` 的 ``params``。
    这里先用 Pydantic 类校验/解析，再委托给原 execute 函数（其签名仍为
    ``(name, args: <Pydantic>, extra, callback) -> AgentToolResult``）。
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: Type[BaseModel],
        execute: Callable[..., Awaitable[AgentToolResult]],
        label: str = "",
    ) -> None:
        self.name = name
        self.label = label or name
        self.description = description
        # JSON Schema dict（pi-py 期望 dict，不是 Pydantic 类）
        self.parameters = parameters.model_json_schema()
        self.execution_mode = None
        self._params_cls = parameters
        self._execute_fn = execute

    async def execute(
        self,
        tool_call_id: str,
        params: Any,
        cancel_event: Optional[asyncio.Event] = None,
        on_update: Optional[Callable[[AgentToolResult], None]] = None,
    ) -> AgentToolResult:
        # params 来自 LLM（dict）；用 Pydantic 类做校验与默认值填充
        if isinstance(params, dict):
            args = self._params_cls(**params)
        elif isinstance(params, self._params_cls):
            args = params
        else:
            # 兜底：尝试强制构造，让 Pydantic 报错
            args = self._params_cls.model_validate(params)
        # 原 execute 签名：(name, args, extra, callback)
        return await self._execute_fn(self.name, args, None, on_update)


# 兼容别名：调用点仍可写 AgentTool(...)，实际构造 _PyTool。
# （pi-py 的 AgentTool 是 Protocol，不能直接实例化。）
AgentTool = _PyTool


# =============================================================================
# 参数模型定义
# =============================================================================

class GetCurrentPriceParams(BaseModel):
    """获取当前价格参数"""
    symbol: str = Field(description="交易对符号，如BTCUSDT")


class Get24hrTickerParams(BaseModel):
    """获取24小时ticker参数"""
    symbol: str = Field(description="交易对符号")


class GetFundingRateParams(BaseModel):
    """获取资金费率参数"""
    symbol: str = Field(description="交易对符号")


class GetLongShortRatioParams(BaseModel):
    """获取多空比参数"""
    symbol: str = Field(description="交易对符号")


class GetOpenInterestParams(BaseModel):
    """获取持仓量参数"""
    symbol: str = Field(description="交易对符号")


class GetFearAndGreedParams(BaseModel):
    """获取恐惧贪婪指数参数"""
    pass


class GetNewsSentimentParams(BaseModel):
    """获取新闻情绪参数"""
    symbol: str = Field(description="交易对符号")
    limit: int = Field(default=15, description="获取数量")


class GetOrderBookParams(BaseModel):
    """获取订单簿参数"""
    symbol: str = Field(description="交易对符号")
    limit: int = Field(default=20, description="深度级别")


class GetSocialSentimentParams(BaseModel):
    """获取社交媒体情绪参数"""
    symbol: str = Field(description="交易对符号")


class GetTakerBuySellRatioParams(BaseModel):
    """获取买卖比例参数"""
    symbol: str = Field(description="交易对符号")


class GetTopTraderLongShortRatioParams(BaseModel):
    """获取大户多空比参数"""
    symbol: str = Field(description="交易对符号")


class GetLiquidationOrdersParams(BaseModel):
    """获取清算订单参数"""
    symbol: Optional[str] = Field(default=None, description="交易对符号，不填则获取全部")


class GetTrendingSymbolsParams(BaseModel):
    """获取热门交易对参数"""
    pass


class GetComprehensiveSentimentParams(BaseModel):
    """获取综合情绪参数"""
    symbol: str = Field(description="交易对符号")


# =============================================================================
# 技术分析工具参数模型
# =============================================================================

class GetTechnicalIndicatorsParams(BaseModel):
    """获取技术指标参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class GetKlineDataParams(BaseModel):
    """获取K线数据参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")
    limit: int = Field(default=100, description="获取数量")


class ComposeFactorParams(BaseModel):
    """组合因子参数 (Phase 2.2 StackVM)"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")
    formula: list = Field(description="因子公式 AST, 如 [\"GATE\", \"vol_cluster\", \"momentum\", 0.0]")


class GetComprehensiveTechnicalAnalysisParams(BaseModel):
    """获取综合技术分析参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class AnalyzeTrendParams(BaseModel):
    """分析趋势参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class DetectSupportResistanceParams(BaseModel):
    """检测支撑阻力参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class CalculatePivotsParams(BaseModel):
    """计算枢轴点参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class DetectCandlestickPatternsParams(BaseModel):
    """检测K线形态参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class DetectDivergenceParams(BaseModel):
    """检测背离参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class AnalyzeVolumePatternsParams(BaseModel):
    """分析成交量模式参数"""
    symbol: str = Field(description="交易对符号")
    interval: str = Field(default="30m", description="K线间隔")


class SubmitTradeOrderParams(BaseModel):
    """提交交易订单参数"""
    symbol: str = Field(description="交易对符号，如 BTCUSDT")
    side: str = Field(description="订单方向：BUY 或 SELL")
    order_type: str = Field(default="MARKET", description="订单类型：MARKET、LIMIT、STOP_MARKET、TAKE_PROFIT_MARKET")
    quantity: float = Field(gt=0, description="下单数量，币本位数量，例如 BTC 数量")
    position_side: str = Field(default="BOTH", description="持仓方向：BOTH、LONG 或 SHORT")
    price: Optional[float] = Field(default=None, description="限价单价格；市价单不填")
    reference_price: Optional[float] = Field(default=None, description="市价单风控估值价格；用于下单前名义价值检查")
    stop_price: Optional[float] = Field(default=None, description="止损/止盈触发价格")
    reduce_only: bool = Field(default=False, description="是否只减仓；平仓时应设置为 true")
    rationale: str = Field(default="", description="Portfolio Manager 对本次下单的最终理由")


# =============================================================================
# 执行函数
# =============================================================================

async def execute_get_current_price(
    name: str,
    args: GetCurrentPriceParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取当前价格"""
    result = await market_data_tools.get_current_price(args.symbol)
    return AgentToolResult(
        content=[TextContent(text=f"当前价格: {result.get('price', 'N/A')}")]
    )


async def execute_get_24hr_ticker(
    name: str,
    args: Get24hrTickerParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取24小时ticker"""
    result = await market_data_tools.get_24hr_ticker(args.symbol)
    pct = result.get('price_change_percent', 'N/A')
    vol = result.get('volume', 'N/A')
    text = f"24h价格变化: {pct}%, 成交量: {vol}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_funding_rate(
    name: str,
    args: GetFundingRateParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取资金费率"""
    result = await market_data_tools.get_funding_rate(args.symbol)
    rate = result.get('funding_rate', 'N/A')
    mark = result.get('mark_price', 'N/A')
    text = f"资金费率: {rate}, 标记价格: {mark}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_long_short_ratio(
    name: str,
    args: GetLongShortRatioParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取多空比"""
    result = await fundamental_tools.get_long_short_ratio(args.symbol)
    ratio = result.get('long_short_ratio', 'N/A')
    text = f"多空比: {ratio}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_open_interest(
    name: str,
    args: GetOpenInterestParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取持仓量"""
    result = await market_data_tools.get_open_interest(args.symbol)
    oi = result.get('open_interest', 'N/A')
    text = f"持仓量: {oi}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_fear_and_greed(
    name: str,
    args: GetFearAndGreedParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取恐惧贪婪指数"""
    result = await sentiment_tools.get_fear_and_greed_index()
    val = result.get('value', 'N/A')
    cls = result.get('value_classification', 'N/A')
    text = f"恐惧贪婪指数: {val}, 分类: {cls}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_news_sentiment(
    name: str,
    args: GetNewsSentimentParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取新闻情绪"""
    result = await sentiment_tools.get_news_sentiment(args.symbol, limit=args.limit)
    news_items = result.get("news", [])[:3] if isinstance(result, dict) else []
    text = f"最新新闻 ({len(news_items)} 条):\n"
    for item in news_items:
        title = item.get("title", "N/A")[:80]
        text += f"  - {title}...\n"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_order_book(
    name: str,
    args: GetOrderBookParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取订单簿"""
    result = await market_data_tools.get_order_book(args.symbol, limit=args.limit)
    bids = result.get("bids", [])[:5]
    asks = result.get("asks", [])[:5]
    text = f"订单簿 ({args.symbol}):\n"
    text += "买盘:\n"
    for bid in bids:
        text += f"  {bid}\n"
    text += "卖盘:\n"
    for ask in asks:
        text += f"  {ask}\n"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_social_sentiment(
    name: str,
    args: GetSocialSentimentParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取社交媒体情绪"""
    result = await sentiment_tools.get_social_sentiment(args.symbol)
    score = result.get("sentiment_score", "N/A")
    mentions = result.get("mentions", {}).get("total", "N/A")
    text = f"社交媒体情绪评分: {score}, 提及次数: {mentions}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_taker_buy_sell_ratio(
    name: str,
    args: GetTakerBuySellRatioParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取主动买卖比例"""
    result = await fundamental_tools.get_taker_buy_sell_ratio(args.symbol)
    buy_ratio = result.get("buy_ratio", "N/A")
    sell_ratio = result.get("sell_ratio", "N/A")
    text = f"主动买盘比例: {buy_ratio}, 主动卖盘比例: {sell_ratio}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_top_trader_long_short_ratio(
    name: str,
    args: GetTopTraderLongShortRatioParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取大户多空比"""
    result = await fundamental_tools.get_top_trader_long_short_ratio(args.symbol)
    long_ratio = result.get("long_short_ratio", "N/A")
    text = f"大户多空比: {long_ratio}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_liquidation_orders(
    name: str,
    args: GetLiquidationOrdersParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取清算订单"""
    result = await fundamental_tools.get_liquidation_orders(args.symbol)
    orders = result.get("orders", [])[:5] if isinstance(result, dict) else []
    text = f"清算订单 ({len(orders)} 条):\n"
    for order in orders:
        text += f"  {order}\n"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_trending_symbols(
    name: str,
    args: GetTrendingSymbolsParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取热门交易对"""
    result = await sentiment_tools.get_trending_symbols()
    symbols = result.get("symbols", [])[:10] if isinstance(result, dict) else []
    text = f"热门交易对 ({len(symbols)} 个):\n"
    for symbol_info in symbols:
        text += f"  {symbol_info}\n"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_comprehensive_sentiment(
    name: str,
    args: GetComprehensiveSentimentParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取综合情绪分析"""
    result = await sentiment_tools.get_comprehensive_sentiment(args.symbol)
    score = result.get("overall_score", "N/A")
    signal = result.get("signal", "N/A")
    text = f"综合情绪评分: {score}, 信号: {signal}"
    return AgentToolResult(content=[TextContent(text=text)])


# =============================================================================
# 技术分析工具执行函数
# =============================================================================

async def execute_get_technical_indicators(
    name: str,
    args: GetTechnicalIndicatorsParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取技术指标"""
    result = await technical_tools.get_technical_indicators(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    indicators = result.get("indicators", {})
    text = f"""技术指标 ({args.symbol} {args.interval}):
RSI: {indicators.get('rsi', 'N/A')}
MACD: {indicators.get('macd', 'N/A')}
布林带: [{indicators.get('bollinger_lower', 'N/A')}, {indicators.get('bollinger_upper', 'N/A')}]
ATR: {indicators.get('atr', 'N/A')}"""
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_get_kline_data(
    name: str,
    args: GetKlineDataParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取K线数据"""
    result = await technical_tools.get_kline_data(args.symbol, args.interval, args.limit)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    klines = result.get("klines", [])
    text = f"K线数据: 共 {len(klines)} 条，最新: {klines[-1] if klines else 'N/A'}"
    return AgentToolResult(content=[TextContent(text=text)])


def create_compose_factor_tool(tool_context: Any) -> AgentTool:
    """Create a StackVM compose_factor tool bound to a ToolContext (Phase 2.2)."""

    async def execute_compose_factor(
        name: str,
        args: ComposeFactorParams,
        extra: Any = None,
        callback: Any = None,
    ) -> AgentToolResult:
        """执行组合因子 (Phase 2.2 StackVM).

        從 storage 讀 klines → 計算微觀因子 → StackVM 求值公式 AST.
        """
        import numpy as np

        from vibe_trading.factors.microstructure import compute_all
        from vibe_trading.factors.vm import evaluate_formula

        try:
            from vibe_trading.data_sources.kline_storage import KlineQuery

            storage = getattr(tool_context, "storage", None)
            if storage is None:
                return AgentToolResult(content=[TextContent(text="N/A (无 storage, compose_factor 需要本地数据)")])

            klines = await storage.query_klines(
                KlineQuery(symbol=args.symbol, interval=args.interval, limit=100)
            )
            if not klines:
                return AgentToolResult(content=[TextContent(text="N/A (无 K线数据)")])

            micro = compute_all(klines)
            # 標量微觀因子展開為序列 (供運算元操作)
            series = {k: np.full(100, v) for k, v in micro.items()}
            result = evaluate_formula(args.formula, series)
            if result is None:
                return AgentToolResult(content=[TextContent(
                    text=f"公式無效或序列缺失: {args.formula}\n可用因子: {list(micro.keys())}"
                )])
            return AgentToolResult(content=[TextContent(
                text=f"compose_factor: {args.formula}\nresult: {result:.6f}"
            )])
        except Exception as e:
            return AgentToolResult(content=[TextContent(text=f"compose_factor 錯誤: {e}")])

    return AgentTool(
        name="compose_factor",
        label="组合因子",
        description="通过 StackVM 组合自定义因子表达式 (Phase 2.2), 如 [\"GATE\", \"vol_cluster\", \"momentum\", 0.0]",
        parameters=ComposeFactorParams,
        execute=execute_compose_factor,
    )


async def execute_get_comprehensive_technical_analysis(
    name: str,
    args: GetComprehensiveTechnicalAnalysisParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行获取综合技术分析"""
    result = await technical_tools.get_comprehensive_technical_analysis(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    trend = result.get("trend", "N/A")
    signals = result.get("signals", [])
    text = f"趋势: {trend}\n信号: {', '.join(signals[:5])}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_analyze_trend(
    name: str,
    args: AnalyzeTrendParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行趋势分析"""
    result = await technical_tools.analyze_trend(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    trend = result.get("trend", "N/A")
    strength = result.get("strength", "N/A")
    text = f"趋势: {trend}, 强度: {strength}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_detect_support_resistance(
    name: str,
    args: DetectSupportResistanceParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行支撑阻力检测"""
    result = await technical_tools.detect_support_resistance(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    support = result.get("support_levels", [])
    resistance = result.get("resistance_levels", [])
    text = f"支撑位: {support[:3]}\n阻力位: {resistance[:3]}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_calculate_pivots(
    name: str,
    args: CalculatePivotsParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行枢轴点计算"""
    result = await technical_tools.calculate_pivots(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    pivots = result.get("pivots", {})
    text = f"枢轴点: {pivots}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_detect_candlestick_patterns(
    name: str,
    args: DetectCandlestickPatternsParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行K线形态检测"""
    result = await technical_tools.detect_candlestick_patterns(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    patterns = result.get("patterns", [])
    text = f"检测到的形态: {', '.join(patterns[:5])}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_detect_divergence(
    name: str,
    args: DetectDivergenceParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行背离检测"""
    result = await technical_tools.detect_divergence(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    divergences = result.get("divergences", [])
    text = f"背离信号: {divergences}"
    return AgentToolResult(content=[TextContent(text=text)])


async def execute_analyze_volume_patterns(
    name: str,
    args: AnalyzeVolumePatternsParams,
    extra: Any = None,
    callback: Any = None,
) -> AgentToolResult:
    """执行成交量模式分析"""
    result = await technical_tools.analyze_volume_patterns(args.symbol, args.interval)
    if "error" in result:
        return AgentToolResult(content=[TextContent(text=f"错误: {result['error']}")])

    pattern = result.get("pattern", "N/A")
    confirmation = result.get("confirmation", "N/A")
    text = f"成交量模式: {pattern}, 确认度: {confirmation}"
    return AgentToolResult(content=[TextContent(text=text)])


def create_submit_trade_order_tool(tool_context: Any) -> AgentTool:
    """Create a Portfolio Manager execution tool bound to a ToolContext."""

    async def execute_submit_trade_order(
        name: str,
        args: SubmitTradeOrderParams,
        extra: Any = None,
        callback: Any = None,
    ) -> AgentToolResult:
        """Submit an order through the configured executor."""
        if not getattr(tool_context, "executor", None):
            raise RuntimeError("No order executor configured for this agent context")

        from vibe_trading.data_sources.binance_client import OrderSide, OrderType, PositionSide

        side = OrderSide(args.side.upper())
        order_type = OrderType(args.order_type.upper())
        position_side = PositionSide(args.position_side.upper())
        trace_id = getattr(tool_context, "current_trace_id", None) or getattr(
            tool_context, "current_bar_open_time_ms", None
        ) or "manual"

        # ===== B9 修復 (2026-08-13 SWDA): PM 路徑訂單正規化 (cap/position_side/reference_price) =====
        # 實證: 06:37 三連拒 (orders #255-257) — LLM 送 qty=0.01 超 notional cap /
        # position_side=BOTH 撞 hedge mode / reference_price=None。
        # 統一與保險路徑同規則 (OrderBuilder), 讓 PM tool 與保險參數一致。
        from vibe_trading.config.settings import get_settings as _get_settings
        from vibe_trading.execution.order_builder import compute_quantity, resolve_position_side

        _settings = _get_settings()

        # C2: hedge mode + position_side=BOTH → 依 side 推導 LONG/SHORT
        if position_side == PositionSide.BOTH and _settings.execution_position_mode == "hedge":
            position_side = resolve_position_side(side, "hedge")
            logger.info(f"[執行] position_side BOTH → {position_side.value} (hedge 正規化, B9)")

        # C4: reference_price 缺 → 自動從 executor 取價
        if not args.reference_price or args.reference_price <= 0:
            _getter = getattr(tool_context.executor, "get_reference_price", None)
            if callable(_getter):
                try:
                    _rp = _getter(args.symbol.upper())
                    if isinstance(_rp, (int, float)) and _rp > 0:
                        args.reference_price = float(_rp)
                        logger.info(f"[執行] reference_price 自動補: {args.reference_price} (B9)")
                    else:
                        args.reference_price = None
                except Exception:
                    args.reference_price = None

        # C3: 非 reduce_only 時 cap qty 至 notional ≤ 上限 (floor stepSize 0.0001)
        if not args.reduce_only and args.reference_price and args.reference_price > 0:
            try:
                _capped = compute_quantity(
                    notional_cap=_settings.execution_max_single_order_notional,
                    reference_price=float(args.reference_price),
                    step_size=0.0001,
                    min_qty=0.0001,
                    min_notional=50.0,
                )
                if args.quantity > _capped:
                    logger.info(
                        f"[執行] qty {args.quantity} 超 notional cap, cap 至 {_capped} (B9)"
                    )
                    args.quantity = _capped
            except Exception as _e:
                logger.warning(f"[執行] qty cap 失敗, 沿用原值: {_e}")

        args.position_side = position_side.value  # 記錄正規化後值
        risk_result = None
        if getattr(tool_context, "risk_gate", None):
            risk_result = await tool_context.risk_gate.validate_order(
                symbol=args.symbol.upper(),
                side=side,
                order_type=order_type,
                quantity=args.quantity,
                price=args.price,
                reference_price=args.reference_price,
                position_side=position_side,
                reduce_only=args.reduce_only,
            )
            if getattr(tool_context, "order_audit", None):
                await tool_context.order_audit.record_risk_check(
                    trace_id=str(trace_id),
                    symbol=args.symbol.upper(),
                    interval=tool_context.interval,
                    open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                    verdict=risk_result.verdict.value,
                    reason=risk_result.reason,
                    request=args.model_dump(),
                    metrics=risk_result.to_dict(),
                )
            if not risk_result.approved:
                details = {
                    "order_id": None,
                    "symbol": args.symbol.upper(),
                    "side": side.value,
                    "order_type": order_type.value,
                    "quantity": args.quantity,
                    "price": args.price,
                    "filled_price": None,
                    "filled_quantity": 0.0,
                    "status": "REJECTED_BY_RISK",
                    "is_paper": None,
                    "rationale": args.rationale,
                    "reduce_only": args.reduce_only,
                    "risk_check": risk_result.to_dict(),
                }
                if getattr(tool_context, "order_audit", None):
                    await tool_context.order_audit.record_order(
                        trace_id=str(trace_id),
                        symbol=args.symbol.upper(),
                        interval=tool_context.interval,
                        open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                        order_id=None,
                        status=details["status"],
                        side=side.value,
                        order_type=order_type.value,
                        quantity=args.quantity,
                        result=details,
                    )
                return AgentToolResult(
                    content=[TextContent(text=f"订单被风控拒绝: {risk_result.reason}")],
                    details=details,
                )

        exchange_filter_result = None
        if getattr(tool_context, "exchange_filter_validator", None):
            # B10 修復 (2026-08-13 SWDA): MARKET 單不帶 price 給 filter 驗證。
            # Binance PRICE_FILTER.tickSize 只適用於 LIMIT 價格；把 reference_price
            # 塞給 MARKET 單會誤判 "price is not aligned to tickSize"
            # (09:37 order #260 鐵證: risk approved 但本地 filter 拒單)。
            # 與 B8 修復 (place_order 送價端) 同源，此處修 filter 驗證端。
            filter_price = (
                None
                if order_type == OrderType.MARKET
                else (args.price or args.reference_price)
            )
            exchange_filter_result = tool_context.exchange_filter_validator.validate(
                symbol=args.symbol.upper(),
                quantity=args.quantity,
                price=filter_price,
            )
            if not exchange_filter_result.approved:
                details = {
                    "order_id": None,
                    "symbol": args.symbol.upper(),
                    "side": side.value,
                    "order_type": order_type.value,
                    "quantity": args.quantity,
                    "price": args.price,
                    "filled_price": None,
                    "filled_quantity": 0.0,
                    "status": "REJECTED_BY_EXCHANGE_FILTER",
                    "is_paper": None,
                    "rationale": args.rationale,
                    "reduce_only": args.reduce_only,
                    "exchange_filter": exchange_filter_result.to_dict(),
                }
                if risk_result:
                    details["risk_check"] = risk_result.to_dict()
                if getattr(tool_context, "order_audit", None):
                    await tool_context.order_audit.record_order(
                        trace_id=str(trace_id),
                        symbol=args.symbol.upper(),
                        interval=tool_context.interval,
                        open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                        order_id=None,
                        status=details["status"],
                        side=side.value,
                        order_type=order_type.value,
                        quantity=args.quantity,
                        result=details,
                    )
                return AgentToolResult(
                    content=[TextContent(text=f"订单未满足交易所过滤规则: {exchange_filter_result.reason}")],
                    details=details,
                )

        # FIX: pass risk-checked effective_price as fallback to avoid the
        # PaperOrderExecutor 50000 mock-price fallback when caller leaves
        # price=None and no real-time price is cached.
        # B8 修復 (2026-08-13 SWDA): MARKET 單不帶 price — Binance -1106
        # "Parameter 'price' sent when not required" (06:08 order #254 鐵證)。
        fill_price = args.price
        if (
            fill_price is None
            and risk_result is not None
            and order_type != OrderType.MARKET
        ):
            fill_price = risk_result.checks.get("effective_price")

        # VBT B5 修復 (2026-08-13 SWDA): place_order 失敗必須可觀測。
        # 舊邏輯: BinanceOrderExecutor.place_order 對 API 400 無 try/except →
        # 異常穿過 tool 被 PM agent loop 吞掉 → risk approved 卻無 order 記錄
        # (04:07:20/26 兩筆 approved 無單鐵證)。
        # 新邏輯: 捕獲異常並以 REJECTED_BY_BROKER 記錄到 audit → 保險對帳可見、
        # log 有 traceback、bar 層可追溯。
        try:
            result = await tool_context.executor.place_order(
                symbol=args.symbol.upper(),
                side=side,
                order_type=order_type,
                quantity=args.quantity,
                price=fill_price,
                stop_price=args.stop_price,
                position_side=position_side,
                reduce_only=args.reduce_only,
            )
        except Exception as e:
            logger.error(
                f"[執行] place_order 失敗 (B5): {e}",
                exc_info=True,
            )
            details = {
                "order_id": None,
                "symbol": args.symbol.upper(),
                "side": side.value,
                "order_type": order_type.value,
                "quantity": args.quantity,
                "price": args.price,
                "filled_price": None,
                "filled_quantity": 0.0,
                "status": "REJECTED_BY_BROKER",
                "is_paper": None,
                "rationale": args.rationale,
                "reduce_only": args.reduce_only,
                "broker_error": str(e),
            }
            if risk_result:
                details["risk_check"] = risk_result.to_dict()
            if getattr(tool_context, "order_audit", None):
                await tool_context.order_audit.record_order(
                    trace_id=str(trace_id),
                    symbol=args.symbol.upper(),
                    interval=tool_context.interval,
                    open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                    order_id=None,
                    status=details["status"],
                    side=side.value,
                    order_type=order_type.value,
                    quantity=args.quantity,
                    result=details,
                )
            return AgentToolResult(
                content=[TextContent(text=f"订单提交失败 (broker): {e}")],
                details=details,
            )

        details = {
            "order_id": result.order_id,
            "symbol": result.symbol,
            "side": result.side.value,
            "order_type": result.order_type.value,
            "quantity": result.quantity,
            "price": result.price,
            "filled_price": result.filled_price,
            "filled_quantity": result.filled_quantity,
            "status": result.status,
            "is_paper": result.is_paper,
            "rationale": args.rationale,
            "reduce_only": args.reduce_only,
        }
        if risk_result:
            details["risk_check"] = risk_result.to_dict()
        if exchange_filter_result:
            details["exchange_filter"] = exchange_filter_result.to_dict()
        if getattr(tool_context, "order_audit", None):
            await tool_context.order_audit.record_order(
                trace_id=str(trace_id),
                symbol=result.symbol,
                interval=tool_context.interval,
                open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                order_id=result.order_id,
                status=result.status,
                side=result.side.value,
                order_type=result.order_type.value,
                quantity=result.quantity,
                result=details,
            )
            if result.filled_quantity:
                await tool_context.order_audit.record_fill(
                    trace_id=str(trace_id),
                    symbol=result.symbol,
                    interval=tool_context.interval,
                    open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                    order_id=result.order_id,
                    fill_id=f"{result.order_id}:fill",
                    side=result.side.value,
                    quantity=result.filled_quantity,
                    price=result.filled_price or result.price or 0.0,
                    fee=None,
                    fee_asset=None,
                )
            positions = await tool_context.executor.get_positions()
            balances = await tool_context.executor.get_balance()
            await tool_context.order_audit.record_position_snapshot(
                trace_id=str(trace_id),
                symbol=result.symbol,
                interval=tool_context.interval,
                open_time_ms=getattr(tool_context, "current_bar_open_time_ms", None),
                positions=[
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
                ],
                balances=balances,
            )
        text = (
            f"订单已提交: {result.status}\n"
            f"order_id={result.order_id}, symbol={result.symbol}, side={result.side.value}, "
            f"type={result.order_type.value}, quantity={result.quantity}, "
            f"filled={result.filled_quantity} @ {result.filled_price}"
        )
        return AgentToolResult(content=[TextContent(text=text)], details=details)

    return AgentTool(
        name="submit_trade_order",
        label="提交交易订单",
        description=(
            "Portfolio Manager 专用执行工具。仅在最终批准交易后调用。"
            "根据当前执行器配置提交订单；Paper/Dry-run 模式不会触发真实主网成交。"
        ),
        parameters=SubmitTradeOrderParams,
        execute=execute_submit_trade_order,
    )


def get_execution_tools(tool_context: Any) -> list[AgentTool]:
    """Get execution tools bound to the provided ToolContext."""
    return [create_submit_trade_order_tool(tool_context)]


class PortfolioDecisionParams(BaseModel):
    """submit_portfolio_decision 參數 (規格書 v1.0.0 §4.2).

    Phase 5 — PM 以結構化動作意圖取代一期現貨式 BUY/HOLD/SELL 字串,
    徹底消滅 34.7% 評分卡兜底 (R3) 並解鎖做空 (R1).
    """
    action: str = Field(description=(
        "合約全生命週期動作: OPEN_LONG / ADD_LONG / OPEN_SHORT / "
        "ADD_SHORT / TP_PARTIAL / CLOSE_ALL / TRAIL_STOP / HOLD"))
    confidence: float = Field(ge=0.0, le=1.0, description="決策置信度 (0.0-1.0)")
    suggested_entry_price: float = Field(description="建議進場或基準參考價")
    suggested_stop_loss: float = Field(description="結構止損價格")
    suggested_take_profit: float = Field(description="第一目標止盈價格 (TP1)")
    core_rationale: str = Field(default="", description="核心決策邏輯摘要")


def create_submit_portfolio_decision_tool(tool_context: Any) -> AgentTool:
    """Create the structured decision tool bound to a ToolContext (Phase 5).

    PM 呼叫此工具輸出結構化決策 (action + 點位)。執行層將其暫存於
    tool_context.portfolio_decision, 供 coordinator 量化引擎消費
    (Half-Kelly 倉位計算 → 執行)。HOLD 動作僅記錄, 不觸發下單。
    """

    async def execute_submit_portfolio_decision(
        name: str,
        args: PortfolioDecisionParams,
        extra: Any = None,
        callback: Any = None,
    ) -> AgentToolResult:
        from vibe_trading.agents.decision.trading_tools import PositionAction
        try:
            action = PositionAction(args.action.upper())
        except ValueError:
            # 非法動作 → Fail-Open 安全降級 HOLD (護欄 4)
            logger.warning(f"[決策] 非法動作 '{args.action}' → 降級 HOLD")
            action = PositionAction.HOLD

        decision = {
            "action": action.value,
            "confidence": float(args.confidence),
            "entry_price": float(args.suggested_entry_price),
            "stop_loss": float(args.suggested_stop_loss),
            "take_profit": float(args.suggested_take_profit),
            "rationale": args.core_rationale,
        }
        # 暫存供 coordinator 消費 (量化引擎)
        tool_context.portfolio_decision = decision
        logger.info(
            f"[決策] submit_portfolio_decision: {action.value} "
            f"conf={args.confidence:.2f} entry={args.suggested_entry_price:.0f} "
            f"SL={args.suggested_stop_loss:.0f} TP={args.suggested_take_profit:.0f}"
        )
        return AgentToolResult(content=[TextContent(
            text=f"Portfolio decision recorded: {action.value}"
        )])

    return AgentTool(
        name="submit_portfolio_decision",
        label="提交投資組合決策",
        description=(
            "Portfolio Manager 專用結構化決策工具 (Phase 5 雙向對稱決策)。"
            "輸出合約全生命週期動作 (OPEN_LONG/OPEN_SHORT/TP_PARTIAL/TRAIL_STOP/...) "
            "與結構點位 (entry/SL/TP), 取代文字決策。"
        ),
        parameters=PortfolioDecisionParams,
        execute=execute_submit_portfolio_decision,
    )


def get_decision_tools(tool_context: Any) -> list[AgentTool]:
    """Get Phase 5 structured decision tool bound to ToolContext."""
    return [create_submit_portfolio_decision_tool(tool_context)]


def get_technical_tools(tool_context: Any) -> list[AgentTool]:
    """Get context-bound technical analysis tools (compose_factor, Phase 2.2)."""
    return [create_compose_factor_tool(tool_context)]


# =============================================================================
# Tool 定义
# =============================================================================

def get_all_tools() -> list[AgentTool]:
    """获取所有可用工具 (共24个)"""
    return [
        # ========== 基础市场数据 (5个) ==========
        AgentTool(
            name="get_current_price",
            label="获取当前价格",
            description="获取指定交易对的当前市场价格",
            parameters=GetCurrentPriceParams,
            execute=execute_get_current_price,
        ),
        AgentTool(
            name="get_24hr_ticker",
            label="获取24小时行情",
            description="获取指定交易对24小时价格变动数据",
            parameters=Get24hrTickerParams,
            execute=execute_get_24hr_ticker,
        ),
        AgentTool(
            name="get_funding_rate",
            label="获取资金费率",
            description="获取永续合约的资金费率",
            parameters=GetFundingRateParams,
            execute=execute_get_funding_rate,
        ),
        AgentTool(
            name="get_long_short_ratio",
            label="获取多空比",
            description="获取账户多空持仓比",
            parameters=GetLongShortRatioParams,
            execute=execute_get_long_short_ratio,
        ),
        AgentTool(
            name="get_open_interest",
            label="获取持仓量",
            description="获取合约持仓量",
            parameters=GetOpenInterestParams,
            execute=execute_get_open_interest,
        ),

        # ========== 情绪分析工具 (3个) ==========
        AgentTool(
            name="get_fear_and_greed_index",
            label="获取恐惧贪婪指数",
            description="获取加密市场恐惧贪婪指数",
            parameters=GetFearAndGreedParams,
            execute=execute_get_fear_and_greed,
        ),
        AgentTool(
            name="get_news_sentiment",
            label="获取新闻情绪",
            description="获取最新的加密货币新闻及其情绪分析",
            parameters=GetNewsSentimentParams,
            execute=execute_get_news_sentiment,
        ),
        AgentTool(
            name="get_social_sentiment",
            label="获取社交媒体情绪",
            description="获取社交媒体上的讨论情绪和提及次数",
            parameters=GetSocialSentimentParams,
            execute=execute_get_social_sentiment,
        ),

        # ========== 深度数据工具 (4个) ==========
        AgentTool(
            name="get_order_book",
            label="获取订单簿",
            description="获取交易对的订单簿深度数据",
            parameters=GetOrderBookParams,
            execute=execute_get_order_book,
        ),
        AgentTool(
            name="get_taker_buy_sell_ratio",
            label="获取主动买卖比例",
            description="获取主动买盘和卖盘的比例",
            parameters=GetTakerBuySellRatioParams,
            execute=execute_get_taker_buy_sell_ratio,
        ),
        AgentTool(
            name="get_top_trader_long_short_ratio",
            label="获取大户多空比",
            description="获取大户(Top Trader)的多空持仓比例",
            parameters=GetTopTraderLongShortRatioParams,
            execute=execute_get_top_trader_long_short_ratio,
        ),
        AgentTool(
            name="get_liquidation_orders",
            label="获取清算订单",
            description="获取最近的清算订单数据",
            parameters=GetLiquidationOrdersParams,
            execute=execute_get_liquidation_orders,
        ),

        # ========== 综合分析工具 (2个) ==========
        AgentTool(
            name="get_trending_symbols",
            label="获取热门交易对",
            description="获取当前热门的交易对列表",
            parameters=GetTrendingSymbolsParams,
            execute=execute_get_trending_symbols,
        ),
        AgentTool(
            name="get_comprehensive_sentiment",
            label="获取综合情绪分析",
            description="获取综合情绪评分和信号",
            parameters=GetComprehensiveSentimentParams,
            execute=execute_get_comprehensive_sentiment,
        ),

        # ========== 技术分析工具 (9个) ==========
        AgentTool(
            name="get_technical_indicators",
            label="获取技术指标",
            description="获取RSI、MACD、布林带等技术指标",
            parameters=GetTechnicalIndicatorsParams,
            execute=execute_get_technical_indicators,
        ),
        AgentTool(
            name="get_kline_data",
            label="获取K线数据",
            description="获取指定交易对的K线数据",
            parameters=GetKlineDataParams,
            execute=execute_get_kline_data,
        ),
        AgentTool(
            name="get_comprehensive_technical_analysis",
            label="获取综合技术分析",
            description="获取综合技术分析包括趋势、信号等",
            parameters=GetComprehensiveTechnicalAnalysisParams,
            execute=execute_get_comprehensive_technical_analysis,
        ),
        AgentTool(
            name="analyze_trend",
            label="分析趋势",
            description="分析当前价格趋势方向和强度",
            parameters=AnalyzeTrendParams,
            execute=execute_analyze_trend,
        ),
        AgentTool(
            name="detect_support_resistance",
            label="检测支撑阻力",
            description="检测支撑位和阻力位",
            parameters=DetectSupportResistanceParams,
            execute=execute_detect_support_resistance,
        ),
        AgentTool(
            name="calculate_pivots",
            label="计算枢轴点",
            description="计算枢轴点和支撑阻力位",
            parameters=CalculatePivotsParams,
            execute=execute_calculate_pivots,
        ),
        AgentTool(
            name="detect_candlestick_patterns",
            label="检测K线形态",
            description="检测K线形态如十字星、锤子线等",
            parameters=DetectCandlestickPatternsParams,
            execute=execute_detect_candlestick_patterns,
        ),
        AgentTool(
            name="detect_divergence",
            label="检测背离",
            description="检测价格与指标的背离信号",
            parameters=DetectDivergenceParams,
            execute=execute_detect_divergence,
        ),
        AgentTool(
            name="analyze_volume_patterns",
            label="分析成交量模式",
            description="分析成交量模式和趋势确认",
            parameters=AnalyzeVolumePatternsParams,
            execute=execute_analyze_volume_patterns,
        ),
    ]


def get_agent_tools() -> list[AgentTool]:
    """获取通用工具集合 (向后兼容)"""
    return get_all_tools()


def get_tools_for_agent(agent_role: str) -> list[AgentTool]:
    """根据Agent角色分配专门的工具集合

    Args:
        agent_role: Agent角色 (technical_analyst, fundamental_analyst, etc.)

    Returns:
        该角色专用的工具列表
    """
    all_tools = {tool.name: tool for tool in get_all_tools()}

    # 分析师团队 - 专注于各自领域的数据
    if agent_role == "technical_analyst":
        # 技术分析师需要技术分析工具
        tools = [
            all_tools["get_current_price"],
            all_tools["get_24hr_ticker"],
            all_tools["get_order_book"],
            all_tools["get_technical_indicators"],
            all_tools["get_comprehensive_technical_analysis"],
            all_tools["analyze_trend"],
            all_tools["detect_support_resistance"],
            all_tools["detect_candlestick_patterns"],
        ]
        # Fix 2026-08-15: compose_factor 不在 get_all_tools（透過 additional_tools 綁定）
        # → 動態附加，避免 KeyError 使 technical_analyst 完全拿不到 tools
        compose = all_tools.get("compose_factor")
        if compose is not None:
            tools.append(compose)
        return tools

    elif agent_role == "fundamental_analyst":
        return [
            all_tools["get_funding_rate"],
            all_tools["get_long_short_ratio"],
            all_tools["get_open_interest"],
            all_tools["get_taker_buy_sell_ratio"],
            all_tools["get_top_trader_long_short_ratio"],
        ]

    elif agent_role == "news_analyst":
        return [
            all_tools["get_news_sentiment"],
            all_tools["get_trending_symbols"],
        ]

    elif agent_role == "sentiment_analyst":
        return [
            all_tools["get_fear_and_greed_index"],
            all_tools["get_social_sentiment"],
            all_tools["get_comprehensive_sentiment"],
            all_tools["get_funding_rate"],  # 资金费率反映情绪
            all_tools["get_long_short_ratio"],  # 多空比反映情绪
        ]

    # 研究员团队 - 综合工具用于辩论
    elif agent_role in ["bull_researcher", "bear_researcher", "research_manager"]:
        # Fix 2026-08-09: 精簡 tools 降低 400 provider error 率
        # 原 8 個 tools 讓 opencode proxy 偶發 400（Upstream request failed）；
        # debate 主要靠 analyst reports + 情緒/資金數據，保留最核心的 5 個。
        return [
            all_tools["get_current_price"],
            all_tools["get_fear_and_greed_index"],
            all_tools["get_funding_rate"],
            all_tools["get_long_short_ratio"],
            all_tools["get_open_interest"],
        ]

    # 风控团队 - 需要风险相关数据
    elif agent_role in ["aggressive_debator", "neutral_debator", "conservative_debator"]:
        return [
            all_tools["get_liquidation_orders"],
            all_tools["get_funding_rate"],
            all_tools["get_open_interest"],
            all_tools["get_taker_buy_sell_ratio"],
        ]

    # 决策团队 - 需要全面数据
    elif agent_role == "trader":
        return [
            all_tools["get_current_price"],
            all_tools["get_24hr_ticker"],
            all_tools["get_order_book"],
            all_tools["get_funding_rate"],
            all_tools["get_technical_indicators"],
        ]

    elif agent_role == "portfolio_manager":
        # 投资组合经理需要所有工具
        return get_all_tools()

    # 默认返回基础工具
    return [
        all_tools["get_current_price"],
        all_tools["get_24hr_ticker"],
        all_tools["get_fear_and_greed_index"],
    ]
