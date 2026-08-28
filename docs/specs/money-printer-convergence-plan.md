---
title: 印钞机优先收敛计划
category: specs
tags: [roadmap, convergence, rule-engine, validation-gates]
---

# 印钞机优先收敛计划

> 本文件为 2026-08-28 经三轮 grilling 评审收敛后的**唯一执行路线**，优先级高于 `docs/develop/roadmap.md` 与 `docs/research/evolution-roadmap.md` 中与本计划冲突的条目。
> 核心原则：**先成为印钞机，再谈其他。任何一关失败时，禁止以「加新功能」作为解法。**

## 0. 背景事实（评审依据）

- 最能赚钱的数字来自**规则层模拟**（B1 ablation +9.42 / 183 trades）；LLM 管线最佳实绩仅 +0.13%～+0.19%，398-bar 完整 LLM 回测（25–80h）已被叫停，`replay/data/real_llm_398_decisions.jsonl` 权益无变化（10000 → 10000）。
- L4（72h paper shadow）被跳过两次；2026-08-13 执行链瘫痪事故（252 单中 239 被风控/交易所挡下）证明纸面与实盘存在真实落差；`docs/operations/deployment-checklist.md` 的 EvidenceGate→coordinator 整合 blocker 未关闭。
- 系统实际只跑 Binance 单币，却维护 6 家交易所 executor + SOR + Jupiter DEX + MCP server + Pine/MQL5 exporter + prime 模式。
- 既有文档已含同款修剪原则：`docs/research/vbt-architecture-strategy-improvement-plan.md` §5.2（3-signal rule 等）、`docs/research/feature-adoption-assessment.md` 的不采纳清单。

## 1. 已裁决的设计决策

| # | 决策点 | 裁决 |
|---|--------|------|
| Q1 | 完赛定义 | 过 paper gate（14d：Sharpe≥0.8、MaxDD≤20%）→ 500U 实盘 2 周仍达标 |
| Q2 | 引擎 | 规则层为主（AlphaZoo + ExitLadder + Half-Kelly + EvidenceGate），LLM 降级 |
| Q3/Q5 | 范围/标的 | Binance 一家，三币：BTCUSDT + ETHUSDT + SOLUSDT |
| Q4/Q7 | 回测验证 | 三组代表性 168h 窗口（上涨/盘整/下跌），**每段各自 PF ≥ 1.2**，总 MaxDD ≤ 5%（10k 本金） |
| Q6 | LLM 残留角色 | 每小时 macro → RISK_ON/NEUTRAL/RISK_OFF 三态，RISK_OFF 禁开新仓（挡单不下单） |
| Q8 | 上线管线 | 3×168h 回测 → 14d paper → 500U 实盘 |
| Q9 | 12-agent 辩论链 | **留码不跑**：代码与测试保留，不进任何自动回路，可手动离线对照 |
| Q10 | 冻结清单执行 | **删码**（物理删除，可逆性依赖 git 历史） |
| Q11 | kill-switch | 日亏 ≥25U（5%）**或**连续 3 笔止损**或**订单拒绝率 >20% → 熔断 |

## 2. 阶段 0：删除华而不实（删码）

物理删除以下模块及其专属测试，修复所有 import 引用：

- `backend/src/vibe_trading/execution/` 内 Binance 以外的 executor：`okx`、`bybit`、`bitget`、`hyperliquid`、`jupiter`，以及 `broker_connector`、`sor`、`funding_arb`
- `backend/src/vibe_trading/mcp/`（MCP server）
- `backend/src/vibe_trading/exporters/`（Pine/MQL5 exporter）
- `backend/src/vibe_trading/prime/`（prime 监控模式）
- 对应测试一并删除或改写（含工作区未追踪的 `tests/test_mcp_contract.py`）

**保留不动**：12-agent 辩论链代码与测试（Q9）、前端监控（不开新功能）、memory 子系统（不扩充）。

文档同步：

- `docs/research/evolution-roadmap.md`：Phase 4 多交易所/DEX、MCP 等标记为「已移除（收敛印钞机路线）」；L2 完整 LLM ablation、L3 Monte Carlo、L4 72h paper 标记为「取消，由 168h×3 + 14d paper 取代」
- `AGENTS.md`：更新架构描述（移除已删模块、说明规则层主引擎 + LLM regime gate）

