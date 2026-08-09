---
title: "Silent Stream Failure"
description: "Incident report: Silent Stream Failure"
date: 2026-08-04
category: incident
tags: [incident, bug-fix, debugging, post-mortem]
---

# VBT 修正計畫：LLM 串流靜默失敗導致連續 UNKNOWN（2026-08-04）

## 1. 問題摘要

**現象**：2026-08-04 03:00–04:00 連續三根決策 UNKNOWN(0.30)。
**根因**：LLM stream 以 `stop=error` + 空內容結束時，被 `pi_agent_core` 當作成功處理，agent 回傳空字串報告，無異常拋出。News/Sentiment/Bull/Bear 全空 → PM 只剩 Fundamental 一個輸入源 → UNKNOWN。

**證據鏈**（logs/vbt_restart_20260804_014131.log + trading log）：
```
2293 stream_open 開始 03:00:01
2295 ✓ stream_assistant_response 完成 stop=error 03:00:04
2296 assistant_msg.content 型別數: 0 內容: []
2297 → Analyst Sentiment Analyst Analysis:     ← 空
```
- 退化時間線：02:00 Sentiment 空 → 03:00 News+Sentiment+辯論全空 → 只剩 Fundamental
- 失敗 agent 都是「第一輪 tool_calls → 執行工具 → 第二輪 stream error」模式；Fundamental/Risk 一次成功
- 高度懷疑 opencode zen 端點在多路並發呼叫（4 analyst + 2 debater + 3 risk + PM + macro）時過載/限流

## 2. 程式碼層級根因（已定位）

| 位置 | 問題 |
|------|------|
| `backend/src/pi_ai/llm.py:661-684` | stream 異常處理：429→raise `LLMRateLimitError`、529/503/502→raise `LLMConnectionError`，但**其他錯誤只 `yield StreamErrorEvent` 不 raise** → retry handler 攔不到 |
| `backend/src/pi_agent_core/agent.py` `_run_loop` except 分支 (~L520) | catch 後產生 `stop_reason="error"` + `content=[TextContent(text="")]` 的 error_msg 並 append_message，**不 re-raise** → 上層以為成功 |
| `backend/src/pi_agent_core/agent_loop.py:151` | `if stop_reason in ("error","aborted")` 直接結束，空 content 當最終回應 |
| `backend/src/vibe_trading/agents/analysts/base_analyst.py` `analyze()` | 空 content → `""` 回傳，不檢查、不重試 |
| `backend/src/vibe_trading/coordinator/trading_coordinator.py` `_run_analysts_parallel` | try/except 只攔異常，攔不到「成功回傳空字串」 |

## 3. 修正方案（按優先級）

### Fix 1（P0 治本）：串流失敗 → 重試 + 可見失敗

**1a. `pi_ai/llm.py` 其他錯誤分支補 raise（最小改動）**
- 在 `llm.py:684` 的「其他錯誤」分支補 `raise LLMStreamError(provider=model.provider, message=error_str)`
- 讓 `StreamRetryHandler.execute_stream_with_retry` 能攔截（`LLMStreamError` 已在 `retry_handler.py:47-57` 的 retryable_exceptions）
- 效果：所有 stream 錯誤都會自動重試（預設 max_attempts 指數退避），重試耗盡才失敗

**1b. `pi_agent_core/agent.py` `_run_loop` except 分支 re-raise（防護）**
- 目前 catch 後吞掉 → 改為：append error_msg 後 **re-raise 原異常**（或 `RuntimeError(f"LLM stream failed: {err}")`）
- 讓所有 agent 的 `analyze()/respond()` 自然拋異常 → coordinator 已能 catch 並記錄「analysis unavailable: ...」
- 需注意 `_run_loop` 同時服務 steering/continue 流程，re-raise 前確認不破壞正常 cancel 路徑（cancel 時維持原 aborted 行為）

**1c. `base_analyst.py` / `technical_analyst.py` / `researcher_agents.py` 空回應重試（防禦）**
- `analyze()/respond()` 對空 response（`""` 或 `len(content)==0`）重試 2–3 次（每次重新 `prompt()`），仍空則 `raise RuntimeError`
- 避免「成功但空」的隱性路徑（例如工具執行後模型沒產生文字）

