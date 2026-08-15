---
name: Pull Request
about: 提交變更
title: ""
labels: ""
assignees: ''
---

## 摘要
<!-- 這個 PR 做了什麼, 為什麼 -->

## 變更類型
- [ ] feat: 新功能
- [ ] fix: 修復
- [ ] refactor: 重構 (無行為變化)
- [ ] docs: 文件
- [ ] test: 測試
- [ ] chore: 維護

## 測試
- [ ] `uv run mypy backend/src/vibe_trading/<改動檔案>` — 無新增錯誤
- [ ] `uv run pytest tests/<相關測試> -v` — 通過
- [ ] `uv run pytest -x` — 全量通過

## 相關
- 關聯 issue: #
- ADR: docs/adr/#
