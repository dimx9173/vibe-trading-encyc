# Vibe Trading - TODO

> **2026-08-28 优先级声明**：当前唯一执行路线为 [印钞机优先收敛计划](docs/specs/money-printer-convergence-plan.md)。
> 核心原则：**先成为印钞机，再谈其他。任何一关失败时，禁止以「加新功能」作为解法。**
> 本文件下方的 API 集成清单全部**冻结**，待阶段 4 实盘验证通过后再评估解冻。

---

## 🚀 当前执行管线（按顺序，过一关才能进下一关）

### 阶段 0：删除华而不实（删码）✅ 已完成（a6c860b，全量 1855 passed）
- [x] 删除 `execution/` 内非 Binance executor（okx、bybit、bitget、hyperliquid、jupiter）+ `broker_connector`、`sor`、`funding_arb`
- [x] 删除 `mcp/`、`exporters/`、`prime/`
- [x] 删改对应测试（含 `tests/test_mcp_contract.py`），修复 import
- [x] 同步 `evolution-roadmap.md` 状态标记与 `AGENTS.md` 架构描述
- **验收**：✅ `uv run pytest tests/ -x -q` 全绿；`ruff check` / `mypy` 无新增错误

### 阶段 1：规则层主引擎 + LLM regime gate ✅ 已完成（8d40215 实作 + 475be6f 审阅修复，全量 1912 passed）
- [x] 交易回路改规则层直驱：AlphaZoo → 信号 → Half-Kelly → EvidenceGate/grounding → ExitLadder
- [x] 标的扩为 BTCUSDT / ETHUSDT / SOLUSDT（Binance，30m）
- [x] LLM 降为每小时→每2小時（7200s，24hr 48×30m 輸入，4hr/14400s staleness）macro（註：歷史為「每小時」，自 2026-08-30 起已為每2小時/7200s，見收斂計畫 Q6） → RISK_ON/NEUTRAL/RISK_OFF，RISK_OFF 禁开新仓
- [x] 12-agent 辩论链退出自动回路（留码不跑）
- **验收**：三币烟雾 replay 已 PASS（RISK_OFF 挡开仓，gate 432x）；测试 1912 passed；8d40215 审阅发现 3 条 P0 / 5 条 P1 / 2 条 P2，全部于 475be6f 修复（见下）

### 阶段 1.5：审阅修复 ✅ 已完成（475be6f，全量 1912 passed）

```
开工：修复 Phase 1 commit 8d40215 的审阅发现。先读 docs/specs/phase1-rule-engine-regime-gate.md（规格）与被审 commit（git show 8d40215）。

P0-1 新仓 TP1 前零止损保护（最严重）
- 现状：backend/src/vibe_trading/rule_engine/loop.py on_bar 步 6 算出的 sl（1.5×ATR，:307）仅用于 sizing/grounding，从不写入 _LadderState.stop；_evaluate_exit（:386-399）的 hard stop 只在 state.stop is not None 时生效，而 ExitLadderEngine.evaluate_position 在 INITIAL 阶段不回 stop → 开仓到 TP1（+1.5R）之间无任何止损
- 修法：开仓成功后（:344-357）建立 self._ladder_states[symbol] = _LadderState(stage=INITIAL, entry=成交价, highest=成交价, lowest=成交价, stop=sl)；先读 _LadderState 定义确认字段与预设
- 验证：新测试——开仓后下一 bar 收盘跌破 sl → 断言 action="exit" 全平
- 规格同步：在 §5 加一行注明「live 模式交易所端 STOP_MARKET 条件单属阶段 4 前置，本阶段不做」

P0-2 enable_exit_ladder=False 未接进真实启动路径（双重出场权威）
- 现状：开关在 execution/order_executor.py:123，但 cli.py create_execution_executor（:192 附近）与 main/multi_thread_main.py 不传 → vibe-trade start 实跑时 executor 内嵌简单 ladder 与 ExitLadderEngine 双发，违规格 §5
- 修法：沿 cli.py start → create_execution_executor → MultiThreadedTradingSystem 把旗标传到 PaperOrderExecutor（规则回路模式恒 False）
- 验证：测试断言 startup 组装后 executor._enable_exit_ladder is False

P0-3 regime 逐币读取但 macro 只写主币（ETH/SOL 永久半仓）
- 现状：loop.py:276 current_regime(..., symbol=self.symbol)，macro_thread 只分析 symbols[0] → ETH/SOL 永无 state → fail-safe NEUTRAL 永久半仓
- 修法：macro regime 是市场级判断，current_regime 忽略 symbol 读最新 state；symbol 参数保留仅供日志
- 验证：测试——macro state 以 BTCUSDT 写入，ETH 的 loop 读到相同 regime

P1（一批做完）
1. loop.py:442,447 死码 min(qty, abs(qty)) → qty
2. regime_gate.py map_macro_to_regime 未用的 sentiment 参数删除（同步呼叫点/测试）；核 trend_strength 字串映射 STRONG=0.8 是否符合 MacroState 实际型别，码与规格 §3.2 对齐一边
3. onbar_thread.py 新码的标准 logging logger.info → 改用同档既有 pi_logger（AGENTS.md 硬性规范）
4. 持仓期间步 4–8 跳过（no-pyramiding）不动码：更新规格 §3.3 步 3 文字 + loop.py 加注释
5. RuleEngineConfig 规格外的 interval/symbols 字段：未使用则删，有使用则补进规格 §3.4

P2（仓库卫生；git mutation 前先问用户）
- replay/data/rule_*.db.audit 与 rule_*_decisions.jsonl 是 replay 产物 → git rm --cached + .gitignore 加 replay/data/rule_*
- 动量因子键大小写双拼写（signal.MOMENTUM_KEYS vs technical_tools）核实后统一

硬性约束
- 不改 trading_coordinator.py / evidence_gate.py / backtest/engine.py / 旧 Kelly 路径
- 日志一律 pi_logger get_logger（tag 参数），禁标准 logging
- 最小改动，不做本清单外的事

验收
- uv run pytest tests/test_rule_engine_loop.py tests/test_regime_gate.py tests/test_rule_engine_signal.py -q 全绿（含 P0-1 新测试）
- uv run pytest tests/ -x -q 全绿无回归
- uv run ruff check backend/src/ 与 uv run mypy backend/src/ 无新增错误
- 重跑 replay/replay_rule_engine.py BTC 段确认仍有正常 exit/reduce 决策产出
- 完成后 commit message 用 conventional 前缀（fix: ...），并回报每条 P0/P1 的处置
```
- **验收**：✅ 三测试文件 99 passed（含 P0-1/P0-3 新测试）/ 全量 tests/ 1912 passed / ruff・mypy 无新增错误 / replay BTC 段 432 bars 正常完成（决策分布与基线一致）
- **处置**：P0-1 开仓即武装初始 stop；P0-2 旗标透传 start→executor；P0-3 regime 市场级读取；P1 五项；P2 全项（详见 475be6f commit message）

