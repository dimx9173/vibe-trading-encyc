# Changelog

專案變更記錄 (以 git history 為權威, 此文件記錄主要版本/重大功能)。

## [Unreleased]

### Fixed
- **測試穩定性**: 隔離 HybridCache 文件持久化 (`./cache`) — 運行中 vbt/回測寫入的真實市場資料不再汙染工具測試 (get_open_interest 等); 修 usage ledger daily summary 測試 cutoff bug
### Fixed
- **回測報告 P&L 嚴重高估虧損**: `agent_report` 用 balance 變化算 realized/total, 但 balance 是可用餘額 (開倉/加倉扣未返還 margin) → 把 margin 當虧損 (一週 -150 實為 -16.5)。修: total 用 (equity + 未返還 margin), realized/unrealized/win_rate 亦 margin-aware
### Fixed
- **回測管線 skip_debate bug**: `set_settings(**{**settings.__dict__, ...})` 傳 kwargs dict 給收 Settings 物件的函式 → TypeError 使回測完全跑不動; 改 `Settings(**{...})` 重建
- **回測 LLM cache wrapper**: 對 Trader/PM 包錯物件 (`agent.prompt` 不存在) → cache 完全失效; 改解析實際 `_agent.prompt` 讓 cache 對所有角色生效
- **Sentiment 分析師 funding_rate 崩潰**: `data["funding_rate"]["funding_rate"]` 在資料源回 error dict 時拋 KeyError; 加容錯降級 (N/A 標記, 不崩潰)
### Fixed
- **測試隔離**: `DecisionCheckpointStore` 測試中重定向 `:memory:` — coordinator 測試不再寫入真實 `vibe_trading.db` (先前每跑全量污染 ~15000 checkpoint/決策)
- **風控參數**: `execution_max_total_exposure` 300 → 1000 USDT (預設 + env fallback) — 解除持倉敞口卡死 (現有 225 + 加倉 94 超過舊 300 限制)

### Added
- **測試覆蓋率 85% 里程碑達成**: 50% → 85% (2332 tests, 18006/21183 stmts) — 120 波 Wave D 測試補強, 涵蓋 cli/coordinator/prime/web/execution/triggers/constraints/memory/providers/indicators 全模組 (測試檔 55+)
- **測試期間修復 8 個真實 bug**: `vendor_routed` 缺 return、`TriggerConfirmation` 欄位缺失/遞迴 property、`MessageChannel.get` event starvation、PM cross-lessons list concat、risk level string max、`RiskDebatePhase.CONSENSUS` 大小寫、`get_tools_for_agent` KeyError、sentiment cache undefined response
- 測試套件效能: 修復 30s 真等待測試 (mock wait_for), 全量 85s → 55s

### Added
- 測試覆蓋率提升 (Wave A+B): 50% → 56% — `test_alpha_zoo` (56)/`test_technical_indicators` (22)/`test_storage_layers` (28, 4 storage 87-89%)/`test_vendor_router` (21)/`test_cli_commands` (19, cli 0→42%)/`test_coordinator_decision` (13, coordinator 55→63%)
- **修 bug**: `vendor_routed` 裝飾器缺 `return decorator` (回 None, 由新測試發現)

### Added
- CEX/DEX 執行矩陣 (Phase 4.1): Bybit/Bitget 永續執行器 + Hyperliquid DEX + Jupiter swap (全部 dry-run 優先) + SOR 跨所路由 + 資金費率套利偵測 (`sor-quote`/`funding-arb` CLI)
- Crypto MCP 計算工具 (Phase 4.4): `quantlib_var_calc`/`alpha_stackvm_eval`/`crypto_universe_scan` + Host/Origin guard (DNS-rebinding 防護)
- RunManifest 方法論指紋 (Phase 4.3): replay 可重現性可證明 (prompt/tools/套件 content-addressed hash), `manifest-diff` 偵測漂移
- 動態標的宇宙 + 退出階梯 (Phase 4.2): `universe-scan` (Binance 永續 24h 排名/過濾) + trailing stop/moonbag 退出狀態機 (PaperOrderExecutor 接入)
- Alpha Mining (Phase 3): 演化式因子搜尋 (變異/交叉/選擇) + IC/IR/Sharpe 張量評分 + 假說庫自動註冊 (`vibe-trade research alpha-mine`, 無 RL — PIT 安全)
- 永續合約回測保真度 (Phase 2.3): 資金費率三結算點 (0/8/16 UTC) 去重扣費 + OKX 分級維持保證金強平 (agent replay)
- StackVM 符號運算元 (Phase 2.2): 12 運算元 (ADD/SUB/MUL/DIV/GATE/JUMP/DECAY/DELAY1/MAX3...) + compose_factor tool (分析師可組合自定義因子, arity-checked, NaN-safe)
- Microstructure factors (Phase 2.1): pressure (真實 taker_buy)/fomo/vol_cluster/close_pos/momentum_rev/vol_trend 接入 Technical Analyst (純函式, NaN-aware)
- QuantLib (Phase 1.1): 確定性金融數學庫 (Cornish-Fisher VaR, EVT/GPD, GARCH/EWMA, Fractional Kelly, TWR/XIRR, L2 衝擊成本); 修復 `advanced_risk_tools` parametric VaR scipy ImportError (改純 NumPy Acklam ppf)
- Grounding Gate (Roadmap Phase 1.2): TradingPlan 價格 vs OHLC 邊界確定性校驗, 違規自動降級 HOLD + metadata 記錄
- TG 查詢指令: `/balance` `/positions` `/status` `/decision` `/help` + 指令選單 (`set_my_commands`)
- Agent-in-the-loop backtest CLI (`vibe-trade backtest-agent run/report/fetch`):
  - LLM response cache (重跑近零成本), `--resume` 斷點續跑, 成本估算閘門
  - Look-ahead 完整性修復 (tool isolation 3 漏洞)
- 一鍵管理腳本 `scripts/vbt.sh` (start/stop/restart/status/logs, systemd 自動委託)
- Telegram 通知整合: startup/shutdown/緊急事件通知

### Fixed
- Backtest `_make_trade` 部位計算: `position_size` 是 USDT 金額, 需換算 quantity (原公式把金額當數量 × 價格, P&L 放大千倍)
- Signal handler 提前設 `_running=False` 導致 shutdown 通知永遠不發送
- `TelegramNotifier.stop()` 取消 loop 前未 flush 佇列, shutdown 通知遺失
- pi_logger `configure(log_level=...)` 被靜默忽略 (屬性名是 `min_level`)
- CLI `--log-level` 未透傳到 `run_multi_thread_system`

### Chore
- 專案目錄整理至 GitHub 標準結構: runtime/備份檔移出版本控制, demo 腳本入 `scripts/`
- 補齊 community standards: `LICENSE` (Apache-2.0), `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, issue/PR templates, CI workflow

## [0.1.0] - 2026-07

- 初始版本: 13-agent 協作決策管線、Binance 整合、paper trading、Web 監控
