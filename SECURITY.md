# Security Policy

## 支援版本

| 版本 | 支援狀態 |
|---|---|
| main / local/brian | ✅ 主動開發中 |
| 其他 | ❌ 不支援 |

## 回報漏洞

**請勿在公開 issue 中揭露安全漏洞。**

- 聯繫方式: 透過 GitHub 私訊維護者, 或於 issue 中標記 `security` 並避免洩漏敏感細節
- 包含資訊:
  - 漏洞類型與影響範圍
  - 重現步驟 (最小範例)
  - 受影響版本/commit
  - 建議修復 (如有)

## 已知安全注意事項

本專案為量化交易系統, 涉及真實資金與 API 憑證:

1. **`.env` / `llm.yaml`**: 含 API keys (Telegram bot token, LLM keys, Binance keys), 已被 `.gitignore` 排除, 永不提交。若意外提交, 立即撤銷該 key 並輪換。
2. **TG 指令授權**: 僅 `TELEGRAM_CHAT_ID` (或 `allowed_chat_ids`) 可執行查詢指令; 無控制/下單指令 (v2 設計)。
3. **實盤風險**: `--mode live --execute` 會真實下單; 風控閘門 (`PreTradeRiskGate`) 為最後防線, 修改時需測試。
4. **Look-ahead 完整性**: agent replay 依賴 tool isolation 阻擋 live 數據洩漏; 新增 live-data tool 時必須同步 patch `agent_isolation.py` (見 ADR-0001)。

## 安全更新流程

1. 修復在 `local/brian` 分支開發
2. 合併前需通過完整測試 (`uv run pytest -x`)
3. 重大安全修復建議同時更新 `CHANGELOG.md`
