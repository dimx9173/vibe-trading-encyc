# 阶段 1 规格：规则层主引擎 + LLM Regime Gate 接线

> 上游文档：[money-printer-convergence-plan.md](money-printer-convergence-plan.md) 第 3 节。
> 本文档把阶段 1 落到具体文件、函数与测试，达到可直接开发的程度。
> 调查日期：2026-08-28（基于 commit `8ecf129` 工作区）。

## 1. 目标与非目标

**目标**（对应收敛计划阶段 1 验收）：

- 自动交易回路改为规则层直驱：`AlphaZoo 因子 → 信号 → Half-Kelly 仓位 → Grounding Gate → ExitLadder 出场`
- 标的扩为 `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`，30m bar
- LLM 仅保留每小时一次 macro regime 判定，输出收敛为 `RISK_ON / NEUTRAL / RISK_OFF`；`RISK_OFF` 禁开新仓，既有持仓出场不受影响
- 12-agent 辩论链退出所有自动回路，保留 `vibe-trade analyze` 与 `backtest-agent run` 手动入口（Q9：代码保留）

**非目标**（本阶段不做）：

- EvidenceGate→回路的自动卡关整合（属阶段 3 blocker，见 deployment-checklist.md:69）；本阶段只保留其手动调用能力
- 调因子/出场/仓位参数以追求绩效（属阶段 2 回测不过时的修法）
- 删除 TradingCoordinator / SharedStateManager / StateMachine（留码不跑）
- backtest/engine.py 的 MA 金叉引擎改造（它是基线工具，不进本回路）

## 2. 现状关键事实（开发前必读）

| 组件 | 位置 | 状态 |
|---|---|---|
| AlphaZoo 因子 | `backend/src/vibe_trading/data_sources/alphas/zoo.py:17`，`calculate(klines) -> Dict[str, float]`，23 因子 | 无信号逻辑，仅以文本摘要进 PM prompt（trading_coordinator.py:757） |
| Half-Kelly | `backend/src/vibe_trading/execution/position_sizing.py:61` `calculate_atr_position_size(...)` | **孤儿**，仅 tests 引用；另有 3 条旧 Kelly 路径并存（risk_manager.py:78、quantlib/capital.py:12、agents/decision/trading_tools.py:309），本阶段不动它们 |
| Grounding Gate | `backend/src/vibe_trading/execution/grounding_gate.py:41` `validate_trading_plan_prices(...)` | 已接入 LLM 回路（trading_coordinator.py:794），可直接复用 |
| ExitLadder | `execution/exit_ladder.py`：简单版 `update_exit`（:30）已被 `PaperOrderExecutor._run_exit_ladder`（order_executor.py:452）内嵌调用；三级版 `ExitLadderEngine.evaluate_position`（:112）是孤儿 | 见 §5 的双重出场冲突处理 |
| EvidenceGate | `backend/src/vibe_trading/data_sources/evidence_gate.py:67` | 孤儿，阶段 3 才接 |
| Macro 判定 | `agents/macro_agent.py:123 analyze()`，输出 `BULL/BEAR/NEUTRAL`，存 `MacroStorage`（macro_storage.py:21） | **写了没人读**：自动回路不消费 macro state |
| 自动回路挂点 | `threads/onbar_thread.py:316` 调 `coordinator.analyze_and_decide()` | 12-agent 链进自动回路的唯一入口 |
| 多标的截断 | `cli.py:163` 只取 `symbols[0]` | `config/settings.py:49` 已有 `symbols` 列表与 `SYMBOLS` 环境变量 |
| regime gate | 不存在 | 全仓 grep `RISK_OFF` 零命中，全新代码 |
| Paper 执行器 | `execution/order_executor.py:115`，`update_price()`（:201）内触发 trailing stop + 简单 ExitLadder + 条件单撮合 | replay 喂价即调 `update_price`（replay_leg_a.py:153） |
| 下单唯一路径 | `agents/agent_tools.py:648` `create_submit_trade_order_tool()`（PreTradeRiskGate → ExchangeFilterValidator → executor） | LLM tool 形态，规则层不经此路径，直接调 executor + PreTradeRiskGate |

