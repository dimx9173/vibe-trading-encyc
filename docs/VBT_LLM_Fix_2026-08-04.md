# Vbt LLM 修復大作戰 — 從「瞎子交易」到真 AI 交易系統 (2026-08-04)

> 建立日期: 2026-08-04
> 對應 Commits: `6c002e6` `7423044` `7fbdebc` `8baf8c6` `dc6ff39` `6bbc06e` `d5bd69f` `e069bdf` `cd11793`（local/brian branch，未 push）
> 嚴重度: **CRITICAL** — 系統從未真正呼叫 LLM，所有決策都是空內容 fallback
> 修復結果: 決策耗時 2.83s → 343-491s（真實 LLM 分析），Quality 0.30 → 0.90

---

## 症狀

所有 agent（Analyst/Bull/Bear/Risk/Trader/PM）的 Analysis 欄位**全是空字串**：
- 決策耗時固定 2.83s（快得可疑，根本沒等 LLM）
- Trader 永遠 fallback 到 hardcoded `HOLD 1500 USDT`
- QualityTracker 永遠 0.30 (UNKNOWN)
- 但**沒有 401/403/auth 錯誤** — API key 有效，請求看起來有發

---

## 根因鏈（8 層 bug，逐層挖）

### Layer 1: AgentOptions.stream_fn 預設 None
`pi_agent_core/agent.py` 的 `AgentOptions.stream_fn: StreamFn | None = None`，而 vibe-trading **所有 7 個 AgentOptions 創建點都沒傳 stream_fn** → `Agent.stream_fn = None` → `agent_loop` raise `ValueError("No stream function provided")` → 被 `Agent.run()` 的 `except Exception` 吞掉 → 產生**空內容 AssistantMessage**。

### Layer 2: config.py env var 解析全壞
`${OPENAI_API_KEY:***` 這類 interpolation，config.py 用 `api_key.endswith(":")` 判斷（但 pattern 結尾是 `}`）→ **所有 config 的 api_key 都是字面值**，從沒 resolve 過。

### Layer 3: pi_ai vs pi_agent_core 重複定義 class
兩個 package **各自定義同名的 `AssistantMessage` / `ToolCall` / `Message`**（一個 dataclass、一個 Pydantic BaseModel）→ 跨 package 的 `isinstance` 檢查**永遠 False**、Pydantic discriminator 驗證**永遠失敗**。這是整場 debug 的核心魔王。

### Layer 4: base_url 路徑重複
`llm.yaml` 寫 `https://opencode.ai/zen/go/v1/chat/completions`，但 AsyncOpenAI client **自動加 `/chat/completions`** → 實際打到 `/chat/completions/chat/completions` → 404 HTML。

### Layer 5: site-packages vs backend/src 兩份 code
VBT import 的是 **`.venv/lib/python3.14/site-packages/pi_agent_core`**（copy 安裝的舊版），不是 `backend/src/pi_agent_core`（改的 source）！所有修改「看起來生效」（pyc 有更新）但進程根本沒載入。**解法：symlink site-packages → backend/src**。

### Layer 6: rate limiter semaphore 洩漏
`LLMRateLimiter.acquire(model_id)` 在 model 不在 `model_limits` 時用**全域 semaphore**（值 3），但 `release(model_id)` 只查 per-model semaphore → **永不釋放** → 第 4 次並發呼叫起全部 `LLM 获取并发许可超时 (30.0s)`。

### Layer 7: streaming 消費階段無 timeout
`execute_stream_with_retry` 的 `asyncio.wait_for` 只包「建立 StreamResponse」（<1s），真正的 `async for event in response` 消費階段在 timeout 外 → opencode.ai 中途卡住就永久等待。

### Layer 8 (真正 root cause): isinstance 跨 package 失敗
`provider.stream()` 產生 pi_ai 的 ToolCall 放進 assistant_msg.content，但 `agent_loop` 用 `isinstance(c, pi_agent_core.ToolCall)` 檢查 → **永遠 False** → `tool_calls=0` → 工具從不執行 → 第二輪 context 有 assistant tool_calls 但無 tool results → opencode.ai 回 400 `tool_calls must be followed by tool messages` → 決策卡死。

---

## 修復（8 個 commit 摘要）