### 阶段 2：3×168h regime 回测（硬门槛 1）⛔ 冻结（按计划默认：任一不过 → 不进实盘）
- [x] `replay/fetch_bars.py` 补齐三币 180d 30m K 线
- [x] 按 BTC 168h 报酬率选上涨/盘整/下跌三段窗口，三币共用日期（`replay/data/windows.json`）
- [x] 纯规则层 replay + 20 组合参数 sweep × 2 轮，产出三段 tearsheet（`replay/tearsheet_rule.py`）
- **门槛**：每段各自 PF ≥ 1.2，总 MaxDD ≤ 5%；不过 → 修策略，不加功能
- **v1 结论**：20/20 未过（range 0.59–0.90）；发现 TP 接线缺陷（commit 533d932 + 484dad4）
- **v2 结论**：修复 TP 接线（ab73c7d）后重跑 20/20 未过（range 0.51–1.14 峰值；uptrend/downtrend 高阈值+宽止损可各自达标但同组合无法兼顾）。range 段 40/40 < 1.2 → 动量信号在横盘无 edge，非参数问题
- **判别因子复测（882ce38）**：trend_strength / ADX / Efficiency-Ratio 三窗口分布全部完全重叠 → 无「横盘判别因子」可加，问题在信号本身（30m 减采样后净零漂移窗口无可交易结构）
- **数据验证**：独立重算 PF 精确匹配 sweep log；tearsheet equity/MaxDD 计算正确（margin 不计亏损）；doc↔log↔raw 四层一致
- **处置**：⛔ 按计划「任一不过 → 不进实盘」冻结，不进阶段 3。重启需用户明确指示（如实盘 regime gate 切段 A / 信号层迭代 / 换窗口口径），非当前待办。详见 [阶段 2 回测报告](docs/specs/phase2-regime-backtest-verdict.md)

### 阶段 3：14 天 paper shadow（硬门槛 2）
- [ ] 完成 EvidenceGate→coordinator 整合（`docs/operations/deployment-checklist.md` blocker）
- [ ] 三币 paper shadow 连跑 14 天
- **门槛**：Sharpe ≥ 0.8、MaxDD ≤ 20%；不过 → 回阶段 2

### 阶段 4：500U 小额实盘（完赛）
- [ ] 500 USDT 跑 2 周，单笔 ≤ 100U
- [ ] Kill-switch：日亏 ≥25U（5%）或连 3 笔止损或订单拒绝率 >20% → 熔断 + Telegram + 人工签核重启
- **完赛**：2 周期满达标且无熔断 → 才讨论放大或解冻周边

---

## 🧊 已冻结：API 集成清单（印钞机验证通过前不执行）

> 以下为原 API 集成 TODO，全部属于「加功能」，与收敛路线冲突，冻结保留备查。

### 🔴 原高优先级

**1. Whale Alert API - 大额转账监控**（免费，https://whale-alert.io/）
**2. CryptoQuant API - 链上数据**（部分免费，https://cryptoquant.com/api-docs）

### 🟡 原中优先级

**3. FRED API - 宏观经济数据**（免费，https://fred.stlouisfed.org/docs/api/fred/）
**4. Etherscan API - Gas 费数据**（免费有限制，https://docs.etherscan.io/）
**5. Coinglass API - 跨交易所数据**（部分免费，https://www.coinglass.com/）

### 🟢 原低优先级

**6. GitHub API - 开发活跃度**（公开端点即可）
**7. RSS 新闻源聚合**（CoinDesk / Cointelegraph / The Block）
**8. Santiment API - 链上+社交数据**（付费，https://santiment.net/）

---

## 📊 当前已集成

| 功能 | 平台 | 状态 |
|------|------|------|
| K线数据 | Binance | ✅ 完成 |
| 技术指标 | 自计算 | ✅ 完成 |
| 资金费率 | Binance | ✅ 完成 |
| 多空比例 | Binance | ✅ 完成 |
| 新闻数据 | CryptoCompare | ✅ 完成 |
| 恐惧贪婪指数 | Alternative.me | ✅ 完成 |
| 社交情绪 | LunarCrush | ✅ 完成 |

---

## 📝 注意事项

- 所有 API 密钥请妥善保管，不要提交到 Git
- 免费层通常有请求限制，注意缓存策略
- 解冻任何冻结条目前，先重读收敛计划的「明确不做」一节