## 3. 新模块：`rule_engine/`

新建 `backend/src/vibe_trading/rule_engine/`，三个文件，均为**纯函数/薄状态**设计，不 import TradingCoordinator。

### 3.1 `rule_engine/signal.py` — 因子→信号

```python
@dataclass
class RuleSignal:
    direction: Literal["LONG", "SHORT", "FLAT"]
    strength: float          # |composite|，供 sizing 参考
    composite: float         # tanh 归一化动量综合分 [-1, 1]
    fake_breakout_warning: bool
    reason: str              # 人读日志/TG 用

def generate_signal(factors: Dict[str, float]) -> RuleSignal
```

- 综合分复用 `tools/technical_tools.py:574 get_alpha_factor_summary` 里 `momentum_score` 的 tanh 归一化逻辑（抽成可复用函数，避免复制）。
- 入场阈值：`composite ≥ +0.3` → LONG；`composite ≤ -0.3` → SHORT；其余 FLAT。阈值放 `RuleEngineConfig`（§3.4），阶段 2 调参只改配置。
- `fake_breakout_warning=True` 时降级为 FLAT（假突破过滤，复用 zoo 因子 `fake_breakout_warning` 语义）。
- 因子不足（`AlphaZoo.calculate` 返回 `{}`，<50 根 bar）→ FLAT。
- 纯函数，全部边界由单测覆盖（§7）。

### 3.2 `rule_engine/regime_gate.py` — 三态闸门

```python
class Regime(Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"

def map_macro_to_regime(market_regime: str, trend_strength: float,
                        sentiment: str) -> Regime   # BULL/BEAR/NEUTRAL → 三态

async def current_regime(macro_storage: MacroStorage,
                         max_age_seconds: int = 7200) -> Regime
```

- 映射规则（初版，阶段 2 可凭事后标注修正）：`BULL → RISK_ON`；`BEAR 且 trend_strength ≥ 0.6 → RISK_OFF`；其余（含 BEAR 弱趋势、NEUTRAL）→ `NEUTRAL`。
- **fail-safe**：无 macro state 或超过 `max_age_seconds`（默认 2h，macro 线程 1h 一跑）→ 返回 `NEUTRAL`，不返回 RISK_ON。
- `RISK_OFF` 语义只有一条：**禁开新仓**；出场评估照常进行。
- `NEUTRAL`  semantics：允许开仓但 sizing 的 `risk_multiplier` 打 0.5 折（半仓），对应收敛计划"NEUTRAL 降档"意图——若计划无此意，开发时以本行为准并在 PR 描述中标注。

### 3.3 `rule_engine/loop.py` — on-bar 主回路

```python
class RuleEngineLoop:
    def __init__(self, symbol: str, interval: str, storage: KlineStorage,
                 executor: OrderExecutor, macro_storage: MacroStorage,
                 config: RuleEngineConfig): ...

    async def on_bar(self, kline: Kline) -> RuleDecision  # bar 收盘触发
```

每根收盘 bar 的顺序（写死，不可跳过）：

1. `storage.store_kline(kline)`（store-before-decide，沿用 replay 防 look-ahead 纪律）
2. `executor.update_price(symbol, kline.close)`（paper 模式完成该 bar 撮合）
3. **出场评估**：若有持仓 → `ExitLadderEngine.evaluate_position(...)`（§5），需平则下 reduce_only 单，本 bar 结束
4. **regime gate**：`current_regime(...)` == `RISK_OFF` → 记日志 + `RuleDecision(blocked_by="RISK_OFF")`，结束
5. **信号**：`AlphaZoo.calculate(recent_klines)` → `generate_signal`；FLAT → 结束
6. **仓位**：`calculate_atr_position_size(equity, confidence=strength, entry, sl, tp, atr)`，NEUTRAL 时 `risk_multiplier × 0.5`；SL/TP 由 `1.5×ATR / 2.5×ATR` 结构价给出（与 ExitLadderEngine 的 R 倍数口径一致）
7. **grounding**：`validate_trading_plan_prices(plan, bar_low, bar_high, close)`；违规 → 放弃开仓并记录
8. **下单**：`PreTradeRiskGate.validate_order` → `executor.place_order`（不经 LLM tool 路径，但复用同一风险门与审计存储 `ExecutionAuditStorage`）