**驗證**：
- 單元測試：mock stream_fn 回 `stop=error` → 斷言 retry 觸發、最終 raise
- 重啟 VBT 後觀察 1–2 根決策：`agent_contributions` 應恢復四 agent 皆有權重；若 LLM 端點持續失敗，log 應出現明確 error 而非靜默空報告

### Fix 2（P1）：LLM 併發節流

**位置**：`trading_coordinator.py:_run_analysts_parallel`（~L856）、`_run_research_debate`、risk 階段
**做法**：
- Phase 1 四路 analyst 並發改為 `asyncio.Semaphore(2)` 限制同時最多 2 路
- 確認 `pi_ai/retry_handler.py` RateLimitConfig（預設 max_concurrent=3, rpm=100）實際生效；若已生效仍看到多路同時 stream_open，調低到 2
**驗證**：log 中同時 `stream_open` 數 ≤ 2

### Fix 3（P1）：fallback model

**位置**：`agent_factory.py:create_trading_agent`（model_router 未配置，log: "未配置模型路由，使用单一模型模式"）
**做法**：
- 配置 model_router 或手動 fallback：主模型（opencode_zen_deepseek_v4_flash）連續失敗 N 次 → 切備援（llm.yaml 已有 deepseek / openai_gpt4o_mini / claude_sonnet4）
- 最低成本版：在 Fix 1a 的 retry handler 耗盡後，用備援 model 再試 1 次
**驗證**：斷言失敗時 log 出現 "fallback to <model>"

### Fix 4（P2）：journal 資料串接

**現象**：所有根（含正常根）reports/logs/phase_status 皆為 `{}`
**位置**：`quality_tracker.py:_persist_decision`（~L386，只寫 decision payload）；coordinator 未把 analyst_reports/logs 傳入 journal
**做法**：coordinator 在各 phase 完成後呼叫 `journal_storage.upsert_bar(update={"reports": ..., "logs": ...})`，或把 phase 資料併入現有更新點
**驗證**：DB 中 reports_json 非空

### Fix 5（P2）：執行模板方向-參數校驗

**現象**：Risk LLM 第 3、4 期連續警告「方向=HOLD 卻綁 SHORT 參數（上方止損/下方止盈）+ 市價開倉指令」
**位置**：`trading_coordinator.py:_run_trader`（~L1117 direction 提取）、`execution/` 參數模板產生處
**做法**：產生執行計畫後加一致性校驗：HOLD → 不允許開倉指令；LONG → 止損必須在下方、止盈在上方；SHORT → 鏡像。不一致則攔截並標記不可執行
**驗證**：單元測試三種方向 × 參數組合

### Fix 6（P3）：macro 資料源

**現象**：02:41/03:41 macro 皆稱 "No price change, funding rate, trending symbols available"
**位置**：`macro_agent` 資料獲取處
**做法**：單獨調查資料源（疑似與 Fix 2 併發限流相關，或 Binance REST 資料缺失）

## 4. 執行順序與風險

| 步驟 | 內容 | 風險 | 回滾 |
|------|------|------|------|
| 1 | Fix 1a（llm.py 補 raise） | 低：只讓錯誤可見+重試 | 單行 revert |
| 2 | Fix 1c（agent 空回應重試） | 低 | revert |
| 3 | Fix 1b（agent.py re-raise） | 中：影響所有 agent 流程，需測 steering/cancel | revert + 完整重啟測試 |
| 4 | Fix 2（併發節流） | 低 | revert |
| 5 | Fix 3（fallback） | 中：需確認備援 model 可用 | revert |
| 6 | Fix 4/5/6 | 各自獨立 | 各自 revert |

每步完成後：跑 pytest + 重啟 VBT（`scripts/restart_vbt.sh`）觀察 1 根決策確認無回歸。

## 5. 本次不動

- 問題 1（決策解析 bug）：獨立議題，另排
- 模型切換（換掉 opencode zen）：等 Fix 1–3 後若仍頻繁失敗再評估
