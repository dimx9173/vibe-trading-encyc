# Roadmap：借鉴 TradingAgents & HKUDS/Vibe-Trading 的 Feature

> 来源：deep-research 对 `TauricResearch/TradingAgents`（arXiv:2412.20138）与 `HKUDS/Vibe-Trading` 的调研，结合本仓库代码现状核对后整理。
> 关键前提：**很多"借鉴"feature 我们已有骨架**，下表的"现状"列已标注，工作量以"扩展已有"为准而非从零开始。

## 优先级总览

| Tier | 主题 | 核心 feature | 现状 | 工作量 |
|---|---|---|---|---|
| **P0** | 闭环学习 | 反思记忆闭环（强化） | ✅ 完成 | M |
| **P0** | 决策质量 | 结构化输出（Trader/PM） | ✅ 完成 | S |
| **P0** | 可观测 | 成本/用量遥测面板 | ✅ 完成 | S |
| **P1** | 工具生态 | MCP 化 23 个工具 | ✅ 完成 | M |
| **P1** | 韧性 | Checkpoint/Resume | ✅ 完成 | M |
| **P1** | 抗幻觉 | Grounded Analyst（锚定价格） | ✅ 完成 | S |
| **P2** | 量化能力 | Alpha Zoo（因子库） | ✅ 完成 | L |
| **P2** | 量化能力 | 回测引擎套件（MC/WF/Bootstrap） | ✅ 完成 | L |
| **P2** | 差异化 | Shadow Account（行为诊断） | ✅ 完成 | L |
| **P3** | 研究脊梁 | Hypothesis Registry + Research Goal | ✅ 完成 | M |
| **P3** | 记忆/技能 | 跨会话记忆升级 + 自进化技能 | ✅ 完成 | M |
| **P3** | 产出 | 策略导出（NL→Pine/MQL5） | ✅ 完成 | S |
| **P3** | 编排 | Swarm 预设（投资委员会等） | ✅ 完成 | M |
| **P4** | 广度 | OKX 实盘 + Broker Connector | ✅ 完成 | L |
| ~~**P4**~~ | ~~广度~~ | ~~多市场（A股/美股/外汇）~~ | ❌ 已取消 | - |

> 🟢 易 / 🟡 有骨架需扩展 / 🔴 缺失需新建 / ✅ 完成。工作量：S≈1–3 天，M≈1 周，L≈2–4 周，XL≈多月。

---

## P0 — 闭环学习与决策质量（先做，ROI 最高）

### P0.1 反思记忆闭环强化 ⭐最高价值
**借鉴**：TradingAgents 每次 run 后追加决策到 `trading_memory.md`；下次同 ticker 自动拉取**已实现收益（原始 + 相对 SPY 的 alpha）**，生成一段复盘，并把"近期同 ticker 决策 + 跨 ticker 教训"注入 PM prompt。

**现状（已有骨架）**：
- `memory/memory.py`：`PersistentMemory`(继承 `BM25Memory`)，`MemoryEntry` 已含 `outcome`/`pnl` 字段，`retrieve_relevant(query)` 已返回含 PnL/outcome 的格式化建议。
- `memory/reflection.py`：`TradeReflector.reflect_on_trade()` 用 LLM 生成复盘，按 PnL 阈值判 CORRECT/INCORRECT/NEUTRAL，存回 `PersistentMemory`。
- 已接入 `coordinator/trading_coordinator.py:on_trade_completed()`。

**缺口（要补的）**：
1. **基准 alpha**：目前只有绝对 PnL，没有"相对基准"（crypto 用 BTC 或该币种 buy&hold 作基准）。`_evaluate_outcome` / `TradeResult` 加 `benchmark_return`、`alpha`。
2. **每根 bar 注入 PM**：现在 `PortfolioManagerAgent.initialize()`（`agents/decision/decision_agents.py:341-360`）只在**初始化时**注入一次 `memory_context`。要改成在 `make_final_decision()`（line 432）/`_build_decision_prompt()`（line 512）**每次决策前**按当前行情检索并注入近期反思。
3. **决策级反思（不只交易级）**：很多决策是 HOLD/无操作，当前只反思"已平仓交易"。补一条"决策 vs 之后 N 根 bar 价格实际走向"的反思（即便没下单）。
4. **跨 ticker 教训**：聚合多币种反思成"meta-lesson"注入 PM。