`RuleDecision` dataclass 记录每 bar 全貌（regime/signal/qty/blocked_by/reason），供日志、replay JSONL 与测试断言。

### 3.4 `rule_engine/config.py`

`RuleEngineConfig`：entry_threshold=0.3、atr_period=14、sl_atr_mult=1.5、tp_atr_mult=2.5、neutral_risk_scale=0.5、macro_max_age_seconds=7200、max_single_notional=500.0。从 `config/settings.py` 读取，环境变量前缀 `RULE_`。

## 4. 既有文件改动清单（最小集）

| 文件 | 改动 |
|---|---|
| `threads/onbar_thread.py` | `_process_kline`（:261）把 `coordinator.analyze_and_decide()`（:316）换成 `rule_engine_loop.on_bar(kline)`；coordinator 不再注入本线程 |
| `main/multi_thread_main.py` | `__init__` 收 `symbols: List[str]`；每 symbol 装一个 OnBarThread + RuleEngineLoop；trigger 按 symbol 注册 |
| `cli.py` | `start`（:163）删掉 `symbols[0]` 截断，传整个列表；`analyze`（:298）保持原样（手动 12-agent 入口） |
| `agents/macro_agent.py` | prompt 输出格式收敛为三态：`_parse_analysis`（:262）增加 `RISK_ON/NEUTRAL/RISK_OFF` 解析，写入 `MacroState.market_regime` 列（**不换列名**，值域变更，旧值 BULL/BEAR 由 `map_macro_to_regime` 兼容读取） |
| `threads/macro_thread.py` | 无逻辑改动；确认 `_notify_update` 广播照旧（规则回路自己读 storage，不依赖广播） |
| `config/settings.py` | `symbols` 默认改为 `["BTCUSDT","ETHUSDT","SOLUSDT"]`，`interval` 确认 30m；加 `RuleEngineConfig` 装载 |
| `execution/order_executor.py` | `PaperOrderExecutor.__init__` 加 `enable_exit_ladder: bool = True`；规则回路驱动时传 `False`（§5） |

不改：`trading_coordinator.py`（留码）、`evidence_gate.py`（阶段 3）、`backtest/engine.py`、三套旧 Kelly 路径。

## 5. 出场双重触发冲突（必须处理）

`PaperOrderExecutor.update_price` 内部已跑简单版 ExitLadder（order_executor.py:452）与 trailing stop。规则回路若同时用 `ExitLadderEngine` 评估出场，会**同一持仓两套出场逻辑双发**。

**裁决**：出场单一权威是规则回路的 `ExitLadderEngine`（三级阶梯版，tests 18 用例 + replay 实战验证）：

- `PaperOrderExecutor` 加 `enable_exit_ladder=False` 开关，规则回路创建的 executor 关闭内部简单 ladder；trailing stop 同理加 `enable_trailing_stop=False` 或确认其注册点仅由 LLM 回路设置（开发时先查 `_check_trailing_stops` 的注册来源再定，若只由 LLM 决策注册则无需开关）
- `ExitLadderEngine` 的 per-position 状态（`LadderStage`、highest/lowest、stop）存内存 dict + 随 `RuleDecision` 落日志；paper 账户重启恢复时从 `paper_account.json` 持仓重建 `LadderStage.TP1` 初始态
- Live 模式（BinanceOrderExecutor）无内嵌 ladder，天然无冲突

## 6. Macro 线程：输出收敛细节

