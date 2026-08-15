"""
Vibe Trading - 主入口

支持实盘和纸面交易模式，使用三线程架构:
1. Macro Judgment Thread - 每小时分析宏观环境
2. Main Trading Thread - K线触发决策流程
3. Event-Driven Thread - 监控紧急事件
"""
import asyncio
from enum import Enum
from typing import List

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pi_logger import get_logger, configure, info, success, warning, separator

from vibe_trading.config.settings import get_settings
from vibe_trading.main.multi_thread_main import MultiThreadedTradingSystem
from vibe_trading.data_sources.kline_storage import KlineStorage
from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
from vibe_trading.execution.order_executor import TradingMode as ExecutorTradingMode, create_executor

# Prime Agent导入
from vibe_trading.prime import PrimeAgent, PrimeAgentConfig, PrimeConfig, HarnessConfig

# 初始化
app = typer.Typer(help="Vibe Trading - AI驱动的量化交易系统")
console = Console()
logger = get_logger("main")


class TradingMode(str, Enum):
    """交易模式"""
    PAPER = "paper"  # 纸面交易
    TESTNET = "testnet"  # Binance 测试网
    LIVE = "live"    # 实盘交易


async def run_web_server(port: int = 8000, symbol: str = "BTCUSDT", interval: str = "30m") -> None:
    """
    在后台运行 Web 服务器

    Args:
        port: Web 服务器端口
        symbol: 交易对符号
        interval: K线周期
    """
    import uvicorn
    from vibe_trading.web.server import app, set_initial_config

    # 在启动前设置配置
    set_initial_config(symbol, interval)

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    except asyncio.CancelledError:
        info("Web 服务器已停止", tag="WEB")
    except Exception as e:
        logger.error(f"Web 服务器错误: {e}", exc_info=True)


@app.command()
def start(
    symbols: List[str] = typer.Argument(..., help="交易对符号，如 BTCUSDT ETHUSDT"),
    interval: str = typer.Option("30m", help="K线间隔 (1m, 5m, 15m, 30m, 1h, 4h, 1d)"),
    mode: str = typer.Option("paper", help="交易模式: paper、testnet 或 live"),
    execute: bool = typer.Option(False, help="--execute: 实盘模式下真正执行订单"),
    log_level: str = typer.Option("INFO", help="日志级别: DEBUG, INFO, WARNING, ERROR"),
    save_logs: bool = typer.Option(True, help="--save-logs/--no-save-logs: 是否保存日志到文件 (默认保存到 logs/ 目录)"),
    web: bool = typer.Option(False, help="--web: 启动 Web 监控界面 (默认端口 8000)"),
    web_port: int = typer.Option(8000, help="--web-port: Web 监控界面端口"),
    paper_state: str = typer.Option(
        "", help="paper 模式账户状态文件路径 (默认 data/paper_account.json，跨重启保留 balance/持仓)"
    ),
    reset_paper: bool = typer.Option(
        False, "--reset-paper", help="重置 paper 账户 (忽略状态文件，从初始余额重新开始)"
    ),
):
    """
    启动三线程交易系统

    使用三线程架构:
    - Macro Thread: 每小时分析宏观环境
    - On Bar Thread: K线触发决策流程
    - Event Thread: 监控紧急事件并触发应急流程

    示例:
        # 纸面交易
        vibe-trade start BTCUSDT

        # 实盘交易 (仅打印订单)
        vibe-trade start BTCUSDT --mode live

        # 实盘交易 (真正执行)
        vibe-trade start BTCUSDT --mode live --execute

        # 启动 Web 监控界面
        vibe-trade start BTCUSDT --web

        # 多交易对 (使用第一个作为主symbol)
        vibe-trade start BTCUSDT ETHUSDT SOLUSDT
    """
    # 配置日志
    configure(log_level=log_level, json_output=False, enable_file_logging=True)
    mode = mode.lower()

    # 验证交易模式
    trading_mode = TradingMode.PAPER
    if mode == "testnet":
        trading_mode = TradingMode.TESTNET
        console.print("[yellow]⚠️  Binance Testnet 模式 - 将向测试网提交订单，不使用真实资金[/yellow]")
    elif mode == "live":
        trading_mode = TradingMode.LIVE
        # 实盘模式二次确认
        if not execute:
            console.print("[red]⚠️  警告: 实盘交易模式 (dry-run) - 订单将被打印但不会执行[/red]")
            confirm = typer.confirm("确定要继续吗？")
            if not confirm:
                raise typer.Abort()
        else:
            console.print("[red]⚠️  警告: 实盘交易模式 (EXECUTE) - 订单将被真正执行！[/red]")
            console.print("[red]⚠️  这将使用真实资金进行交易！[/red]")
            confirm = typer.confirm("确定要继续吗？", default=False)
            if not confirm:
                raise typer.Abort()
    elif mode != "paper":
        console.print("[red]交易模式无效，请使用 paper、testnet 或 live[/red]")
        raise typer.Abort()

    # 显示启动信息
    mode_color = "green" if trading_mode == TradingMode.PAPER else ("yellow" if trading_mode == TradingMode.TESTNET else "red")
    mode_text = {
        TradingMode.PAPER: "📝 纸面交易模式",
        TradingMode.TESTNET: "🧪 Binance Testnet 模式",
        TradingMode.LIVE: "⚠️  实盘交易模式",
    }[trading_mode]

    web_status = f"✅ 启用 (http://localhost:{web_port})" if web else "❌ 未启用"

    console.print()
    console.print(Panel(
        f"[bold {mode_color}]{mode_text}[/bold {mode_color}]\n\n"
        f"交易对: {', '.join(symbols)}\n"
        f"K线周期: {interval}\n"
        f"执行交易: {'是' if execute else '否 (仅打印)'}\n"
        f"Web 监控: {web_status}\n"
        f"线程架构: Macro + OnBar + Event",
        title="[bold cyan]🤖 Vibe Trading - 三线程架构[/bold cyan]",
        border_style="cyan",
    ))

    if trading_mode == TradingMode.LIVE and not execute:
        console.print("[yellow]⚠️  警告: 实盘模式但未启用--execute，订单将被打印但不会真正执行[/yellow]")

    console.print()

    # 使用第一个symbol作为主symbol (可扩展为多symbol支持)
    primary_symbol = symbols[0]

    if len(symbols) > 1:
        warning(f"多交易对模式: 使用 {primary_symbol} 作为主symbol，其他symbol暂不支持", tag="INFO")

    executor = create_execution_executor(trading_mode, execute, paper_state, reset_paper)

    # 运行三线程系统
    asyncio.run(run_multi_thread_system(
        symbol=primary_symbol,
        interval=interval,
        mode=trading_mode,
        execute_trades=execute,
        executor=executor,
        save_logs=save_logs,
        enable_web=web,
        web_port=web_port,
        log_level=log_level,
    ))


