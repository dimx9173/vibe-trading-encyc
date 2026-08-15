# Changelog

專案變更記錄 (以 git history 為權威, 此文件記錄主要版本/重大功能)。

## [Unreleased]

### Added
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
