# SPEC: VBT_EXECUTION_ORDER_BUILDER_FIX (B1-B6 執行鏈修復)

- 日期: 2026-08-13
- 分支: `local/brian`
- 狀態: SWDA Stage 3 (Draft, 待子代理收斂)

## 1. 問題陳述

VBT testnet 執行層自 2026-08-09 18:57 起癱瘓：DB 252 筆 orders = 213 REJECTED_BY_RISK + 13 REJECTED_BY_EXCHANGE_FILTER + 26 FILLED（最後 FILLED 08-09）。決策引擎正常（每 30m bar 產出 BUY/SELL/HOLD），但訂單從未落地。

## 2. 根因樹（源碼實證）

### R1 (P0) — B5+B6: PM approved 後無單，保險安全網同時失效
- **B5**: 2026-08-13 04:07:20 / 04:07:26 兩筆 risk check **APPROVED**（qty=0.001, positionSide=LONG, ref=63618.7, notional=63.6 < 100）
  - `execution_risk_checks` id=342/343 存在，但 `execution_orders` **無對應記錄**，`bar_decision_journal` 最新 `executions_json=[]`
  - 斷鏈點: `agent_tools.py` L715 `await tool_context.executor.place_order(...)` **無 try/except** → Binance testnet API 400（position_mode 不符）→ `binance_client.py` L367 `raise Exception(f"API Error: {data}")` → 異常傳回 PM agent loop 被吞 → `record_order` (L744) 從未執行
- **B6**: `trading_coordinator.py` L843-865 執行對帳 `has_order = bool(orders)` — 把 **REJECTED_BY_RISK 的 order 記錄也算 has_order** → 04:07:16 的 order#252 (REJECTED) 讓保險誤判「已有訂單」→ `_auto_execute_insurance` 不觸發 → approved 無單時安全網癱瘓

### R2 (P1) — B1-B4: 保險路徑自建訂單參數分裂
- **B1**: `trading_coordinator.py` L1472-1483 cap 後 qty=100/63416.37=0.0015768 **未 floor stepSize 0.0001** → order#249 REJECTED_BY_EXCHANGE_FILTER
- **B2**: L1507 `reference_price=entry.get("price")` 用**原始 entry**，非 L1465-1471 fallback 後變數 → PM 決策無 price 時 = None → order#250 rejected "reference price is required"
- **B3**: L1488 `str(position_side or "BOTH")` 預設 BOTH 撞 `position_mode=hedge`（pre_trade_risk.py L141-149 要求 LONG/SHORT）→ order#251 rejected
- **B4**: 第一次嘗試 qty=0.01（trading_plan 倉位）無視 cap → order#252 rejected notional 636>100

### R3 (環境) — executor 切換
- 8/9 前 fills 全是 `paper_xxx`（PaperOrderExecutor）；8/9 18:57 後 daemon 重啟 → `--mode testnet` → BinanceOrderExecutor → testnet 帳戶 position_mode 與 code policy (hedge) 不一致 → place_order 400
- risk checks `available_balance=5000.0`（testnet 帳戶餘額）vs DB snapshot `~9980`（paper 帳戶）— 兩個帳本分裂

## 3. 修復設計

### 3.1 新增 `backend/src/vibe_trading/execution/order_builder.py`（唯一訂單建構入口）

```python
class MissingReferencePriceError(ValueError): ...

def floor_to_step(qty: float, step_size: float) -> float:
    """0.0015768 → 0.0015 (floor 到 step 整數倍)"""

def compute_quantity(*, notional_cap, reference_price, step_size, min_qty, min_notional) -> float:
    """qty = floor(notional_cap / reference_price 到 step)；校驗 ≥ min_qty & notional ≥ min_notional"""

def resolve_position_side(side: OrderSide, position_mode: str) -> PositionSide:
    """hedge → BUY=LONG / SELL=SHORT；one_way → BOTH"""

@dataclass
class OrderBuildResult:
    symbol, side, order_type, quantity, price, reference_price, position_side, reduce_only, rationale
```

