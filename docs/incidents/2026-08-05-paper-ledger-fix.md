---
title: "Paper Ledger Fix"
description: "Incident report: Paper Ledger Fix"
date: 2026-08-05
category: incident
tags: [incident, bug-fix, debugging, post-mortem]
---

# Paper 帳本真實化 + 跨重啟持久化 (2026-08-05)

> 建立日期: 2026-08-05
> 對應 Commits: `d140d36` `8abb462`（local/brian branch，未 push）
> 嚴重度: **MEDIUM** — paper 引擎帳本是假帳本，balance 恆為 10,000，無法反映真實盈虧
> 修復結果: 真實保證金帳本（扣保證金/結算盈虧）+ JSON state 檔跨重啟自動還原

---

## 症狀

paper 模式下 `get_balance()` 永遠回傳 10,000：
- 買入不扣款、賣出不加款，帳戶餘額恆定
- DB 的 `execution_position_snapshots` 裡 `unrealized_pnl` 永遠 0（成交當下 mark=entry）
- 從 7/17 至今 **0 筆 SELL fill**，`realized_pnl` 永遠 0
- 每次重啟 → 新的 10,000 帳戶、空持倉（純記憶體狀態）

## 根因（程式碼審查）

### ① `PaperOrderExecutor._balance` 從未被交易更新
`order_executor.py`：
```python
def __init__(self, initial_balance: float = 10000.0):
    self._balance = initial_balance   # ← 之後沒有任何程式碼修改它
```
`get_balance()` 回傳 `balance = self._balance + total_realized_pnl`，但買入不扣款、賣出不加款 — 帳本根本沒在記帳。

### ② realized_pnl 全平倉就丟失
```python
pos.realized_pnl += pos.unrealized_pnl
pos.quantity -= quantity
if pos.quantity <= 0:
    del self._positions[pos_key]     # ← position 被刪，realized_pnl 一起消失
```
`total_realized_pnl` 只加總**仍存在**的持倉 — 全平倉後盈虧蒸發。

### ③ 每次重啟歸零
`PaperOrderExecutor` 純記憶體，DB（`order_audit`）只寫 audit log、不做 state restore。

---

## 修復 1：真實保證金帳本（`d140d36`）

### 改動
- **BUY**（開/加多倉）：`self._balance -= execution_price * quantity / leverage`（扣保證金）
- **SELL**（平多倉）：退還**原保證金**（按 entry_price 計算，避免價格變動雙重計算）+ 已實現盈虧入帳
- **realized_pnl 移到 executor 層級累計**（`self._realized_pnl`）→ 全平倉 `del` 後不再丟失
- **多空對稱**：`SELL+SHORT` 開空、`BUY+SHORT` 平空、`SELL+SHORT` 空倉加倉
- `get_balance()`：`balance` = 現金（含已實現）、`available` = balance + 浮盈

### 測試（8 個）
`tests/test_paper_executor.py`：扣保證金、全平倉結算、realized 跨全平倉保留（regression）、部分平倉、無倉位 noop、加倉均價、浮盈追蹤、空單盈虧

## 修復 2：跨重啟持久化（`8abb462`）

### 設計：預設自動還原，帶參數才重置

```
vibe-trade start BTCUSDT                     # 預設：restore 上次狀態
vibe-trade start BTCUSDT --reset-paper       # 重置：忽略 state 檔，從 10,000 重新開始
vibe-trade start BTCUSDT --paper-state /path # 自訂 state 檔位置（預設 data/paper_account.json）
```

### 改動
- **`PaperOrderExecutor.__init__(initial_balance, state_file, reset)`**
  - state 檔存在且未 reset → `_load_state()` 還原 balance + positions + realized_pnl
  - 每次成交後 `_save_state()`（atomic write：tmp + rename，避免寫壞）
  - 還原失敗（檔案損壞）→ warning + 從頭開始（不會 crash）
- **`create_executor(PAPER)`**：接受 `paper_state_file` / `reset_paper` 並轉傳
- **CLI `start`**：新增 `--paper-state PATH` / `--reset-paper`
- **`scripts/restart_vbt.sh`**：`RESET_PAPER=1` / `PAPER_STATE` 環境變數透傳；預設還原

### state 檔格式（`data/paper_account.json`）
```json
{
  "balance": 9872.0,
  "realized_pnl": 10.0,
  "positions": [
    {
      "symbol": "BTCUSDT",
      "position_side": "LONG",
      "entry_price": 64000.0,
      "quantity": 0.01,
      "leverage": 5,
      "realized_pnl": 0.0
    }
  ]
}
```

### 測試（6 個）
重啟還原、`reset=True` 忽略 state、無 state 全新帳戶、全平倉後 realized 跨重啟保留、state JSON 正確、`create_executor` 參數傳遞

---

## 驗證

- 新測試 14/14 通過
- 完整套件 111 passed；2 個既有 integration 失敗（`test_model_validation_fix.py` T1 為既有問題、T3 為測試順序 flaky），經 `git stash` 比對確認與本次改動無關
- VBT 已於 10:01:47 重啟載入（PID 2899392），state 檔將於第一次成交後建立

## 已知限制
- paper 帳戶狀態存在 **JSON 檔**（非 DB），單機單進程使用 OK
- `update_price` 的浮盈不寫入 state（重啟後由市價重新計算）
- 若要多人/多進程共享帳戶，需改 DB 儲存 + 鎖