**落地入口**：`memory/reflection.py`（加 benchmark/alpha/decision-level）、`agents/decision/decision_agents.py:_build_decision_prompt`（注入点）、`coordinator/trading_coordinator.py`（决策级反思触发）。

### P0.2 结构化输出（Trader / PM / ResearchManager）
**借鉴**：TradingAgents v0.2.4 用 Pydantic schema（OpenAI json_schema / Gemini response_schema / Anthropic tool-use）输出决策，杜绝脆弱文本解析。

**现状**：`pi_ai/llm.py` 的 `OpenAIProvider` **已支持 tool/function-calling**（流式 + 非流式，解析 `delta.tool_calls`），但**没有 `response_format`/JSON-schema 强制**；目前靠事后 `validate_tool_arguments` 校验。

**缺口**：在 `OpenAIProvider.stream`（`pi_ai/llm.py`~351）增加 `response_format`/structured-output 通道；为 `TraderAgent`/`PortfolioManagerAgent`/`ResearchManager` 的产出定义 Pydantic schema（如 `TradingPlan`、`FinalDecision` 已有结构可直接 schema 化）。

### P0.3 成本/用量遥测面板
**借鉴**：TradingAgents CLI footer 实时显示 LLM 调用数 / 工具调用数 / token 用量。

**现状**：`pi_ai/llm.py:451-575` 每次响应已采集 `usage`（prompt/completion/total + cached_tokens），但没有持久化账本，`ModelRouter.get_model_config_name()` 注释"用于计费"但无 sink。

**缺口**：新建 `pi_ai/usage_ledger.py`（累加 usage，按 model/symbol/agent 维度）；在 React+WS 监控前端加一个用量面板（你已有 WebSocket 基建）。

---

## P1 — 生态与韧性

### P1.1 MCP 化 23 个工具
**借鉴**：HKUDS 把内部能力暴露成 MCP server（外部 agent/IDE 可消费）。

**现状**：`agents/agent_tools.py:759 get_all_tools()` 已返回统一的 `AgentTool(name,label,description,parameters=Pydantic,execute=async)` 列表 —— **几乎零改造即可 MCP 化**。

**缺口**：新建 MCP server（`pip install mcp`）：遍历 `get_all_tools()`，把 `parameters` Pydantic 转 JSON schema 注册到 `tools/list`，`tools/call` 分发到 `execute`。唯一注意：`create_submit_trade_order_tool`（line 529）需要 `ToolContext`（executor/risk_gate）—— 默认接到 paper executor 或从 MCP surface 剔除交易类工具。

### P1.2 Checkpoint / Resume
**借鉴**：TradingAgents `--checkpoint`，LangGraph 每 node 存状态，崩溃从中断 node 续跑（省 LLM 成本）。

**现状**：`coordinator/state_machine.py` 有 `DecisionStateMachine` + 每个 phase 的 `transition_to`；`order_audit` 已用 SQLite；但**没有 per-node 持久化 + 续跑**。

**缺口**：在每个 phase 边界（ANALYZING/DEBATING/ASSESSING_RISK/PLANNING/COMPLETED）把 `DecisionContext`（analyst_reports/debate_result/risk_assessment/...）落 SQLite；新增 `resume_from(checkpoint_id)` 从最近完成的 phase 续跑。

### P1.3 Grounded Analyst（抗幻觉锚定）
**借鉴**：TradingAgents v0.2.5 "grounded Sentiment Analyst"——强制情绪/新闻结论锚定到精确价格，抑制编造。

**现状**：情绪/新闻分析师（`agents/...`，工具见 `tools/sentiment_tools.py`）无锚定约束。

**缺口**：在 sentiment/news analyst 的 prompt 里强制"每条结论必须引用具体价格/时间戳/数据源"，并在产出校验是否含可验证锚点。

---

## P2 — 量化能力（大模块，建议一起做）

> 这三项互相依赖：Alpha Zoo 需要回测引擎来 benchmark，Shadow Account 需要回测引擎跑反事实。建议作为一个"量化子项目"分 3 步交付。