**验收**：`uv run pytest tests/ -x -q` 全绿；`uv run ruff check backend/src/` 与 `uv run mypy backend/src/` 无新增错误。

## 3. 阶段 1：规则层主引擎 + LLM regime gate 接线

- 交易回路改为规则层直接驱动：AlphaZoo 因子 → 信号 → Half-Kelly 仓位 → EvidenceGate/grounding → ExitLadder 出场
- 标的扩为 `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`（Binance，30m bar）
- LLM 仅保留每小时一次 macro regime 判定，输出收敛为 `RISK_ON / NEUTRAL / RISK_OFF`；`RISK_OFF` 时规则层禁开新仓（既有持仓出场逻辑不受影响）
- 12-agent 辩论链不进任何自动回路（保留手动触发入口做离线对照）

**验收**：三币各跑一段短 replay 烟雾测试，确认 regime gate 在 RISK_OFF 时确实挡下开仓；相关 pytest 全绿。

## 4. 阶段 2：3×168h regime 回测（硬门槛 1）

- 数据：用 `replay/fetch_bars.py` 从 Binance 补齐三币 6–12 个月 30m K 线（本地 `replay/data/bars_90d.json` 仅 BTC 92.5 天且整段偏下跌，上涨段需更早期数据）
- 窗口选择：以 BTC 168h（336 根 30m bar）报酬率分类，选出上涨/盘整/下跌各一段；**三币共用同一组日期窗口**
- 执行：纯规则层 replay（分钟级完成）；LLM regime gate 不进回测回路，以事后标注方式验证 regime 命中率
- **通过门槛（Q7）：每段各自 PF ≥ 1.2；总 MaxDD ≤ 5%（10k 本金）**
- 任一不过 → 回头修策略（调因子/出场/仓位），**不加新功能**

**验收**：产出三段 tearsheet 报告（PF、MaxDD、胜率、payoff），数字白底黑字达标。注意 2026-08 PnL 高估 bug 前科：PnL 计算须对账确认 margin 不计入亏损。

## 5. 阶段 3：14 天 paper shadow（硬门槛 2）

- 先关闭既有 blocker：完成 EvidenceGate→coordinator 整合（见 `docs/operations/deployment-checklist.md`）
- 三币 paper shadow 连跑 14 天，`EvidenceGate.evaluate_paper_performance()` 自动卡关：**Sharpe ≥ 0.8、MaxDD ≤ 20%**
- 不过 → 回阶段 2 诊断，不进实盘

**验收**：14 天期满 EvidenceGate 评估报告显示 PASS。

## 6. 阶段 4：500U 小额实盘（完赛）

- 500 USDT 本金，跑 2 周，单笔 ≤ 100U，沿用 Half-Kelly 仓位与 EvidenceGate
- **Kill-switch（Q11）**：日亏损 ≥ 25U（5%）**或**连续 3 笔止损**或**订单拒绝率 > 20% → 自动停止开新仓 + Telegram 警报，人工复盘签核后才能重启
- 完赛条件：2 周期满仍达 paper gate 同级标准且无熔断触发 → 「印钞机」初验通过，届时才讨论放大或解冻任何周边

**验收**：2 周实盘对账报告（成交明细 vs 系统记录一致、PnL 达标、无熔断）。

## 7. 明确不做

- 不重启 25–80h 级完整 LLM 回测；L2 ablation / L3 Monte Carlo 取消
- 不开发前端新功能、memory 扩充、多交易所、MCP、exporter、prime 模式（阶段 0 已删码）
- 任何一关失败时，禁止以「加新功能」作为解法

## 8. 风险与备注

- 删码不可逆（git 历史可找回，但回滚成本高）——Q10 用户明确裁决
- 阶段 0 删除会波及部分既有测试，预期需要删改测试档；以全绿为完成标准
- 168h×3 样本仍小，PF≥1.2 只是入场券而非盈利保证——这正是阶段 3/4 存在的原因
