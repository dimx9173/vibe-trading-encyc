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

### 变更

- Web 前端改为 React + Vite + lightweight-charts
- Makefile 支持通过 `SYMBOL` 和 `INTERVAL` 变量启动不同交易对和K线周期
- **Paper ledger 持久化**：`state_file` + `--reset-paper`，重启自动还原（d140d36, 8abb462）
- **Backtest SMA 优化**：O(N·P) → O(N) sliding window，30x 加速（30033a5）

### 修复

- **Paper ledger 真实账本**：BUY 扣保证金、SELL 退还 + 结算 realized_pnl（d140d36）
- **PM 决策保险**：BUY/SELL 漏呼叫 tool 时 coordinator 自动执行（7853355）
- **Debate timeout 防护**：45s timeout + 3 retries，防止 reasoning model thinking loop（fc7f089）
- **Agent prompt 统一**：universal `prompt_with_timeout` for all agent LLM calls（d641576）
- **Tool call 错误处理**：extract TextContent only + error_message field + retry compensation（fb5bb3d）

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