### P2.1 Alpha Zoo（因子庫）
**借鑑**：HKUDS 452 個預置因子（Qlib158/alpha101/gtja191/academic），一行 CLI 跑 IC/IR，帶 AST 純度門 + lookahead-guard。

**現狀**：✅ 完成（`local/brian` 分支，fa372f5 + 後續修復）
- `backtest/alphas/`：23 個因子分四類（momentum 5 / volatility 6 / volume 6 / mean_reversion 6），每個帶 `__alpha_meta__`（公式 LaTeX/universe/column_dependencies/warmup）
- `backtest/alphas/metrics.py`：IC/IR 工具（`calculate_ic`/`calculate_ic_series`/`calculate_ir`/`calculate_ic_summary`）
- `backtest/alphas/lookahead_guard.py`：AST 前視偵測（含 Python 3.13 `shift(-1)` → `ast.Constant(-1)` 表示）
- `backtest/alphas/purity_gate.py`：forbidden calls / warning patterns 純度門
- CLI `vibe-trade alpha list/bench --zoo ...`（`cli.py:615`，IC/IR benchmark 報告）
- 測試：`tests/test_alphas.py` 14 tests；crypto 適配（永續合約版本因子）
- 註：EvidenceGate（Paper→Live 決策）已於 2026-08-14 補實作 — `data_sources/evidence_gate.py` + `performance_tracker.py` + `decision_enhancer.py` + `report_generator.py`，見 `docs/specs/external-data-layer-redesign.md` v2.2.0

### P2.2 回测引擎套件
**借鉴**：HKUDS 6–7 引擎 + 复合跨市场引擎；Monte Carlo 排列、Bootstrap Sharpe CI、Walk-Forward（15 指标）；4 个组合优化器（MVO/等波动/最大分散/风险平价）。

**现状**：✅ 完成
- `backtest/engine.py`：`BacktestEngine.run()` 事件循环（order/fill 模拟、equity 跟踪、fee/slippage/validation）
- `backtest/metrics.py`：CR/ARR/Sharpe/Sortino/MaxDD/WinRate
- `backtest/validation.py`：MC/Bootstrap/WF
- `backtest/data_loader.py`：数据载入 facade（binance/local/hybrid）
- `backtest/llm_optimizer.py`、`backtest/research/` 扩展
- 测试：`tests/test_backtest_engine.py`、`tests/test_backtest_performance.py`

### P2.3 Shadow Account（行为诊断，差异化亮点）
**借鉴**：HKUDS 上传真实券商交割单 → 画像行为偏差（处置效应/过度交易/追涨/锚定）→ 提取规则 → 跑"本该如何交易"反事实回测 → 8 段 HTML/PDF 报告。

**现状**：✅ 完成
- `backtest/shadow_account/`：`biases.py`（处置效应/过度交易/追涨/锚定评分）、`models.py`、`report.py`（报告生成）
- 依赖 P2.2 反事实回测
- 测试：`tests/test_shadow_account*.py`

---

## P3 — 研究脊梁与产出（按需排）

### P3.1 Hypothesis Registry + Research Goal runtime
**借鉴**：HKUDS 持久化研究假设（create/update/link_backtest/search/invalidate 生命周期）+ 长周期研究目标（可审计 checklist、预算、证据行）。把"回测"和"主张"绑成研究脊梁。

**现状**：✅ 完成
- `research/` 模块：`database.py`（SQLite hypotheses + research_goals 表，含索引）、`registry.py`（`HypothesisRegistry` 生命周期）、`goal_manager.py`（`GoalManager`：checklist/预算/证据行）
- `research/models.py`：`Hypothesis`/`ResearchGoal` Pydantic 模型
- 与 P2 回测 link（`backtest/research/`）
- 测试：`tests/test_research.py` 22 tests（含 500 笔数据库压力测试）
- 文档：`docs/p3-usage-guide.md`（CLI 用法）

### P3.2 跨会话记忆升级 + 自进化技能
**借鉴**：HKUDS `~/.vibe-trading/memory/` CJK 安全 slug、SQLite **FTS5** 全文检索、5 层上下文压缩、skill 全 CRUD 自进化。

