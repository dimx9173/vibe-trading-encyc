# Task 4.7：部署到生產環境 — 準備清單

> 來源：`docs/tasks/external-data-layer-tasks.md` Task 4.7（DevOps）
> 狀態：⏸ 未執行 — 本文件為 live 切換前檢查清單（2026-08-14 盤點）

## 結論先行

**程式/測試層面已就緒**（486/486 全綠、spec 6.2 性能全達標、EvidenceGate 已實作）。
切 live 前剩餘 5 項行動，其中 **4 項需人工確認/操作**，**1 項可自動化（程式碼審查）**。

---

## 行動項目狀態

### 1. 程式碼審查 — 🟡 可自動化
- 最後 15 commits 未跑完整 code review（`local/brian` 領先 origin 15）
- 建議：`/code-review` 審查 `fa372f5..HEAD` 範圍（P2.1→P4 全量）

### 2. 生產環境配置 — 🔒 需人工
| 項目 | 現況 | 待辦 |
|---|---|---|
| `TRADING_MODE` | `.env` 目前 `paper`（正確，切 live 前不變） | 切換時改 `live` |
| `SYMBOLS` / `INTERVAL` | BTCUSDT / 30m | 確認生產標的 |
| `MAX_POSITION_SIZE` / `MAX_TOTAL_POSITION` | 有設定 | 按風險偏好調整 |
| `STOP_LOSS_PCT` / `TAKE_PROFIT_PCT` | 有設定 | 確認閾值 |
| `LEVERAGE` | 有設定 | 確認槓桿（目前持倉 5x） |
| `EXECUTION_POSITION_MODE` | hedge | 確認 broker 支援 |

### 3. API Key 配置 — 🔒 需人工（資金風險最高）
| Key | 現況 | 待辦 |
|---|---|---|
| `BINANCE_API_KEY` / `SECRET` | `.env` 有值 | ⚠️ 確認為**主網** key（非 testnet）且開啟現貨/合約權限、IP 白名單、無提幣權限 |
| `BINANCE_TESTNET_API_KEY` | 有值 | 先以 testnet 驗證執行路徑 |
| Telegram bot token / chat id | `.env.example` 有模板 | 確認已配置（告警用） |

### 4. 監控指標配置 — 🟡 部分就緒
| 項目 | 現況 |
|---|---|
| Usage 遙測（`monitoring/usage_ledger.py`） | ✅ 已實作 + `/api/usage/*` endpoints |
| HealthMonitor / CircuitBreaker | ✅ 已實作 |
| Telegram 通知（`notifications/telegram_notifier.py`） | ✅ 已實作，需確認 `TELEGRAM_ENABLED=true` 且 token 有效 |
| EvidenceGate 評估 | ⚠️ **未整合進 coordinator** — `evaluate_paper_performance` 需手動呼叫或接入排程 |

### 5. 告警規則配置 — 🔒 需人工
- 現有告警：協調器保險（漏單自動執行）、緊急處理器（`emergency_handler.py`）
- 待辦：定義實盤告警閾值（連續虧損、API 失敗率、槓桿超限、資金異常）

---

## 建議切換流程（人工執行）

1. **驗證**：跑 `/code-review`（fa372f5..HEAD）確認無遺漏
2. **演練**：以 `TRADING_MODE=paper` + Binance **testnet** 跑 1-2 天，確認 OKX/Binance 執行路徑
3. **小額實盤**：`TRADING_MODE=live` + 極小 `MAX_POSITION_SIZE` + 單一 SYMBOL，觀察 24h
4. **證據門控**（可選）：先手動執行 `EvidenceGate.evaluate_paper_performance()` 確認 14 天 Paper 績效達標（Sharpe ≥ 0.8、MaxDD ≤ 20%），再切 live
5. **監控**：確認 Telegram 告警收得到、usage 面板正常
6. **回滾**：保留 `TRADING_MODE=paper` 備份 .env，出問題秒切回

---

## 阻塞項目摘要

| # | 阻塞項 | 負責 | 可自動化？ |
|---|---|---|---|
| 1 | 程式碼審查（15 commits） | AI/開發 | ✅ |
| 2 | 生產 .env 參數確認 | 人工 | ❌ |
| 3 | 主網 API key 權限確認 | 人工（資金風險） | ❌ |
| 4 | Telegram 告警驗證 | 人工 | 🟡 |
| 5 | EvidenceGate→coordinator 整合 | AI/開發 | ✅（如需要） |
