# 2026-08-09 — VBT Replay 3 Bars SWDA 分析報告

> 類型：Postmortem / SWDA 分析
> 範圍：`replay_leg_a.py` 3 bars replay（BTCUSDT 30m, 2026-07-24 07:00–08:00 UTC）
> 結論：Replay 存在 **live data look-ahead 污染（P0）** 與 **決策記錄與實際執行不一致（P0）**，回測結果不可信，需修復後重跑。

---

## 1. 現象（JSONL 表面 vs 帳戶實際狀態）

執行：`backend/.venv/bin/python replay/replay_leg_a.py --bars replay/data/bars.json --start 120 --end 123`
輸出：`replay/data/leg_a_3bars_v2.jsonl`

| Bar | 記錄決策 | 帳戶實際狀態 | 一致？ |
|---|---|---|---|
| 1 (07:00) | UNKNOWN | 無倉位，balance 10000 | ✅ |
| 2 (07:30) | UNKNOWN | **LONG 0.0015 @ 65202.1**，balance 9980.89 | ❌ |
| 3 (08:00) | WEAK BUY | 倉位維持 0.0015，未加倉 | ❌ |

表面看起來「2 根 UNKNOWN + 1 根 WEAK BUY 有開倉」，實際是 **bar 2 就已成交開倉但決策記錄 UNKNOWN**；**bar 3 決策 WEAK BUY 卻完全沒加倉**。兩者都是決策記錄與執行狀態脫鉤。

## 2. 根因分析

### 根因 1（P0）：Replay 有 Live Data 污染（Look-ahead）

- **鐵證**：bar 2 的 LLM 輸出「当前价格是 **65202.1**，比计划中的 **65499.95** 略低」— 65499.95 是 replay bar 2 的真實 close，65202.1 是 **2026-08-09 當下的實時價格**（agent 透過 `get_current_price` live tool 取得）。
- bar 3 PM 報告「当前价格 65,210.6」≠ bar 3 close 65,390.01 — 又是 live 價格。
- 成交價 65202.1 也是 live price，不是 replay bar close。
- **這是 8/7 教訓「live tools 在 replay 是 look-ahead 污染源」的再現**：B 側有 `btc_replay_desk.yaml`（禁 live tools），但 **A 側 `replay_leg_a.py` 用完整 13-agent TradingCoordinator，tools 沒禁** → 每次決策混入當下市場數據（價格、訂單簿、資金費率、多空比），回測結果不可信。

### 根因 2（P0）：PM timeout 後「已下單但決策記錄 UNKNOWN」

bar 2 時序（audit DB `execution_orders` 鐵證）：

| 時間 | 事件 |
|---|---|
| 15:52:04 | order#133 REJECTED（0.023 BTC，單筆 notional 超限） |
| 15:52:10 | **order#134 FILLED 0.0015 @ 65202.1**（rationale 寫「Portfolio Manager最終決策：WEAK BUY…約10美元測試倉」） |
| 15:52:21 | PM LLM **45s timeout** → fallback scorecard → decision_text 空 → **UNKNOWN** |

- PM agent 在 timeout 前已呼叫 `submit_trade_order` tool 並成交，但 45s timeout 切斷了最終決策輸出 → JSONL 記錄 UNKNOWN 但實際有倉。
- 這也解釋了稍早人工判讀被誤導：帳戶快照 bar 2 就有倉，但 decision=UNKNOWN。

### 根因 3（P1）：Signal Parser 把 WEAK BUY 誤判成 BUY → 保險暴衝

- bar 3 PM 明確決策 **WEAK BUY**（弱買入，小倉位加倉），且未下單（符合規範）。
- 但 QualityTracker 記錄 **BUY (0.80)** → 觸發「執行對帳」→ 啟動 coordinator 保險。
- 保險用 **trading_plan 的完整倉位 0.04579 BTC（≈2994 USDT）** 下單 → 被風控攔下（單筆 notional >100 USDT 限制）→ 所以 bar 3 沒加倉。
- **幸運**：風控擋住了，否則會開出 PM 明說不要的 3000 USDT 倉位。保險完全忽略 PM 的「小倉位」執行指示。

### 根因 4（P2）：PM 45s timeout 對 DeepSeek V4 Flash 太短

- 3 根 bar 中 2 次 PM timeout → UNKNOWN + 空 rationale。
- 8/7 成功那次用 mimo-v2.5（456.5s/bar）；V4 Flash 在 PM 複雜 prompt 下仍不穩定。

## 3. 修復建議（依優先序）

1. **P0**：replay 建立專用 tool context — `get_current_price` 等工具回傳 bar 內數據（bar close），其餘 live tools 禁用 → 消除 look-ahead。
2. **P0**：PM timeout fallback 時若 trace 已有成交訂單 → 決策記錄必須回填實際執行（如 `WEAK BUY (timeout fallback, order filled)`），禁止 UNKNOWN 掩蓋已成交。
3. **P1**：修正 signal parser — 「弱买入/WEAK BUY」必須映射 WEAK_BUY 而非 BUY；保險觸發條件排除 WEAK_BUY/WEAK_SELL。
4. **P1**：保險自動執行改用 PM 決策的倉位大小，不得用 trading_plan 完整倉位覆蓋 PM 指示。
5. **P2**：PM timeout 提高到 90s 或切回 mimo-v2.5。

## 4. 證據檔案

- 決策輸出：`replay/data/leg_a_3bars_v2.jsonl`
- 完整 log：`replay/data/leg_a_3bars_run.log`（497k 行）
- 帳戶狀態：`replay/data/leg_a_3bars_state_v2.json`
- audit DB：`vibe_trading.db`（`execution_orders` / `execution_risk_checks`，trace `BTCUSDT:30m:1784878200000` = bar 2，`1784880000000` = bar 3）

---

## 5. 修復狀態（2026-08-09 18:50，commit d7306ac）

### ① 已修復 ✅ — Replay 禁 live tools（look-ahead 消除）
- 新增 `replay/replay_tool_isolation.py`：monkey-patch `market_data_tools` / `fundamental_tools` / `sentiment_tools` / `technical_tools`，
  讓價格類工具改從 replay storage 讀 bar close、技術指標帶入 replay storage、其餘 live 工具回傳「replay 不可用」。
- `replay_leg_a.py` 在建立 coordinator 後安裝 isolation。
- 驗證（smoke test + 1-bar replay）：`get_current_price` 回傳 **65641.31**（replay bar close，原本 live 65202.1）；
  funding/order_book/long_short/fear_greed 全部回傳不可用；技術指標正常從 storage 計算。

### ② 已修復 ✅ — 決策/執行脫鉤（timeout fallback 回填）
- `trading_coordinator.py` 新增 `_decision_fallback_from_audit()`：PM 決策 UNKNOWN/HOLD 但 audit 顯示該 bar 有 FILLED 訂單時，
  從訂單 rationale 提取 PM 原決策（如 WEAK BUY）回填，禁止 UNKNOWN 掩蓋已成交。
- 驗證：1-bar replay 決策 = **WEAK BUY**（原本 UNKNOWN），成交價 65641.31 = replay close。

### ③④⑤ 尚未執行（P1/P2）
- ③ signal parser：WEAK BUY 誤判 BUY → 保險暴衝（風控已攔下，安全網運作正常）
- ④ 保險自動執行應改用 PM 決策倉位
- ⑤ PM timeout 45s → 90s 或換 mimo-v2.5