def create_execution_executor(
    mode: TradingMode,
    execute: bool,
    paper_state: str = "",
    reset_paper: bool = False,
):
    """Create the executor bound to Portfolio Manager tools."""
    if mode == TradingMode.PAPER:
        state_file = paper_state or str(
            Path(__file__).resolve().parent.parent.parent.parent
            / "data"
            / "paper_account.json"
        )
        return create_executor(
            ExecutorTradingMode.PAPER,
            paper_state_file=state_file,
            reset_paper=reset_paper,
        )
    if mode == TradingMode.TESTNET:
        return create_executor(ExecutorTradingMode.TESTNET, dry_run=False)
    if not execute:
        return create_executor(ExecutorTradingMode.LIVE, dry_run=True)
    return create_executor(ExecutorTradingMode.LIVE, dry_run=False)


async def run_multi_thread_system(
    symbol: str,
    interval: str,
    mode: TradingMode,
    execute_trades: bool,
    executor=None,
    save_logs: bool = True,
    enable_web: bool = False,
    web_port: int = 8000,
    log_level: str = "INFO",
) -> None:
    """
    运行三线程交易系统

    Args:
        symbol: 交易对符号
        interval: K线间隔
        mode: 交易模式
        execute_trades: 是否真正执行交易
        save_logs: 是否保存日志
        enable_web: 是否启动 Web 监控界面
        web_port: Web 服务器端口
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
    """
    info(f"启动三线程交易系统: {symbol} ({interval})", tag="START")
    separator("=", 60)

    # 配置文件日志
    log_file_path = None
    if save_logs:
        from pathlib import Path
        from datetime import datetime
        
        # 创建logs目录
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        
        # 生成日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = logs_dir / f"trading_{symbol}_{timestamp}.log"
        
        configure(log_level=log_level, json_output=False, log_file=str(log_file_path))
        info(f"日志将保存到: {log_file_path}", tag="LOG")
    else:
        configure(log_level=log_level, json_output=False)
        info("文件日志已禁用", tag="LOG")

    # Web 服务器任务
    web_server_task = None

    try:
        # 创建多线程系统
        system = MultiThreadedTradingSystem(
            symbol=symbol,
            interval=interval,
            executor=executor,
            mode=mode.value,
        )

        # 设置信号处理
        system.setup_signal_handlers()

        # 启动 Web 服务器（如果启用）
        if enable_web:
            info(f"启动 Web 监控界面: http://localhost:{web_port}", tag="WEB")
            web_server_task = asyncio.create_task(run_web_server(web_port, symbol, interval))

        # 运行系统
        await system.run()

    except KeyboardInterrupt:
        info("收到键盘中断")
    except Exception as e:
        logger.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 停止 Web 服务器
        if web_server_task:
            info("正在关闭 Web 服务器...", tag="WEB")
            web_server_task.cancel()
            try:
                await asyncio.wait_for(web_server_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                pass

        info("系统关闭完成")


@app.command()
def analyze(
    symbol: str = typer.Argument(..., help="交易对符号"),
    interval: str = typer.Option("30m", help="K线间隔"),
):
    """
    运行单次分析

    获取当前市场数据并执行一次完整的Agent决策流程
    """
    configure(log_level="INFO", json_output=False)

    async def run_analysis():
        storage = KlineStorage()
        await storage.init()

        from vibe_trading.memory.hybrid_memory import create_hybrid_memory_from_settings
        memory = create_hybrid_memory_from_settings()

        coordinator = TradingCoordinator(
            symbol=symbol,
            interval=interval,
            storage=storage,
            memory=memory,
        )
        await coordinator.initialize()

        # 获取当前价格
        from vibe_trading.tools.market_data_tools import get_current_price
        price_result = await get_current_price(symbol)
        current_price = float(price_result.get("price", 0)) if price_result else 0.0

        # 执行分析
        decision = await coordinator.analyze_and_decide(
            current_price=current_price,
            account_balance=10000.0,
        )

        console.print()
        console.print(Panel(
            f"[bold]决策: {decision.decision}[/bold]\n\n{decision.rationale[:300]}...",
            title=f"[bold cyan]{symbol} 分析结果[/bold cyan]",
        ))

        await storage.close()

    asyncio.run(run_analysis())


@app.command()
def prime(
    symbols: List[str] = typer.Argument(..., help="交易对符号，如 BTCUSDT ETHUSDT"),
    interval: str = typer.Option("30m", help="K线间隔 (1m, 5m, 15m, 30m, 1h, 4h, 1d)"),
    mode: str = typer.Option("paper", help="交易模式: paper (纸面) 或 live (实盘)"),
    execute: bool = typer.Option(False, help="--execute: 实盘模式下真正执行订单"),
    log_level: str = typer.Option("INFO", help="日志级别: DEBUG, INFO, WARNING, ERROR"),
    save_logs: bool = typer.Option(True, help="--save-logs/--no-save-logs: 是否保存日志到文件"),
    web: bool = typer.Option(False, help="--web: 启动 Web 监控界面 (默认端口 8000)"),
    web_port: int = typer.Option(8000, help="--web-port: Web 监控界面端口"),
):
    """
    启动Prime Agent监控模式（基于pi_agent_core的新架构）

    Prime Agent作为系统监控者和紧急仲裁者：
    - 运行三线程交易系统（Macro + OnBar + Event）
    - 监控系统健康状态（资金、仓位、风险）
    - 检测紧急情况（价格暴跌、风险超标）
    - 紧急情况下可覆盖决策或直接调用Subagent

    正常情况：Subagents按5阶段流程协作工作
    紧急情况：Prime Agent介入并采取保护措施

    示例:
        # 纸面交易
        vibe-trade prime BTCUSDT

        # 实盘交易 (仅打印订单)
        vibe-trade prime BTCUSDT --mode live

        # 实盘交易 (真正执行)
        vibe-trade prime BTCUSDT --mode live --execute

        # 启动 Web 监控界面
        vibe-trade prime BTCUSDT --web
    """
    # 配置日志
    configure(log_level=log_level, json_output=False, enable_file_logging=save_logs)

    # 验证交易模式
    trading_mode = TradingMode.PAPER
    if mode == "live":
        trading_mode = TradingMode.LIVE
        # 实盘模式二次确认
        if not execute:
            console.print("[red]⚠️  警告: 实盘交易模式 (dry-run) - 订单将被打印但不会执行[/red]")
            confirm = typer.confirm("确定要继续吗？")
            if not confirm:
                raise typer.Abort()
        else:
            console.print("[red]⚠️  警告: 实盘交易模式 (EXECUTE) - 订单将被真正执行！[/red]")
            console.print("[red]⚠️  这将使用真实资金进行交易！[/red]")
            confirm = typer.confirm("确定要继续吗？", default=False)
            if not confirm:
                raise typer.Abort()

    # 显示启动信息
    mode_color = "green" if trading_mode == TradingMode.PAPER else "red"
    mode_text = "📝 纸面交易模式" if trading_mode == TradingMode.PAPER else "⚠️ 实盘交易模式"

    web_status = f"✅ 启用 (http://localhost:{web_port})" if web else "❌ 未启用"

    console.print()
    console.print(Panel(
        f"[bold {mode_color}]{mode_text}[/bold {mode_color}]\n\n"
        f"交易对: {', '.join(symbols)}\n"
        f"K线周期: {interval}\n"
        f"执行交易: {'是' if execute else '否 (仅打印)'}\n"
        f"Web 监控: {web_status}\n"
        f"架构: 三线程系统 + Prime Agent监控层",
        title="[bold magenta]🤖 Vibe Trading - Prime Agent监控模式[/bold magenta]",
        border_style="magenta",
    ))

    console.print()
    info(f"启动Prime Agent系统: {symbols[0]} ({interval})", tag="START")
    separator("=", 60)

    # 运行Prime Agent系统
    asyncio.run(run_prime_system(
        symbols=symbols,
        interval=interval,
        mode=trading_mode,
        execute_trades=execute,
        save_logs=save_logs,
        enable_web=web,
        web_port=web_port,
    ))


async def run_prime_system(
    symbols: List[str],
    interval: str,
    mode: TradingMode,
    execute_trades: bool,
    save_logs: bool = True,
    enable_web: bool = False,
    web_port: int = 8000,
) -> None:
    """
    运行Prime Agent系统

    Args:
        symbols: 交易对列表
        interval: K线间隔
        mode: 交易模式
        execute_trades: 是否真正执行交易
        save_logs: 是否保存日志
        enable_web: 是否启动 Web 监控界面
        web_port: Web 服务器端口
    """
    # 配置文件日志
    log_file_path = None
    if save_logs:
        from pathlib import Path
        from datetime import datetime

        # 创建logs目录
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        # 生成日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = logs_dir / f"prime_{symbols[0]}_{timestamp}.log"

        configure(log_level="INFO", json_output=False, log_file=str(log_file_path))
        info(f"日志将保存到: {log_file_path}", tag="LOG")
    else:
        configure(log_level="INFO", json_output=False)
        info("文件日志已禁用", tag="LOG")

    # Web 服务器任务
    web_server_task = None

    try:
        # 创建Prime Agent配置
        prime_config = PrimeConfig(
            symbol=symbols[0],  # 主交易对
            interval=interval,  # K线间隔
            monitoring_interval=1.0,
            max_queue_size=1000,
            max_single_trade=1000.0 if mode == TradingMode.PAPER else 100.0,  # 纸面交易可以用更大金额
            max_total_position=0.3,
            enable_emergency_override=True,
            enabled_subagents=[
                "technical_analyst",
                "bull_researcher",
                "bear_researcher",
                "research_manager",
                "aggressive_risk_analyst",
                "neutral_risk_analyst",
                "conservative_risk_analyst",
                "trader",
                "portfolio_manager",
                "macro_analyst",
            ],
        )

        harness_config = HarnessConfig(
            enable_safety_constraint=True,
            enable_operational_constraint=True,
            enable_behavioral_constraint=True,
            enable_resource_constraint=True,
        )

        config = PrimeAgentConfig(
            system_prompt=f"""你是Prime Agent，负责监控系统健康状态并在紧急情况下保护资金安全。

当前配置：
- 交易对: {symbols[0]}
- K线周期: {interval}
- 交易模式: {mode.value}

你的职责：
1. 监控系统健康状态（资金、仓位、风险指标）
2. 检测紧急情况（价格暴跌、风险超标）
3. 紧急情况下采取保护措施（平仓、减仓）
4. 正常情况下不干预三线程系统的运行

请始终以系统安全和风险控制为首要目标。""",
            prime_config=prime_config,
            harness_config=harness_config,
        )

        # 创建Prime Agent
        prime_agent = PrimeAgent(config)

        # 启动 Web 服务器（如果启用）
        if enable_web:
            info(f"启动 Web 监控界面: http://localhost:{web_port}", tag="WEB")
            web_server_task = asyncio.create_task(run_web_server(web_port))

        # 启动Prime Agent
        await prime_agent.start()

    except KeyboardInterrupt:
        info("收到键盘中断，正在关闭Prime Agent...")
    except Exception as e:
        logger.error(f"Prime Agent系统错误: {e}", exc_info=True)
    finally:
        # 停止 Web 服务器
        if web_server_task:
            info("正在关闭 Web 服务器...", tag="WEB")
            web_server_task.cancel()
            try:
                await web_server_task
            except asyncio.CancelledError:
                pass

        info("Prime Agent系统关闭完成")


@app.command()
def status():
    """显示系统状态"""
    settings = get_settings()

    table = Table(title="Vibe Trading 系统状态")
    table.add_column("项目", style="cyan")
    table.add_column("值", style="green")

    table.add_row("可用架构", "三线程 (Macro + OnBar + Event), Prime Agent (pi_agent_core)")
    table.add_row("交易模式", settings.trading_mode.value)
    table.add_row("交易对", ", ".join(settings.symbols))
    table.add_row("K线周期", settings.interval)
    table.add_row("数据库", settings.database_url)
    table.add_row("LLM模型", settings.llm_config_name)
    table.add_row("Subagent数量", "10个可用 (3个待实现)")

    console.print(table)


@app.command()
def macro(
    symbol: str = typer.Argument("BTCUSDT", help="交易对符号"),
):
    """
    运行一次宏观分析

    执行宏观环境分析并存储结果
    """
    configure(log_level="INFO", json_output=False)

    async def run_macro_analysis():
        from vibe_trading.threads.macro_thread import MacroAnalysisThread

        info(f"运行宏观分析: {symbol}", tag="MACRO")

        macro_thread = MacroAnalysisThread(symbol=symbol)
        await macro_thread.initialize()

        result = await macro_thread.run_once()

        if result:
            success(f"宏观分析完成: {result.get('market_regime')}", tag="MACRO")
            console.print(Panel(
                f"[bold]趋势方向:[/bold] {result.get('trend_direction')}\n"
                f"[bold]市场状态:[/bold] {result.get('market_regime')}\n"
                f"[bold]整体情绪:[/bold] {result.get('overall_sentiment')}\n"
                f"[bold]信心分数:[/bold] {result.get('confidence', 0):.2f}",
                title="[bold cyan]宏观分析结果[/bold cyan]",
            ))
        else:
            warning("宏观分析失败", tag="MACRO")

    asyncio.run(run_macro_analysis())


# Alpha Zoo CLI commands
alpha_app = typer.Typer(help="Alpha 因子庫管理")
app.add_typer(alpha_app, name="alpha")


@alpha_app.command("list")
def alpha_list(
    category: str = typer.Option(None, "--category", "-c", help="因子類別 (momentum/volatility/volume/mean_reversion)"),
):
    """列出所有可用因子"""
    from vibe_trading.backtest.alphas import get_all_alphas, get_alphas_by_category
    
    table = Table(title="Alpha 因子庫")
    table.add_column("名稱", style="cyan")
    table.add_column("類別", style="green")
    table.add_column("公式", style="yellow")
    table.add_column("預熱期", justify="right")
    table.add_column("標籤", style="magenta")
    
    if category:
        alphas = get_alphas_by_category(category)
    else:
        alphas = get_all_alphas()
    
    for alpha_class in alphas:
        meta = alpha_class.__alpha_meta__
        table.add_row(
            meta.name,
            meta.tags[0] if meta.tags else "unknown",
            meta.formula,
            str(meta.warmup_periods),
            ", ".join(meta.tags[:3]),
        )
    
    console.print(table)
    console.print(f"\n共 {len(alphas)} 個因子")


@alpha_app.command("bench")
def alpha_bench(
    symbol: str = typer.Argument("BTCUSDT", help="交易對符號"),
    interval: str = typer.Option("1h", "--interval", "-i", help="K線間隔"),
    periods: int = typer.Option(500, "--periods", "-p", help="數據期數"),
    forward_period: int = typer.Option(1, "--forward", "-f", help="前瞻期數"),
    category: str = typer.Option(None, "--category", "-c", help="因子類別篩選"),
):
    """運行因子 IC/IR benchmark 報告"""
    from vibe_trading.backtest.alphas import get_all_alphas, get_alphas_by_category
    from vibe_trading.backtest.alphas.metrics import calculate_ic_summary
    from vibe_trading.data_sources.kline_storage import KlineStorage
    
    # 獲取因子列表
    if category:
        alphas = get_alphas_by_category(category)
    else:
        alphas = get_all_alphas()
    # 加載數據
    try:
        storage = KlineStorage()
        from vibe_trading.data_sources.kline_storage import KlineQuery
        query = KlineQuery(symbol=symbol, interval=interval, limit=periods + 50)
        klines = asyncio.run(storage.query_klines(query))
        if not klines:
            warning(f"無法獲取 {symbol} 的 K線數據（數據庫為空）", tag="ALPHA")
            console.print("[dim]提示: 先運行 vibe-trade start 收集數據，或使用 --demo 生成模擬數據[/dim]")
            return
        
        # 轉換為 DataFrame
        import pandas as pd
        data = pd.DataFrame([
            {
                "open_time": k.open_time,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume,
            }
            for k in klines
        ])
        data["open_time"] = pd.to_datetime(data["open_time"], unit="ms")
        data.set_index("open_time", inplace=True)
    except Exception as e:
        warning(f"數據加載失敗: {e}", tag="ALPHA")
        return
    
    # 計算前瞻收益
    close = data["close"]
    forward_returns = close.shift(-forward_period).pct_change(forward_period).shift(forward_period)
    
    # 運行每個因子
    results = []
    for alpha_class in alphas:
        try:
            alpha = alpha_class()
            meta = alpha.__alpha_meta__
            
            # 計算因子值
            factor_values = alpha.compute(data)
            
            # 對齊數據
            common_idx = factor_values.index.intersection(forward_returns.index)
            fv = factor_values.loc[common_idx]
            fr = forward_returns.loc[common_idx]
            
            # 計算 IC/IR
            summary = calculate_ic_summary(fv, fr)
            
            results.append({
                "name": meta.name,
                "category": meta.tags[0] if meta.tags else "unknown",
                "ic_mean": summary.get("ic_mean", 0),
                "ic_std": summary.get("ic_std", 0),
                "ir": summary.get("ir", 0),
                "ic_pos_ratio": summary.get("ic_pos_ratio", 0),
            })
        except Exception as e:
            warning(f"{alpha_class.__name__} 計算失敗: {e}", tag="ALPHA")
    
    # 顯示結果
    table = Table(title="IC/IR Benchmark Results")
    table.add_column("因子", style="cyan")
    table.add_column("類別", style="green")
    table.add_column("IC Mean", justify="right", style="yellow")
    table.add_column("IC Std", justify="right")
    table.add_column("IR", justify="right", style="magenta")
    table.add_column("IC>0%", justify="right")
    
    # 按 IR 絕對值排序
    results.sort(key=lambda x: abs(x["ir"]), reverse=True)
    
    for r in results:
        table.add_row(
            r["name"],
            r["category"],
            f"{r['ic_mean']:.4f}",
            f"{r['ic_std']:.4f}",
            f"{r['ir']:.4f}",
            f"{r['ic_pos_ratio']:.1%}",
        )
    
    console.print(table)
    console.print(f"\n共測試 {len(results)} 個因子")

# Shadow Account CLI commands
shadow_app = typer.Typer(help="Shadow Account 行為診斷")
app.add_typer(shadow_app, name="shadow")


# Agent-in-the-loop backtest CLI commands
backtest_agent_app = typer.Typer(help="Agent-in-the-loop 回測 (13-agent LLM 管線)")
app.add_typer(backtest_agent_app, name="backtest-agent")


@backtest_agent_app.command("run")
def bt_agent_run(
    symbol: str = typer.Option("BTCUSDT", "--symbol", help="交易對"),
    interval: str = typer.Option("30m", "--interval", help="K線間隔"),
    bars: int = typer.Option(100, "--bars", help="回放 bar 數 (不含 warmup)"),
    skip_debate: bool = typer.Option(False, "--skip-debate", help="跳過研究員辯論 (省 ~5 LLM calls/bar)"),
    quiet: bool = typer.Option(False, "--quiet", help="關閉 LLM 流式輸出"),
    resume: bool = typer.Option(False, "--resume", help="跳過 JSONL 已完成的 bar"),
    no_cache: bool = typer.Option(False, "--no-cache", help="禁用 LLM response cache"),
    yes: bool = typer.Option(False, "--yes", help="跳過成本估算確認"),
    bars_path: str = typer.Option("replay/data/bars.json", "--bars-path", help="bars JSON 路徑"),
    log_path: str = typer.Option("replay/data/leg_a_decisions.jsonl", "--log-path", help="決策 JSONL 輸出路徑"),
    usage_db: str = typer.Option("vibe_trading.db", "--usage-db", help="usage ledger db 路徑"),
):
    """運行完整 13-agent LLM 管線逐 bar 回放"""
    from vibe_trading.backtest.agent_models import AgentReplayConfig
    from vibe_trading.backtest.agent_replay import run_replay

    config = AgentReplayConfig(
        symbol=symbol,
        interval=interval,
        bars_path=bars_path,
        start=120,
        end=120 + bars,
        skip_debate=skip_debate,
        quiet=quiet,
        resume=resume,
        use_cache=not no_cache,
        yes=yes,
        log_path=log_path,
        usage_db_path=usage_db,
    )
    asyncio.run(run_replay(config))


@backtest_agent_app.command("report")
def bt_agent_report(
    log_path: str = typer.Argument("replay/data/leg_a_decisions.jsonl", help="決策 JSONL 路徑"),
    symbol: str = typer.Option("BTCUSDT", "--symbol", help="交易對"),
    interval: str = typer.Option("30m", "--interval", help="K線間隔"),
    usage_db: str = typer.Option("vibe_trading.db", "--usage-db", help="usage ledger db 路徑"),
):
    """聚合決策 JSONL 生成 P&L/決策分布/LLM 成本報告"""
    from vibe_trading.backtest.agent_report import build_report, format_report

    result = build_report(
        log_path=log_path,
        symbol=symbol,
        interval=interval,
        usage_db_path=usage_db,
    )
    console.print(format_report(result))


@backtest_agent_app.command("fetch")
def bt_agent_fetch(
    symbol: str = typer.Option("BTCUSDT", "--symbol", help="交易對"),
    interval: str = typer.Option("30m", "--interval", help="K線間隔"),
    days: int = typer.Option(14, "--days", help="回放窗口天數"),
    warmup_bars: int = typer.Option(120, "--warmup-bars", help="warmup bar 數"),
    out: str = typer.Option("replay/data/bars.json", "--out", help="輸出 bars JSON 路徑"),
):
    """從 Binance 抓取歷史 K 線 (public REST, 免 API key)"""
    from vibe_trading.backtest.agent_fetch import fetch_bars

    fetch_bars(symbol=symbol, interval=interval, days=days, warmup_bars=warmup_bars, out=out)


@shadow_app.command("analyze")
def shadow_analyze(
    csv_path: str = typer.Argument(..., help="Binance 交易歷史 CSV 文件路徑"),
    trader_id: str = typer.Option("default", "--trader", "-t", help="交易者 ID"),
    output: str = typer.Option("shadow_report.html", "--output", "-o", help="報告輸出路徑"),
    recommended_daily: int = typer.Option(8, "--recommended-daily", help="建議日均交易次數"),
    chasing_threshold: float = typer.Option(3.0, "--chasing-threshold", help="追漲閾值百分比"),
):
    """分析交易記錄並生成行為診斷報告

    示例:
        vibe-trade shadow analyze trades.csv
        vibe-trade shadow analyze trades.csv -t my_trader -o report.html
    """
    from vibe_trading.backtest.shadow_account import ShadowAccountAnalyzer

    analyzer = ShadowAccountAnalyzer(
        recommended_daily_trades=recommended_daily,
        chasing_threshold_pct=chasing_threshold,
    )

    console.print(f"[bold cyan]Shadow Account Analysis[/bold cyan]")
    console.print(f"CSV: {csv_path}")
    console.print(f"Trader: {trader_id}")
    console.print()

    try:
        report = analyzer.analyze_csv(csv_path, trader_id=trader_id)
    except FileNotFoundError as e:
        warning(str(e), tag="SHADOW")
        raise typer.Exit(code=1)
    except Exception as e:
        warning(f"分析失敗: {e}", tag="SHADOW")
        raise typer.Exit(code=1)

    # 顯示摘要
    profile = report.profile
    console.print(Panel(
        f"[bold]交易者:[/bold] {profile.trader_id}\n"
        f"[bold]分析期間:[/bold] {profile.analysis_period_start.strftime('%Y-%m-%d')} - {profile.analysis_period_end.strftime('%Y-%m-%d')}\n"
        f"[bold]總交易:[/bold] {profile.total_trades} (已平倉: {profile.closed_trades})\n"
        f"[bold]整體偏差分數:[/bold] {profile.overall_score:.2f}/1.00",
        title="[bold cyan]行為剖面[/bold cyan]",
    ))

    # 顯示偏差
    table = Table(title="行為偏差分析")
    table.add_column("偏差類型", style="cyan")
    table.add_column("分數", justify="right")
    table.add_column("描述", style="yellow")

    for bias in profile.biases:
        score_color = "green" if bias.score < 0.4 else ("yellow" if bias.score < 0.7 else "red")
        table.add_row(
            bias.bias_type.value,
            f"[{score_color}]{bias.score:.2f}[/{score_color}]",
            bias.description,
        )

    console.print(table)

    # 顯示反事實
    if report.counterfactual:
        cf = report.counterfactual
        console.print(Panel(
            f"[bold]實際 PnL:[/bold] {cf.actual_pnl:.2f} USDT ({cf.actual_pnl_pct:.2%})\n"
            f"[bold]理想 PnL:[/bold] {cf.ideal_pnl:.2f} USDT ({cf.ideal_pnl_pct:.2%})\n"
            f"[bold]潛在改進:[/bold] [green]+{cf.improvement:.2f} USDT ({cf.improvement_pct:.2%})[/green]",
            title="[bold cyan]反事實分析[/bold cyan]",
        ))

    # 保存報告
    analyzer.save_report(report, output)
    success(f"報告已保存: {output}", tag="SHADOW")

    # 顯示建議
    if report.recommendations:
        console.print("\n[bold]建議:[/bold]")
        for i, rec in enumerate(report.recommendations, 1):
            console.print(f"  {i}. {rec}")

# Research CLI commands
research_app = typer.Typer(help="Hypothesis Registry & Research Goals")
app.add_typer(research_app, name="research")


@research_app.command("hyp-create")
def hyp_create(
    title: str = typer.Argument(..., help="假設標題"),
    description: str = typer.Option("", "--desc", "-d", help="假設描述"),
    tags: str = typer.Option("", "--tags", "-t", help="標籤（逗號分隔）"),
):
    """創建新的研究假設"""
    from vibe_trading.research.registry import HypothesisRegistry

    registry = HypothesisRegistry()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    hyp = asyncio.run(registry.create(
        title=title,
        description=description,
        tags=tag_list,
    ))

    success(f"假設已創建: {hyp.id}", tag="RESEARCH")
    console.print(f"  標題: {hyp.title}")
    console.print(f"  狀態: {hyp.status.value}")
    console.print(f"  標籤: {', '.join(hyp.tags)}")


@research_app.command("hyp-list")
def hyp_list(
    status: str = typer.Option(None, "--status", "-s", help="狀態篩選"),
    tags: str = typer.Option(None, "--tags", "-t", help="標籤篩選（逗號分隔）"),
):
    """列出研究假設"""
    from vibe_trading.research.models import HypothesisStatus
    from vibe_trading.research.registry import HypothesisRegistry

    registry = HypothesisRegistry()
    hyps = asyncio.run(registry.get_all())
    if status:
        status_filter = HypothesisStatus(status)
        hyps = [h for h in hyps if h.status == status_filter]
    if tags:
        tag_list = {t.strip() for t in tags.split(",") if t.strip()}
        hyps = [h for h in hyps if tag_list.issubset(set(h.tags))]

    table = Table(title="研究假設")
    table.add_column("ID", style="cyan")
    table.add_column("標題", style="yellow")
    table.add_column("狀態", style="green")
    table.add_column("標籤", style="magenta")
    table.add_column("更新時間")

    for hyp in hyps:
        table.add_row(
            hyp.id,
            hyp.title,
            hyp.status.value,
            ", ".join(hyp.tags),
            hyp.updated_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
    console.print(f"\n共 {len(hyps)} 個假設")


@research_app.command("alpha-mine")
def alpha_mine(
    symbol: str = typer.Option("BTCUSDT", "--symbol", help="交易對"),
    interval: str = typer.Option("30m", "--interval", help="K線間隔"),
    bars: int = typer.Option(500, "--bars", help="歷史 K 線數"),
    population: int = typer.Option(50, "--population", help="演化池大小"),
    generations: int = typer.Option(20, "--generations", help="演化代數"),
    ic_threshold: float = typer.Option(0.05, "--ic-threshold", help="IC 達標閾值"),
    min_samples: int = typer.Option(20, "--min-samples", help="最小樣本數"),
):
    """演化式因子挖掘 + IC 評分 + 假說庫註冊 (Phase 3, 無 RL)"""
    from vibe_trading.factors.miner import evolve
    from vibe_trading.factors.screener import make_screener, score_formula, passes_gate
    from vibe_trading.factors.vm import ARITY

    # 1. 載入歷史 K 線 (BacktestDataLoader, 與 replay 同資料路徑)
    from vibe_trading.backtest.data_loader import BacktestDataLoader
    loader = BacktestDataLoader()
    klines = asyncio.run(loader.load_klines(symbol=symbol, interval=interval, limit=bars))
    if not klines:
        console.print(f"[red]無法載入 {symbol} {interval} 歷史資料[/red]")
        raise typer.Exit(1)

    # 2. 建構評分器
    screener = make_screener(list(klines))
    features = list(screener["series"].keys())

    def fitness(ast):
        sc = score_formula(ast, screener["series"], screener["fwd"], min_samples=min_samples)
        return abs(sc["ic"]) if sc else None

    info(f"開始演化搜尋: {symbol} {interval} ({len(klines)} bars, "
         f"pop={population}, gen={generations})", tag="MINER")

    # 3. 演化搜尋
    candidates = evolve(features, fitness, population=population,
                        generations=generations, seed=42, top_k=10)

    # 4. 評分 + 達標註冊假說庫
    registry_created = 0
    table = Table(title=f"Alpha Mining 結果 ({symbol} {interval})")
    table.add_column("公式", style="cyan")
    table.add_column("IC", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("樣本", justify="right")
    table.add_column("狀態", style="green")

    for ast, _ic in candidates:
        sc = score_formula(ast, screener["series"], screener["fwd"], min_samples=min_samples)
        if sc is None:
            continue
        formula_str = str(ast)
        passed = passes_gate(sc, ic_threshold)
        status = "✅ 註冊" if passed else "—"
        if passed:
            from vibe_trading.research.registry import HypothesisRegistry
            registry = HypothesisRegistry()
            hyp = asyncio.run(registry.create(
                title=f"Alpha factor: {formula_str[:60]}",
                description=(
                    f"IC={sc['ic']:.4f} Sharpe={sc['sharpe']:.2f} "
                    f"samples={sc['samples']} (mined {symbol} {interval})"
                ),
                tags=["alpha-mining", symbol],
            ))
            registry_created += 1
            status = f"✅ {hyp.id}"
        table.add_row(formula_str, f"{sc['ic']:.4f}", f"{sc['sharpe']:.2f}",
                      str(sc["samples"]), status)

    console.print(table)
    success(f"挖掘完成: {len(candidates)} 候選, {registry_created} 註冊入假說庫", tag="MINER")


@research_app.command("universe-scan")
def universe_scan(
    top_n: int = typer.Option(30, "--top", help="回傳數量"),
    min_volume: float = typer.Option(1_000_000, "--min-volume", help="最低 24h 報價量 (USDT)"),
):
    """動態標的宇宙掃描 (Phase 4.2) — Binance 永續 24h tickers 排名"""
    from vibe_trading.factors.universe import format_universe, rank_universe

    # 免 API key: Binance 公開 REST
    import urllib.request
    import json

    try:
        with urllib.request.urlopen(
            "https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=30
        ) as resp:
            tickers = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        console.print(f"[red]掃描失敗: {e}[/red]")
        raise typer.Exit(1)

    ranked = rank_universe(tickers, top_n=top_n, min_quote_volume=min_volume)
    console.print(format_universe(ranked))
    success(f"掃描完成: {len(tickers)} 個永續交易對 → {len(ranked)} 個符合條件", tag="UNIVERSE")


@research_app.command("manifest-diff")
def manifest_diff(
    a: str = typer.Argument(..., help="manifest A 路徑"),
    b: str = typer.Argument(..., help="manifest B 路徑"),
):
    """比較兩次 run 的方法論指紋 (Phase 4.3)"""
    import json as _json
    from pathlib import Path as _Path

    from vibe_trading.governance.manifest import diff_manifests

    ma = _json.loads(_Path(a).read_text(encoding="utf-8"))
    mb = _json.loads(_Path(b).read_text(encoding="utf-8"))

    if ma.get("manifest_hash") == mb.get("manifest_hash"):
        success("方法論一致 (相同 manifest_hash)", tag="MANIFEST")
        return

    diffs = diff_manifests(ma, mb)
    any_diff = False
    for section, keys in diffs.items():
        if keys:
            any_diff = True
            console.print(f"[yellow]{section} 漂移: {', '.join(keys)}[/yellow]")
    if not any_diff:
        console.print("[yellow]hash 不同但無欄位級差異 (可能是套件版本變更)[/yellow]")
    warning("方法論漂移偵測到", tag="MANIFEST")


@research_app.command("sor-quote")
def sor_quote(
    symbol: str = typer.Option("BTCUSDT", help="標的"),
):
    """跨所最佳報價路由 (Phase 4.1 SOR, dry-run mock)"""
    import asyncio

    from vibe_trading.execution.broker_connector import BrokerConnector, BrokerConfig, BrokerType
    from vibe_trading.execution.bybit_executor import BybitOrderExecutor
    from vibe_trading.execution.sor import SmartOrderRouter
    from vibe_trading.data_sources.binance_client import OrderSide

    # dry-run 執行器 (mock 報價)
    bybit = BybitOrderExecutor(BrokerConfig(
        broker_type=BrokerType.BYBIT, api_key="", api_secret="", dry_run=True,
    ))

    class _MockConnector(BrokerConnector):
        """dry-run mock: 固定報價."""

        async def place_order(self, *args, **kwargs):
            raise NotImplementedError

        async def cancel_order(self, symbol: str, order_id: str) -> bool:
            return True

        async def get_positions(self):
            return []

        async def get_balance(self):
            return {}

        async def close(self) -> None:
            pass

        async def get_mid_price(self, symbol: str) -> float:
            return 67500.0

    hl = _MockConnector()
    router = SmartOrderRouter(
        {BrokerType.BYBIT: bybit, BrokerType.HYPERLIQUID: hl}  # type: ignore[dict-item]
    )

    async def _run() -> None:
        quotes = await router.quotes_all(symbol)
        for broker, price in quotes.items():
            console.print(f"  {broker.value}: {price:.4f}")
        best = await router.best_quote(symbol, OrderSide.BUY)
        if best:
            success(f"最佳 BUY 路由: {best}", tag="SOR")
        else:
            warning("無可用報價 (dry-run 需 mock)", tag="SOR")

    asyncio.run(_run())


@research_app.command("funding-arb")
def funding_arb(
    binance: float = typer.Option(0.0001, help="Binance 8h 資金費率 (小數)"),
    okx: float = typer.Option(0.0002, help="OKX 8h 資金費率"),
    bybit: float = typer.Option(0.00015, help="Bybit 8h 資金費率"),
    bitget: float = typer.Option(0.0001, help="Bitget 8h 資金費率"),
    min_annualized: float = typer.Option(0.10, help="最低年化率閾值"),
):
    """跨所資金費率套利偵測 (Phase 4.1, Delta-Neutral)"""
    from vibe_trading.execution.broker_connector import BrokerType
    from vibe_trading.execution.funding_arb import scan_funding_arb

    rates = {
        BrokerType.BINANCE: binance,
        BrokerType.OKX: okx,
        BrokerType.BYBIT: bybit,
        BrokerType.BITGET: bitget,
    }
    opps = scan_funding_arb(rates, min_annualized=min_annualized)
    if not opps:
        console.print("[dim]無符合閾值的套利機會[/dim]")
        return
    for o in opps:
        console.print(
            f"  long {o.long_broker.value} / short {o.short_broker.value}: "
            f"年化 {o.annualized_rate:.1%} (費率差 {o.spread_bps:.1f}bp)"
        )
    success(f"{len(opps)} 個套利機會 (delta-neutral)", tag="FUNDING-ARB")


@research_app.command("goal-create")
def goal_create(
    title: str = typer.Argument(..., help="研究目標標題"),
    description: str = typer.Option("", "--desc", "-d", help="研究目標描述"),
    checklist: str = typer.Option("", "--checklist", "-c", help="檢查清單項目（逗號分隔）"),
    budget: int = typer.Option(10, "--budget", "-b", help="回測預算次數"),
    tags: str = typer.Option("", "--tags", "-t", help="標籤（逗號分隔）"),
):
    """創建新的研究目標"""
    from vibe_trading.research.goal_manager import GoalManager

    manager = GoalManager()
    checklist_items = [item.strip() for item in checklist.split(",") if item.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    goal = asyncio.run(manager.create(
        title=title,
        description=description,
        checklist_items=checklist_items,
        budget_backtests=budget,
        tags=tag_list,
    ))

    success(f"研究目標已創建: {goal.id}", tag="RESEARCH")
    console.print(f"  標題: {goal.title}")
    console.print(f"  狀態: {goal.status.value}")
    console.print(f"  預算: {goal.budget_backtests} 次回測")
    console.print(f"  檢查清單: {len(goal.checklist)} 項")


@research_app.command("goal-list")
def goal_list(
    status: str = typer.Option(None, "--status", "-s", help="狀態篩選"),
):
    """列出研究目標"""
    from vibe_trading.research.goal_manager import GoalManager
    from vibe_trading.research.models import GoalStatus

    manager = GoalManager()
    goals = asyncio.run(manager.get_all())
    if status:
        status_filter = GoalStatus(status)
        goals = [g for g in goals if g.status == status_filter]

    table = Table(title="研究目標")
    table.add_column("ID", style="cyan")
    table.add_column("標題", style="yellow")
    table.add_column("狀態", style="green")
    table.add_column("進度", justify="right")
    table.add_column("預算使用", justify="right")
    table.add_column("更新時間")

    for goal in goals:
        progress = f"{goal.get_completion_percentage():.0f}%"
        budget = f"{goal.budget_used}/{goal.budget_backtests}"
        table.add_row(
            goal.id,
            goal.title,
            goal.status.value,
            progress,
            budget,
            goal.updated_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
    console.print(f"\n共 {len(goals)} 個目標")

# Swarm Presets CLI commands
swarm_app = typer.Typer(help="Swarm Presets - 可配置管線編排")
app.add_typer(swarm_app, name="swarm")


@swarm_app.command("list")
def swarm_list():
    """列出所有可用的 Swarm 預設"""
    from vibe_trading.coordinator.presets import PresetLoader

    loader = PresetLoader()
    presets = loader.load_builtin_presets()

    table = Table(title="Swarm 預設")
    table.add_column("名稱", style="cyan")
    table.add_column("模式", style="green")
    table.add_column("描述", style="yellow")
    table.add_column("階段數", justify="right")
    table.add_column("超時", justify="right")

    for name, preset in presets.items():
        enabled_phases = len(preset.get_enabled_phases())
        timeout = f"{preset.global_timeout_seconds}s" if preset.global_timeout_seconds else "N/A"
        table.add_row(
            name,
            preset.mode.value,
            preset.description,
            str(enabled_phases),
            timeout,
        )

    console.print(table)
    console.print(f"\n共 {len(presets)} 個預設")


@swarm_app.command("show")
def swarm_show(
    name: str = typer.Argument(..., help="預設名稱"),
):
    """顯示預設詳細配置"""
    from vibe_trading.coordinator.presets import PresetLoader

    loader = PresetLoader()
    presets = loader.load_builtin_presets()

    if name not in presets:
        warning(f"預設 '{name}' 不存在", tag="SWARM")
        raise typer.Exit(code=1)

    preset = presets[name]

    console.print(Panel(
        f"[bold]名稱:[/bold] {preset.name}\n"
        f"[bold]模式:[/bold] {preset.mode.value}\n"
        f"[bold]描述:[/bold] {preset.description}\n"
        f"[bold]全局超時:[/bold] {preset.global_timeout_seconds}s",
        title=f"[bold cyan]Swarm 預設: {name}[/bold cyan]",
    ))

    table = Table(title="階段配置")
    table.add_column("階段", style="cyan")
    table.add_column("啟用", style="green")
    table.add_column("代理數", justify="right")
    table.add_column("超時", justify="right")

    for phase_name, phase_config in preset.phases.items():
        agent_count = len([a for a in phase_config.agents.values() if a.enabled])
        timeout = f"{phase_config.timeout_seconds}s" if phase_config.timeout_seconds else "N/A"
        table.add_row(
            phase_name.value,
            "✅" if phase_config.enabled else "❌",
            str(agent_count),
            timeout,
        )

    console.print(table)


@swarm_app.command("validate")
def swarm_validate(
    name: str = typer.Argument(..., help="預設名稱"),
):
    """驗證預設配置"""
    from vibe_trading.coordinator.presets import PresetLoader

    loader = PresetLoader()
    presets = loader.load_builtin_presets()

    if name not in presets:
        warning(f"預設 '{name}' 不存在", tag="SWARM")
        raise typer.Exit(code=1)

    preset = presets[name]
    issues = loader.validate_preset(preset)

    if not issues:
        success(f"預設 '{name}' 驗證通過", tag="SWARM")
    else:
        warning(f"預設 '{name}' 存在 {len(issues)} 個問題:", tag="SWARM")
        for i, issue in enumerate(issues, 1):
            console.print(f"  {i}. {issue}")

# Strategy Export CLI commands
export_app = typer.Typer(help="策略导出 - 转换为 Pine Script / MQL5")
app.add_typer(export_app, name="export")


@export_app.command("to-pine")
def export_to_pine(
    plan_file: str = typer.Argument(..., help="交易计划 JSON 文件路径"),
    output: str = typer.Option("strategy.pine", "--output", "-o", help="输出文件路径"),
    strategy_name: str = typer.Option("VibeTradingStrategy", "--name", "-n", help="策略名称"),
    author: str = typer.Option("Vibe Trading", "--author", "-a", help="作者"),
):
    """导出交易计划为 Pine Script (TradingView)"""
    import json
    from vibe_trading.exporters import PineScriptExporter, ExportConfig

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except FileNotFoundError:
        warning(f"文件不存在: {plan_file}", tag="EXPORT")
        raise typer.Exit(code=1)
    except json.JSONDecodeError as e:
        warning(f"JSON 格式错误: {e}", tag="EXPORT")
        raise typer.Exit(code=1)

    config = ExportConfig(strategy_name=strategy_name, author=author)
    exporter = PineScriptExporter(config)
    result = exporter.export(plan)

    with open(output, "w", encoding="utf-8") as f:
        f.write(result)

    success(f"Pine Script 已导出: {output}", tag="EXPORT")
    console.print(f"  策略名称: {strategy_name}")
    console.print(f"  作者: {author}")
    console.print(f"  交易对: {plan.get('symbol', 'N/A')}")
    console.print(f"  方向: {plan.get('direction', 'N/A')}")


@export_app.command("to-mql5")
def export_to_mql5(
    plan_file: str = typer.Argument(..., help="交易计划 JSON 文件路径"),
    output: str = typer.Option("strategy.mq5", "--output", "-o", help="输出文件路径"),
    strategy_name: str = typer.Option("VibeTradingStrategy", "--name", "-n", help="策略名称"),
    author: str = typer.Option("Vibe Trading", "--author", "-a", help="作者"),
):
    """导出交易计划为 MQL5 (MetaTrader 5)"""
    import json
    from vibe_trading.exporters import MQL5Exporter, ExportConfig

    try:
        with open(plan_file, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except FileNotFoundError:
        warning(f"文件不存在: {plan_file}", tag="EXPORT")
        raise typer.Exit(code=1)
    except json.JSONDecodeError as e:
        warning(f"JSON 格式错误: {e}", tag="EXPORT")
        raise typer.Exit(code=1)

    config = ExportConfig(strategy_name=strategy_name, author=author)
    exporter = MQL5Exporter(config)
    result = exporter.export(plan)

    with open(output, "w", encoding="utf-8") as f:
        f.write(result)

    success(f"MQL5 已导出: {output}", tag="EXPORT")
    console.print(f"  策略名称: {strategy_name}")
    console.print(f"  作者: {author}")
    console.print(f"  交易对: {plan.get('symbol', 'N/A')}")
    console.print(f"  方向: {plan.get('direction', 'N/A')}")


if __name__ == "__main__":
    app()