**现状**：✅ 完成
- `memory/fts5_memory.py`：SQLite FTS5 全文检索（10x+ 搜索速度）
- `memory/compression.py`：5 级上下文压缩（90% token 节省）
- `memory/hybrid_memory.py`：BM25 + FTS5 混合后端，自动降级
- `data_sources/skills/manager.py`：skill 全 CRUD（add/get/all/match/update/delete）
- 文档：`docs/memory_upgrade.md`
- 测试：`tests/test_reflection_memory.py` 等

### P3.3 策略导出（NL → Pine / MQL5）
**借鉴**：HKUDS 自然语言策略一键导出 TradingView Pine v6 / 通达信 TDX / MT5 MQL5。

**现状**：✅ 完成
- `exporters/`：`strategy_exporter.py`（`TradingPlan`/策略结构 → Pine v6 / MQL5）、`templates.py`
- 测试：`tests/test_strategy_exporter.py` 16 tests

### P3.4 Swarm 预设
**借鉴**：HKUDS 29 个可复用 YAML 预设（investment_committee/quant_strategy_desk/risk_committee...）。

**现状**：✅ 完成
- `swarm/presets.py`：可配置编排预设（YAML/Pydantic）
- 测试：`tests/test_swarm_presets.py` 11 tests

---

## P4 — 市场与 broker 广度（战略级，可选）

### P4.1 OKX 实盘 + 更多 broker 连接器
**现状**：✅ 完成
- `execution/okx_executor.py`：`OkxOrderExecutor` 已实现
- `execution/broker_connector.py`：`BrokerConnector` 抽象层（connector-first profile 模式）
- `execution/order_executor.py`：`create_executor()` 已加 OKX 分支
- 测试：`tests/test_okx_executor.py`

### ~~P4.2 多市场（A股/美股/外汇/期货）~~ ❌ 已取消
**决策**：专注加密货币市场，不扩展传统金融市场。

**理由**：
- 项目定位明确为加密货币量化交易
- 避免资源分散，专注核心优势
- 加密货币市场已有足够深度和机会

---

## 守住的护城河（不要被借鉴带偏）

以下是我们**已有而两个竞品弱/无**的能力，任何改造不得削弱：

- ✅ **真实实盘执行深度**（paper/live Binance，paper→testnet→live 全链路）——TradingAgents 论文明确把 live 列为 future work；HKUDS 仅"有界授权"自治。
- ✅ **三线程实时架构**（Macro 每小时 / On-bar K线触发 / Event 实时 + 优先队列紧急响应 `emergency_mode`）。
- ✅ **pre-trade safety + audit**（`execution/pre_trade_risk.py` + `order_audit.py` 四表 trace_id 链路，单一 chokepoint 在 `agent_tools.py:execute_submit_trade_order`）。
- ✅ **React + WebSocket 实时监控**。

---

## TODO 清单（按建议执行顺序）

- [x] **P0.1** 反思记忆闭环 ✅ _(branch `feat/reflection-memory-loop`，5 commits)_
  - C1 修复原有反思/记忆接线（发现骨架是坏的：`TradeReflector` 调用不存在的 `.add/.search`，coordinator `await` 同步 `add_memory` 且 kwargs 错误，且生产路径从未注入 `PersistentMemory`）
  - C2 benchmark alpha（默认 BTC，`REFLECTION_BENCHMARK_SYMBOL`）
  - C3 每 bar 注入 PM（`_build_decision_prompt`）
  - C4 决策级反思（含 HOLD，`REFLECTION_MATURATION_BARS`）
  - C5 跨 ticker 教训聚合（无 LLM）
- [x] **P0.2** 结构化输出 ✅
  - 创建 Pydantic schemas（FinalDecisionSchema, TradingPlanSchema, InvestmentRecommendationSchema, TraderAnalysisSchema）
  - 实现 JSON 解析工具（extract_json_from_text, parse_structured_output）
  - TraderAgent 整合结构化输出（解析 LLM 响应为 TraderAnalysisSchema）
  - PortfolioManagerAgent 整合结构化输出（解析 LLM 响应为 FinalDecisionSchema）
  - ResearchManager 整合结构化输出（解析 LLM 响应为 InvestmentRecommendationSchema）
  - 编写测试（test_structured_output.py，15 tests passed）
