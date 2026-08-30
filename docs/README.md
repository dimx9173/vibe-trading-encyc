# Vibe Trading 文檔總覽（分類索引）

> 本文件為 `docs/` 目錄的分類索引，便於快速定位文件。**文檔站首頁為 `index.md`（VitePress）**。
> 本索引按主題分類，並標註文件狀態：
> - ★ 權威／現行執行路線　- 活躍文件
> - ⛔ 已棄用　- 📜 歷史紀錄（保留供追溯）　- ⚠️ 部分過時（含收斂計畫前條目，見註記）

## 當前架構一句話
系統自 2026-08-28「印鈔機優先收斂計畫」起，**僅跑 Binance 單交易所**（BTCUSDT/ETHUSDT/SOLUSDT, 30m），主執行回路為**規則層**（AlphaZoo→信號→Half-Kelly→EvidenceGate→ExitLadder），LLM 僅做每小時 `RISK_ON/NEUTRAL/RISK_OFF` regime gate。12-agent 辯論鏈**留碼不跑**（僅離線對照，見收斂計畫 Q9）。

---

## 1. 🚀 入門與快速開始
- [快速開始](guide/quick-start.md) — 環境初始化、啟動、Web 監控（已移除 Prime 模式）
- [項目簡介](guide/intro.md) — 定位、技術棧、核心能力（已移除多交易所規劃）
- [配置說明](guide/configuration.md) — 環境變數與 yaml 配置
- [自定義 Agent](guide/custom-agent.md) — 開發與集成自定義角色

## 2. 🏗️ 系統架構
- [系統架構（指南）](guide/architecture.md) — 現狀架構說明（含收斂 callout）
- [系統全覽](architecture/system-overview.md) — 代碼級組件/生命週期/資料流（含收斂註記與已刪除模組清單）
- [Agent 核心框架](architecture/agent-framework.md) — `pi_agent_core` 雙迴圈訊息機制
- [⚠️ 平台一致性規範](architecture/platform-conformance.md) — 2026-08-05 歷史設計評審（早於收斂；Prime/MCP 已刪除）
- [Context 管理](guide/context-management.md) — Agent 間狀態傳遞與隔離
- [API 文件](guide/api.md) — API 介面參考

## 3. 🤖 Agent 協作（保留／離線對照）
- [Agent 團隊](guide/agents.md) — 12 個 Agent 職責（辯論鏈僅離線對照，Q9）
- [協作流程](guide/workflow.md) — 4 階段協作流程（辯論鏈僅離線對照，Q9）

## 4. 🧩 核心功能指南
- [Web 監控](guide/monitoring.md) — 即時監控介面
- [數據提供者](guide/data-provider.md) — Provider 工廠（已移除 OKX/Bybit 節點，Binance-only）
- [外部數據層](guide/external-data-layer.md) — 核心+插件架構、智能路由、證據門控（已移除多交易所聚合與 Pine/MQL5 導出）
- [⛔ 交易所連接器](guide/broker-connector.md) — **已棄用**：系統僅 Binance 單所
- [記憶系統基礎](guide/memory.md) — BM25 記憶
- [記憶系統升級](guide/memory-upgrade.md) — FTS5+BM25 混合記憶與壓縮
- [P3 研究脊梁](guide/research-backbone.md) — 假設註冊表（已移除策略導出章節）
- [Telegram 告警通知](guide/telegram-notifications.md) — 三級優先級告警

## 5. 📐 規格書（Specs）
- [★ 印鈔機優先收斂計畫](specs/money-printer-convergence-plan.md) — **權威執行路線**（階段 0–4、收斂原則）
- [階段 1：規則層主引擎 + LLM Regime Gate](specs/phase1-rule-engine-regime-gate.md)
- [階段 2：3×168h 回測裁決](specs/phase2-regime-backtest-verdict.md)
- [⚠️ 外部數據層重構規格](specs/external-data-layer-redesign.md) — 含多交易所聚合條目，已於收斂後不適用（僅 Binance）
- [⚠️ 雙向交易與神經符號策略規格](specs/vbt-architecture-strategy-improvement-spec.md) — L4 (72h paper) 已取消
- [進階量化獲利與元認知策略規格](specs/vbt-harvested-alpha-spec.md)

## 6. 🔬 研究與競品分析
- [競品深度分析報告](research/competitive-analysis.md) — 與 HKUDS / AlphaGPT 對比（競品 OKX/Jupiter/MCP 描述為有意保留）
- [📜 技術演進路線圖](research/evolution-roadmap.md) — **歷史演進紀錄**，已被收斂計畫取代（已移除條目加刪除線）
- [398-Bar Replay 回測分析](research/replay-analysis-398bars.md) — 歷史 LLM 回測分析
- [架構與策略改善計劃書](research/vbt-architecture-strategy-improvement-plan.md)
- [進階獲利借鏡擴展計劃書](research/vbt-harvested-alpha-expansion-plan.md)
- [⚠️ 功能借鏡評估](research/feature-adoption-assessment.md) — 含已刪除 MCP server 條目（見註記）

## 7. 📜 架構決策記錄（ADR）
- [ADR-0001 工具隔離](adr/0001-replay-tool-isolation.md)
- [ADR-0002 回測與 Replay 邊界](adr/0002-agent-replay-vs-rule-backtest.md)

## 8. 🚨 事故紀錄（Incidents）
- [2026-08-04 LLM 串流失敗](incidents/2026-08-04-llm-stream-failure.md)
- [2026-08-04 靜默串流失敗](incidents/2026-08-04-silent-stream-failure.md)
- [2026-08-05 Paper 帳本修復](incidents/2026-08-05-paper-ledger-fix.md)
- [2026-08-09 Replay 3 Bars SWDA](incidents/2026-08-09-replay-3bars-swda.md)
- [2026-08-13 執行鏈癱瘓 b1b6 SWDA](incidents/2026-08-13-execution-chain-b1b6-swda.md)

## 9. 🛠️ 運維與部署
- [Web 系統狀態](operations/web-system-status.md)
- [生產部署檢查清單](operations/deployment-checklist.md) — 演練已改為 Binance 單所

## 10. 🧰 開發指南
- [參與貢獻](develop/contributing.md)
- [📜 版本變更記錄](develop/changelog.md) — 歷史紀錄（含已移除的 OKX/Pine 功能，標註已移除）
- [📜 開發路線圖](develop/roadmap.md) — **已過時**，已被收斂計畫取代（已移除條目加刪除線）

## 11. 🌐 文檔站
- [index.md](index.md) — VitePress 首頁（功能特性已更新為 Binance-only）

---

## 重複內容整合說明
- **三份路線圖已收斂為單一權威來源**：`develop/roadmap.md` 與 `research/evolution-roadmap.md` 標記為歷史/已過時，並以刪除線標註已移除條目；現行唯一執行路線為 `specs/money-printer-convergence-plan.md`。
- **架構描述雙來源已對齊**：`guide/architecture.md` 與 `architecture/system-overview.md` 均加收斂 callout，統一為 Binance-only + 規則層主引擎 + LLM regime gate。
- **已刪除功能全局清除**：OKX/Bybit/Bitget/Hyperliquid/Jupiter 多所執行、`broker_connector`、SOR、MCP server、Pine/MQL5 exporter、Prime 模式 的活躍引用均已在指南/規格中清除（僅保留於收斂計畫的「已刪除清單」與歷史紀錄的刪除線標註）。