- prompt 改为要求首行输出 `REGIME: RISK_ON|NEUTRAL|RISK_OFF`；`_parse_analysis` 优先解析该行，**解析失败回退旧 BULL/BEAR/NEUTRAL 行解析**（兼容期，避免 LLM 输出漂移导致 macro state 断更）
- 存储复用 `macro_states.market_regime` 列，无 migration；读取侧 `map_macro_to_regime` 同时接受新旧两套值
- 手动入口 `vibe-trade macro`（cli.py:367）不变

## 7. 测试计划

新增 `tests/test_rule_engine_signal.py`：

- 阈值边界：composite = 0.3/0.299/-0.3 的方向判定
- 因子不足（{}）→ FLAT；fake_breakout_warning → FLAT
- 纯函数：构造 factors dict 直测，不碰 storage

新增 `tests/test_regime_gate.py`：

- 映射表全覆盖（BULL/BEAR×强弱趋势/NEUTRAL/旧值兼容）
- fail-safe：无 state、过期 state → NEUTRAL（模式照 `tests/test_macro_thread.py:76` 的 AsyncMock）

新增 `tests/test_rule_engine_loop.py`（核心验收）：

- **RISK_OFF 挡开仓**：mock macro state = RISK_OFF + 强 LONG 信号 bar → 断言 `executor.get_positions()` 为空、`RuleDecision.blocked_by == "RISK_OFF"`（断言结构照 `tests/test_grounding_gate.py:69 TestCoordinatorDegradation`）
- RISK_OFF 不挡出场：有持仓 + RISK_OFF + 出场条件 → 断言平仓发生
- NEUTRAL 半仓：同一信号下 NEUTRAL 的 qty 为 RISK_ON 的一半（±1%）
- 出场单一权威：`enable_exit_ladder=False` 时 update_price 不触发内部平仓
- store-before-decide：断言 storage 中本 bar 在决策前已写入

回归：`tests/test_macro_thread*.py`、`tests/test_paper_executor_internals.py`（executor 新开关默认 True，行为不变）、`tests/test_coordinator_decision.py`（coordinator 不动）。

## 8. Replay 烟雾测试（验收）

1. 补数据：`python replay/fetch_bars.py --symbol ETHUSDT --days 7 --out replay/data/bars_eth_7d.json`，SOLUSDT 同（BTC 用既有 `bars.json`）
2. `replay/replay_leg_a.py` 骨架复制为 `replay/replay_rule_engine.py`：symbol 参数化（现有 7 处 BTCUSDT/30m 硬编码：:35,:111,:123,:127,:152,:153,:169），驱动 `RuleEngineLoop.on_bar` 而非 `analyze_and_decide`；复用 `replay/replay_tool_isolation.py` 无必要（规则回路不调 live 工具），直接构造 PaperOrderExecutor
3. 三币各跑一遍：确认无异常、有 `RuleDecision` JSONL 产出
4. **RISK_OFF 注入演练**：macro_storage 预置 RISK_OFF state 后重跑 BTC 段，断言全程零新开仓

## 9. 验收清单（对照收敛计划 §3）

- [ ] `vibe-trade start BTCUSDT ETHUSDT SOLUSDT` 三标的 30m 规则回路运行，不再触发任何 LLM agent（日志佐证）
- [ ] 每小时 macro 判定产出三态 regime 并落 `macro_states`
- [ ] RISK_OFF 注入 replay：零新开仓、既有持仓正常出场
- [ ] `vibe-trade analyze` 手动 12-agent 链路仍可用
- [ ] `uv run pytest tests/ -x -q` 全绿；`ruff check backend/src/` 与 `mypy backend/src/` 无新增错误

## 10. 开发顺序建议

1. `signal.py` + 单测（纯函数，无依赖）
2. `regime_gate.py` + macro_agent 输出收敛 + 单测
3. `loop.py` + executor 开关 + 单测（含 RISK_OFF 挡仓）
4. onbar_thread / multi_thread_main / cli 接线 + 回归测试
5. replay 烟雾三币 + RISK_OFF 注入演练
