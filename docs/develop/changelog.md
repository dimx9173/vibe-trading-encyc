---
title: 版本变更记录
category: develop
tags: [development, contributing, changelog]
---

# 版本变更记录

本文档记录了 Vibe Trading 项目的所有重要变更。

## [未发布]

### 新增

- 初始版本发布
- 12 Agent 协作架构
- 4 阶段决策流程
- 智能辩论系统
- BM25 记忆系统
- Paper Trading 模式
- Web 监控界面
- K线级决策追溯
- Agent 报告展开阅读和 Markdown 渲染
- Runtime Log 同步 terminal 输出
- **Backtest Engine**：MA-crossover 策略 + 订单模拟器（`backtest/`）
- **skip_debate 选项**：`SKIP_DEBATE=true` 跳过 debate phase（快速验证用）
- **三層日誌輪替**：replay A 的 log rotation（c22e9c1）
- **P2.1 Alpha Zoo**：23 因子四分类（momentum/volatility/volume/mean_reversion）+ IC/IR bench + AST 纯度门 + lookahead-guard（fa372f5）
- **P2.2 回测引擎套件**：`BacktestEngine.run()` + metrics + MC/WF/Bootstrap validation + fee/slippage（fa372f5）
- **P2.3 Shadow Account**：行为偏差画像（处置效应/过度交易/追涨/锚定）+ 反事实回测报告（fa372f5）
- **P3.1 Hypothesis Registry**：SQLite hypotheses + research_goals + GoalManager（fa372f5）
- **P3.2 跨会话记忆升级**：FTS5 全文检索 + 5 级上下文压缩 + BM25/FTS5 混合后端 + skill CRUD（fa372f5）
- **P3.3 策略导出**：`exporters/` NL→Pine v6 / MQL5（fa372f5）
- **P3.4 Swarm 预设**：可配置编排（investment_committee 等）（fa372f5）
- **P4.1 OKX 实盘**：`OkxOrderExecutor` + `BrokerConnector` 抽象层（fa372f5）
- **外部数据层 2.0**：UnifiedDataSource / LRUCache / CircuitBreaker / HealthMonitor / SmartRouter + 插件架构（fa372f5）
- **ResearchDatabase 压力测试**：500 笔 save/query/update/delete 循环 + 效能断言（cd2ede7）
- **P3 使用指南**：`docs/p3-usage-guide.md`（cd2ede7）
- **外部数据层 Phase 4**：`EvidenceGate`（Paper→Live 14 天评估 + SQLite 历史）+ `PerformanceTracker`（交易记录 + Sharpe/MaxDD/WinRate）+ `DecisionEnhancer`（插件装饰器降级）+ `ReportGenerator`（backtest/paper 对比报告）+ `BacktestDataLoader.load_klines`（回测数据层 facade）（本次 commit）

### 变更

- Web 前端改为 React + Vite + lightweight-charts
- Makefile 支持通过 `SYMBOL` 和 `INTERVAL` 变量启动不同交易对和K线周期
- **Paper ledger 持久化**：`state_file` + `--reset-paper`，重启自动还原（d140d36, 8abb462）
- **Backtest SMA 优化**：O(N·P) → O(N) sliding window，30x 加速（30033a5）
- **B9 订单规范化**：PM 路径订单 notional cap（settings `execution_max_single_order_notional=100`）在 risk gate 前执行（0dcb9a8）
- **spec/task 文档**：external-data-layer 规格更新为 2.1.0，诚实标注 Phase 4（证据门控/统一报告）未实施

### 修复

- **Paper ledger 真实账本**：BUY 扣保证金、SELL 退还 + 结算 realized_pnl（d140d36）
- **PM 决策保险**：BUY/SELL 漏呼叫 tool 时 coordinator 自动执行（7853355）
- **Debate timeout 防护**：45s timeout + 3 retries，防止 reasoning model thinking loop（fc7f089）
- **Agent prompt 统一**：universal `prompt_with_timeout` for all agent LLM calls（d641576）
- **Tool call 错误处理**：extract TextContent only + error_message field + retry compensation（fb5bb3d）
- **PM prompt 为 None**：`_build_decision_prompt` 补 `return prompt`，修复 PortfolioManagerAgent LLM 调用崩溃（cd2ede7）
- **rate limit 统计崩溃**：`_log_improvements_stats` 用 int 剩余令牌取代 `.get('minute')`（cd2ede7）
- **cache.py 兼容**：还原 MemoryCache/HybridCache/get_global_cache/cached 导出 + LRUCache wrapper，修复多模块 import 失败（cd2ede7）

### 移除

- 移除旧回测 Web 文档入口，当前文档聚焦实盘 Paper Trading 监控

---

## 版本号说明

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范：

- **主版本号**：不兼容的 API 变更
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

## 变更类型

- **新增**：新功能
- **变更**：现有功能的变更
- **弃用**：即将移除的功能
- **移除**：已移除的功能
- **修复**：Bug 修复
- **安全**：安全相关的修复或改进
