# Contributing to Vibe Trading

感謝你考慮為 Vibe Trading 貢獻。以下指引確保協作順暢。

## 開發流程

1. **Fork 並建立分支** — 從 `local/brian` 或 `main` 切出 `feat/<描述>` 分支
2. **改動前先了解** — 閱讀 `CONTEXT.md` (領域術語) 與 `docs/adr/` (架構決策), 避免違反既有約定
3. **實作** — 遵循專案模式 (見 `CLAUDE.md` / `AGENTS.md`):
   - Python 遵循 PEP 8; 新代碼與既有風格一致
   - 錯誤處理: try/except + `logger.warning`/`logger.error`, 不靜默吞錯
   - 日誌: pi_logger (`log.info`/`info()`) + 標準 `logging` 並存
4. **測試** — 新功能必有測試 (`tests/`), 遵循既有 fixture 模式
5. **驗證** — 提交前必須:
   ```bash
   uv run mypy backend/src/vibe_trading/<改動檔案>   # 不新增錯誤 (專案有 pre-existing baseline)
   uv run pytest tests/<相關測試> -v
   uv run pytest -x                                   # 全量無回歸
   ```
6. **提交** — 訊息遵循 Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`

## 程式碼規範

- **領域術語**: 使用 `CONTEXT.md` 定義的術語; 新概念先更新 CONTEXT
- **架構決策**: 難逆轉的決策寫入 `docs/adr/` (0001, 0002...)
- **不引入** 未經討論的新依賴 (`pyproject.toml` 是唯一定義)
- **機密**: `.env` / `llm.yaml` 含 API key, 永不提交 (gitignore 已覆蓋)

## 專案結構速覽

```
backend/src/vibe_trading/   # 主程式 (agents/ coordinator/ notifications/ backtest/ ...)
docs/adr/                   # 架構決策記錄
docs/                       # 技術文件
tests/                      # 測試
scripts/                    # 運維腳本 (vbt.sh 一鍵管理)
replay/                     # agent-in-the-loop 回放 harness (產品化於 backtest/)
```

## 問題回報

- Bug: 附重現步驟、預期/實際行為、相關日誌 (`logs/` 或 `journalctl -u vbt.service`)
- 功能請求: 描述使用情境與預期 UX