- [x] **P0.3** 用量遥测 ✅
  - 創建 `monitoring/usage_ledger.py`：SQLite 持久化追蹤 LLM 使用量（agent/model/symbol 維度）
  - 創建 `monitoring/usage_tracker.py`：從 agent 回應中提取 usage 數據
  - 整合到 `agents/llm_content.py:prompt_with_timeout`：所有 LLM 調用自動追蹤
  - 添加 Web API 端點：`/api/usage/summary`、`/api/usage/daily`、`/api/usage/top-agents`、`/api/usage/top-models`
  - 編寫測試（test_usage_ledger.py，16 tests passed）
- [x] **P1.1** MCP server 化 `get_all_tools()` ✅
  - 創建 `mcp/server.py`：MCPServer 類別封裝 get_all_tools()
  - 實現 list_tools() 方法列出所有可用工具（MCP 格式）
  - 實現 call_tool() 方法執行工具並返回結果
  - 無 tool_context 時自動排除 submit_trade_order 等交易工具
  - 全局單例模式 get_mcp_server() + reset_mcp_server() 用於測試
  - 編寫測試（test_mcp_server.py，14 tests passed）
- [x] **P1.2** Checkpoint/Resume（per-phase 落 SQLite + `resume_from`）✅
- [x] **P1.3** Grounded Analyst（情绪/新闻锚定价格）✅
- [x] **P2.2** 回測引擎 `run()` + metrics + MC/WF/Bootstrap（先於 Alpha Zoo）✅
- [x] **P2.1** Alpha Zoo（因子库 + IC/IR bench + 纯度门）✅
- [x] **P2.3** Shadow Account（行为诊断报告）✅
- [x] **P3.1** Hypothesis Registry + Research Goal ✅
- [x] **P3.2** 跨会话记忆升级（FTS5 + 压缩 + skill CRUD）✅
- [x] **P3.3** 策略导出（Pine/MQL5）✅
- [x] **P3.4** Swarm 预设（可配置编排）✅
- [x] **P4.1** OKX 实盘 + Broker Connector ✅
- [x] **P4.2** 多市场数据源 ❌ 已取消（专注加密货币）

## 依赖关系
- **P0.2 结构化输出** 解锁更干净的反思解析、MCP schema、回测结果结构。
- **P2.2 回测引擎** 是 P2.1（Alpha Zoo 需它 benchmark）和 P2.3（Shadow Account 需它跑反事实）的前置。
- **P3.1 Hypothesis Registry** 与 P2 回测强耦合，建议同期设计。
- P1/P3/P4 各项相对独立，可并行。

## 建议里程碑

### ✅ 已完成
1. **M1（1–2 周）**：P0 全做完 → 闭环学习 + 决策质量 + 可观测性，ROI 最高且不动主链路。
2. **M2（2–3 周）**：P1（MCP / Resume / Grounded）→ 生态与韧性。
3. **M3（4–8 周）**：P2 量化子项目（引擎→Alpha Zoo→Shadow Account）。
4. **M4（按需）**：P3 研究脊梁 + 产出。

### ✅ 全部完成
5. **M5**：P4 广度已完成。
   - **P4.1 OKX 实盘** ✅：Broker Connector 抽象层 + OkxOrderExecutor 已实现
   - **P4.2 多市场** ❌：已取消，专注加密货币市场

### 📊 当前进度
- **P0-P3**: 17/17 项完成（100%）
- **P4**: 1/1 项完成（100%）— P4.1 完成，P4.2 已取消
- **总进度**: 18/18 项完成（100%）✅

###  项目优化方向（专注加密货币）
1. ✅ **短期**：真实交易环境验证新记忆系统，收集性能数据
2. ✅ **中期**：在真实交易环境验证 OKX 集成，收集性能数据
3. ✅ **长期**：专注加密货币市场优化，不扩展传统金融

### 🚀 后续优化重点
- **性能调优**：根据实际交易数据优化 FTS5 搜索和压缩策略
- **双交易所验证**：在真实环境测试 Binance + OKX 双 broker 路由
- **策略迭代**：利用 Alpha Zoo 和 Shadow Account 持续优化交易策略
- **监控完善**：完善用量遥测和性能监控面板
