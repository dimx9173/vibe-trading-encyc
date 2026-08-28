# Vibe Trading - TODO

> **2026-08-28 优先级声明**：当前唯一执行路线为 [印钞机优先收敛计划](docs/specs/money-printer-convergence-plan.md)。
> 核心原则：**先成为印钞机，再谈其他。任何一关失败时，禁止以「加新功能」作为解法。**
> 本文件下方的 API 集成清单全部**冻结**，待阶段 4 实盘验证通过后再评估解冻。

---

## 🚀 当前执行管线（按顺序，过一关才能进下一关）

### 阶段 0：删除华而不实（删码）
- [ ] 删除 `execution/` 内非 Binance executor（okx、bybit、bitget、hyperliquid、jupiter）+ `broker_connector`、`sor`、`funding_arb`
- [ ] 删除 `mcp/`、`exporters/`、`prime/`
- [ ] 删改对应测试（含 `tests/test_mcp_contract.py`），修复 import
- [ ] 同步 `evolution-roadmap.md` 状态标记与 `AGENTS.md` 架构描述
- **验收**：`uv run pytest tests/ -x -q` 全绿；`ruff check` / `mypy` 无新增错误

### 阶段 1：规则层主引擎 + LLM regime gate
- [ ] 交易回路改规则层直驱：AlphaZoo → 信号 → Half-Kelly → EvidenceGate/grounding → ExitLadder
- [ ] 标的扩为 BTCUSDT / ETHUSDT / SOLUSDT（Binance，30m）
- [ ] LLM 降为每小时 macro → RISK_ON/NEUTRAL/RISK_OFF，RISK_OFF 禁开新仓
- [ ] 12-agent 辩论链退出自动回路（留码不跑）
- **验收**：三币烟雾 replay 确认 RISK_OFF 挡开仓；pytest 全绿

### 阶段 2：3×168h regime 回测（硬门槛 1）
- [ ] `replay/fetch_bars.py` 补齐三币 6–12 个月 30m K 线
- [ ] 按 BTC 168h 报酬率选上涨/盘整/下跌三段窗口，三币共用日期
- [ ] 纯规则层 replay，产出三段 tearsheet
- **门槛**：每段各自 PF ≥ 1.2，总 MaxDD ≤ 5%；不过 → 修策略，不加功能

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