| Commit | 修什麼 |
|--------|--------|
| `6c002e6` | config.py 改用 regex resolver 解析 `${VAR}` / `${VAR:default}` |
| `7423044` | llm.py 加 `VBT_DEBUG_LLM=1` gated debug logging（stream_open/FIRST_DELTA/STREAM_END）|
| `7fbdebc` | agent.py 加 `_get_default_stream_fn()` fallback（包 stream_simple 成 `{"events","result"}` shape）+ 放寬 event message 欄位為 Any |
| `8baf8c6` | restart script 加 `setsid`（防 exec session 清理時 SIGTERM 殺進程）|
| `dc6ff39` | default stream_fn 改用 `stream_simple_with_retry` + 60s timeout |
| `6bbc06e` | rate limiter `release()` 改成跟 `acquire()` 對稱（model 在 limits 才用 per-model，否則全域）|
| `d5bd69f` | `_stream_once()` 用 `asyncio.timeout` 包整個 streaming 迭代（保護消費階段）|
| `e069bdf` | **duck typing ToolCall 檢查**（`hasattr(name) + class name`）+ `AgentContext.messages` 放寬 `list[Any]` |

---

## 環境陷阱（重要，別再踩）

1. **VBT import 的是 site-packages 的 `pi_agent_core`，不是 `backend/src/`！** 已用 symlink：`site-packages/pi_agent_core → backend/src/pi_agent_core`。改 code 後確認 pyc 更新或清 `__pycache__`
2. **opencode.ai base_url**：`https://opencode.ai/zen/go/v1`（AsyncOpenAI 自動加 `/chat/completions`，寫全路徑會 404）
3. **API key 有兩份**：os.environ 有 stale 167-char key；`.env` 是正確 67-char key。測試/重啟**一定要 source .env**
4. **`LLM_MODEL` env var 覆蓋 llm.yaml 的 `use_llm`**（`backend/src/vibe_trading/config/settings.py:72`）。現值：`opencode_zen_deepseek_v4_flash`
5. **llm.yaml 和 .env 都在 .gitignore**（本機 only）
6. **debug print 走 stdout → restart log**；logger 走 `logs/trading_BTCUSDT_*.log`
7. **DeepSeek V4 Flash 是 reasoning model**：先輸出大量 `reasoning_content` 才出 content/tool_calls
8. **工具執行有參數格式問題**（opencode.ai 回 `arguments={'type':...}`），但 **LLM 會自癒重試**（「讓我嘗試不同的參數格式」），不影響流程

---

## 驗證

- ✅ 22:30 決策：**BUY (Quality 0.90)**，完整決策鏈 Analyst×3 → Bull/Bear 多輪辯論 → 風控 → Trader（完整執行計畫）→ PM，耗時 475s
- ✅ 23:00、23:30、00:00、00:38 連續決策全成功（343-491s）
- ✅ 8-tool Agent 完整流程（工具執行 + LLM 自癒重試 + 多輪往返）
- ⏳ paper mode 驗證：2026-08-04 00:44 切換（testnet dry-run → PaperOrderExecutor），等首筆 `paper_` order

---

## 教訓

1. **「看起來有在跑」≠「真的有在跑」** — 2.83s 決策 + 空字串，一整個系統都在 fallback，但沒有任何 error。要加 debug logging 才有真相。
2. **跨 package 同名 class 是隱形炸彈** — `isinstance` 靜默失敗、Pydantic 驗證靜默失敗，都不報錯。遇到「明明有內容但檢查不到」先懷疑 class identity。
3. **獨立測試成功 ≠ 系統成功** — /tmp 測試全過（新 process 乾淨），VBT 內必卡（進程狀態 / site-packages / 連線池差異）。要複製真實呼叫路徑。
4. **改 code 後確認進程真的載入** — symlink / pycache / site-packages 都可能讓修改「看似生效」。
5. **timeout 要包對層級** — 建立 vs 消費是兩個階段，只包建立等於沒包。

---

## TODO (Next Iteration)

- [ ] paper mode 觀察首筆 `paper_` order 是否正常（order_id 前綴確認）
- [ ] QualityTracker 0.90/0.30 交替原因（部分決策某 agent 內容被判 UNKNOWN）
- [ ] 工具參數格式問題（opencode.ai `arguments={'type':...}`）— 目前 LLM 自癒，但可考慮修 schema
- [ ] 「持倉數量對不上」謎題：8 筆 BUY fills = 0.01226 BTC vs position snapshot 0.00156 BTC（0.0107 BTC 去向不明，無 SELL 紀錄）
- [ ] 追蹤 `VBT_DEBUG_LLM` 是否該常駐（目前 production 也開著）