### 3.2 保險路徑改用 OrderBuilder（trading_coordinator.py L1430-1524）
- reference_price 必填：`entry.price` → executor.get_reference_price() → **raise MissingReferencePriceError**（不再送 None）
- qty: `compute_quantity()`（cap + floor + min 校驗，一次到位修 B1/B2/B4）
- position_side: `resolve_position_side()`（修 B3）
- 移除 L1461-1485 手工 cap 邏輯（改由 builder 保證）

### 3.3 執行對帳修正（trading_coordinator.py L855）
- `has_order` 只認 FILLED / SUBMITTED / PENDING（或 status 不含 REJECTED）→ 修 B6
- 加 `_last_insurance_at` cooldown（≥ 300s）防 6 秒 3 連砲

### 3.4 PM 路徑斷鏈可觀測（agent_tools.py L715）
- `place_order` 包 try/except → 失敗時 record_order(status="REJECTED_BY_BROKER", result=含錯誤訊息) → 保險可見、log 有 traceback
- 不做 retry（交給保險路徑單次補送）

### 3.5 不做（scope 邊界）
- 不動 `EXECUTION_MAX_SINGLE_ORDER_NOTIONAL=100` / pre_trade_risk 拒絕行為（213 筆 rejection 證明守門正常）
- 不重構 coordinator / agent loop
- 不修 WEAK 決策執行策略（維持 Fix ③: WEAK 不觸發保險）— 獨立決策另開 ticket
- 不修 QualityTracker SELL vs WEAK SELL 記錄不一致（純日誌語意，獨立 ticket）

## 4. TDD 測試契約

| # | 測試 | 檔案 | 預期 (Red) |
|---|---|---|---|
| T1 | floor_to_step(0.0015768, 0.0001) == 0.0015 | tests/execution/test_order_builder.py | fail (無此模組) |
| T2 | compute_quantity(100, 63618.7, 0.0001, 0.0001, 50) == 0.0015 且 notional ≤ 100 | 同上 | fail |
| T3 | reference_price=None → raise MissingReferencePriceError | 同上 | fail |
| T4 | resolve_position_side: hedge+BUY→LONG, hedge+SELL→SHORT, one_way→BOTH | 同上 | fail |
| T5 | min_notional 邊界: 重算後 notional < 50 → raise | 同上 | fail |
| T6 | 保險路徑 rejected order 不再阻擋保險（B6） | tests/coordinator/test_insurance_execution.py | fail |
| T7 | 保險路徑 approved 後必有 order 記錄（B5 回歸） | 同上 | fail |
| T8 | 保險 cooldown: 60s 內不重送 | 同上 | fail |

執行: `cd backend && uv run python -m pytest tests/execution/test_order_builder.py tests/coordinator/test_insurance_execution.py -v`
（新測試檔 .gitignore 忽略 → `git add -f`）

## 5. 驗證

1. Regression: `uv run python -m pytest tests/ --ignore=tests/integration`（baseline 129 passed，不得回歸）
2. 重啟 daemon（PID 2428017 → 新 code）
3. 下一個 30m bar 實證: `execution_orders` 出現 FILLED 或至少非 REJECTED_BY_RISK；snapshot 恢復更新
4. 盈虧對照: testnet 帳戶餘額（5000）而非 DB paper snapshot（9980）

## 6. Rollback

- `git revert` 修復 commit → 重啟 daemon
- 空窗: 最壞 1 個 bar cycle（30m + 決策 550-890s）無單 = 現狀同等（已癱瘓 4 天），無額外風險
- 修復前備份: `vibe_trading.db` + 相關 .py（鐵律 #8）

## 7. Commit 規劃

1. `feat(execution): [VBT] OrderBuilder 統一訂單建構 (B1-B4)`
2. `fix(coordinator): [VBT] 對帳只認有效訂單 + 保險 cooldown (B6)`
3. `fix(execution): [VBT] PM place_order 失敗可觀測 (B5)`
