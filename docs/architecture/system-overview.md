# VBT (Vibe Trading) 系統架構全覽

> 建立日期: 2026-08-04
> Repo: `~/project/vibe-trading` (branch: local/brian)
> 基於實際 code 分析（2026-08-04），官方文件見 `docs/guide/architecture.md`

> ⚠️ **收斂計畫更新（2026-08-28，權威文件 `docs/specs/money-printer-convergence-plan.md`）**：本文件原始分析基準為 2026-08-04。收斂後系統改為 **Binance 單交易所**（BTCUSDT / ETHUSDT / SOLUSDT，30m），主執行回路是**規則層**（AlphaZoo 因子 → 信號 → Half-Kelly 倉位 → EvidenceGate/grounding → ExitLadder 出場）；LLM 僅保留每2小時一次 macro regime 判定（24hr 30m K線投喂, 48 bars, 4hr staleness 容忍一次失敗，RISK_ON / NEUTRAL / RISK_OFF，RISK_OFF 禁開新倉）。下方描述的 12-agent 辯論鏈（Phase 1–5 LLM 流水線）**代碼與測試保留，但僅留作離線手動對照，不進入任何自動交易回路**（見收斂計畫 Q9、Q2/Q6）。已物理刪除的模組：OKX/Bybit/Bitget/Hyperliquid/Jupiter executor、broker_connector、SOR、MCP server、Pine/MQL5 exporter、prime 模式（見 Q10）。

---

## 1. 系統總覽

VBT 是 **AI 驅動的多 Agent 協作量化交易系統**，用 12 個專業 Agent 組成 4 階段決策流水線，搭配三線程架構即時響應市場。

```
┌─────────────────────────────────────────────────────────┐
│                    三線程架構                            │
│  Macro Thread (2hr, 24h K線投喂)  OnBar Thread (K線)  Event Thread    │
│  ────────────────  ────────────────   ────────────────  │
│  宏觀分析          完整決策流程        緊急事件響應       │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│              TradingCoordinator (核心決策引擎)           │
│  Phase1 分析師 → Phase2 辯論 → Phase3 風控 →             │
│  Phase4 交易員 → Phase5 PM → 決策輸出                    │
└─────────────────────────────────────────────────────────┘
```

> 上圖 TradingCoordinator 內的 Phase1–5 LLM 流水線（含辯論）保留作離線手動對照，不進入自動交易回路（收斂計畫 Q9）；線上決策由規則層主引擎驅動，LLM 僅做每2小時 RISK_ON/NEUTRAL/RISK_OFF regime gate（24hr 30m K線投喂, 48 bars, 4hr staleness 容忍一次失敗，Q6）。

**核心檔案**：
- 入口: `backend/src/vibe_trading/cli.py`
- 三線程: `backend/src/vibe_trading/main/multi_thread_main.py`
- 決策引擎: `backend/src/vibe_trading/coordinator/trading_coordinator.py`
- LLM 層: `backend/src/pi_ai/` + `backend/src/pi_agent_core/`
- 執行層: `backend/src/vibe_trading/execution/`
- Agent 工具: `backend/src/vibe_trading/agents/agent_tools.py`

---

## 2. 啟動流程

```bash
vibe-trade start BTCUSDT --interval 30m --mode paper --web --web-port 8001
```

CLI (`cli.py`) 流程：
1. 設定 logging（`configure(log_level, json_output, enable_file_logging)`）
2. 驗證交易模式：`paper`（預設）/ `testnet` / `live`
   - **live 無 `--execute`** → dry-run 只印單，需二次確認
   - **live 有 `--execute`** → 真錢交易，需二次確認（default=False）
3. 建立 `MultiThreadedTradingSystem` → `initialize()` → `start()` → 阻塞等 shutdown

`MultiThreadedTradingSystem` (`main/multi_thread_main.py`)：
- 建立 `MacroAnalysisThread`、`OnBarThread`
- 註冊預設 triggers（價格/風險）
- `_run_event_thread` 監控 trigger 事件 → `_handle_trigger_event`

---

## 3. 三線程架構

### Macro Thread（`threads/macro_thread.py`）
- 頻率：每2小時（7200s，`_should_update` 檢查；24hr 30m K線投喂, 48 bars, 4hr staleness 容忍一次失敗）
- 任務：分析市場趨勢、整體情緒、宏觀事件 → 更新 `macro_states`
- 輸出：`MacroAnalysisAgent` 的宏觀狀態（trend_direction / market_regime / sentiment）

### OnBar Thread（`threads/onbar_thread.py`）
- 觸發：新 K 線到達（WebSocket 訂閱 `btcusdt@kline_30m`）
- 任務：`_process_kline` → 觸發線上決策（**規則層主引擎**：AlphaZoo→信號→Half-Kelly→EvidenceGate→ExitLadder，受每2小時 LLM RISK_ON/NEUTRAL/RISK_OFF regime gate 約束（24hr 30m K線投喂, 48 bars, 4hr staleness 容忍一次失敗），RISK_OFF 禁開新倉）。12-agent LLM 5 階段流水線（13 agents）代碼保留，僅作離線手動對照，不進自動回路（收斂計畫 Q9）
- `_execute_trade`：目前是 placeholder（只 log），實際下單由 coordinator/executor 處理

### Event Thread（`threads/event` → `coordinator/event_queue.py`）
- 觸發：緊急事件（價格異常波動、風險超標）
- 處理：`_handle_trigger_event` → 應急流程（`coordinator/emergency_handler.py`）

---

## 4. 決策流程（TradingCoordinator.analyze_and_decide）

> **註（收斂計畫 Q9）**：以下 Phase 1–5 為保留的 12-agent LLM 辯論流水線代碼說明，僅供離線手動對照，**不進入自動交易回路**；線上決策由規則層主引擎產出。

`coordinator/trading_coordinator.py`，每根 K 線執行一次完整決策：

### 準備階段
- `_reset_agent_states()`：清除 pi_agent_core state leak（上次 failed cycle 的殘留）
- `_reflect_on_matured_decisions()`：回看已成熟的決策快照（N 根 bar 後評估）
- 狀態機初始化：`PENDING → ANALYZING`
- `_prepare_context()`：收集 symbol/price/indicators/positions/balance

### Phase 1: 分析師（`_run_analysts_parallel`）
- 並行執行 4 個分析師（asyncio.gather + per-agent lock）
- 技術 / 基本面 / 新聞 / 情緒分析師同時產出報告
- 各 agent 透過 `_get_analyst_data` 取得市場數據 + 工具呼叫
- 推送到 Web（send_report）

### Phase 2: 研究員辯論（`_run_research_debate`）
- `_token_optimizer.compress_prompt()` 壓縮分析師報告（target_ratio=0.8）
- Bull/Bear 多輪辯論（`settings.debate_rounds`，實際跑 2-4 輪）
- `run_debate_round()`：Bull 發言 → Bear 反駁 → 循環
- 每輪歷史累積（bull_history / bear_history）餵給下一輪
- ResearchManager 綜合 → 投資建議 + 置信度

**⚠️ Debate 防護機制（2026-08-09 新增）**：
- **三層防護**：移除 RETRY_COMPENSATORY_PROMPT（避免 reasoning model 進入 thinking loop）
- **45s timeout**：`asyncio.wait_for()` 包每次 attempt，防止無限思考
- **skip_debate 選項**：`SKIP_DEBATE=true` 環境變數可跳過整個 debate phase（快速驗證用）
- 重試邏輯：timeout 觸發 retry（最多 3 attempts），僅 `state reset()` 不補 prompt

### Phase 3: 風控評估（`_run_risk_assessment`）
- `run_risk_debate()`：激進 / 中立 / 保守 3 個風控 agent 同時評估
- 輸入：投資計畫 + 當前持倉 + 帳戶餘額

### Phase 4: 交易員（`_run_trader`）
- 從投資計畫**關鍵字提取方向**：做多/long/買入 → LONG；做空/short → SHORT；觀望/hold → HOLD
- `TraderAgent.create_trading_plan()` → 產生 TradingPlan（entry/SL/TP/leverage/execution_style）
- 之前 bug：LLM 分析內容會出現在 execution_notes 的 `LLM分析:` 欄位

### Phase 5: 投資組合經理（`_run_portfolio_manager`）
- `PortfolioManagerAgent.make_final_decision()` → 最終決策文本
- 從文本解析決策：STRONG BUY / BUY / WEAK BUY / HOLD / SELL / WEAK SELL / STRONG SELL

**⚠️ PM 決策保險機制（2026-08-06 新增）**：
- **問題**：LLM 決策 BUY/SELL 但漏呼叫下單 tool → 決策未執行
- **修復**：Coordinator 層級保險 — 決策 BUY/SELL 且該 bar 無訂單時自動觸發執行
- **流程**：重用 `submit_trade_order` tool 完整鏈（風控 → exchange filter → executor → audit）
- **對帳 key**：改用 `current_trace_id`（與 tool 記錄一致），避免 decision_id 格式誤報
- **Fail-open**：trading_plan 為 None / 缺 entry_orders 時不 crash
- **測試**：`backend/tests/test_coordinator_insurance.py`（4 tests）

### 決策後處理
1. `_signal_processor.process_signal()` → 提取結構化信號（signal/confidence/strength）
2. `_calculate_agent_contributions()` → 各 agent 貢獻度
3. `_determine_market_condition()` → 市場狀態
4. `QualityTracker.record_decision()` → 記錄決策品質
5. `DecisionSnapshot` 記錄（含 benchmark price）→ 供 N 根 bar 後反思

---

## 5. Agent 生態（13 Agents）

> **註（收斂計畫 Q9）**：下表 12-agent 辯論鏈（除 Macro 背景 Agent 外）代碼與測試保留，但僅留作離線手動對照，不進入自動交易回路；MacroAnalysisAgent 現承擔每2小時 LLM RISK_ON/NEUTRAL/RISK_OFF regime gate（24hr 30m K線投喂, 48 bars, 4hr staleness 容忍一次失敗，Q6）。

### 角色定義（`config/agent_config.py` AgentRole & `macro_agent.py`）
| 團隊 | Agent | Role | 運行線程 |
|------|-------|------|----------|
| 分析師 | 技術分析師 | technical_analyst | On-Bar Thread |
| | 基本面分析師 | fundamental_analyst | On-Bar Thread |
| | 新聞分析師 | news_analyst | On-Bar Thread |
| | 情緒分析師 | sentiment_analyst | On-Bar Thread |
| 研究員 | Bull 看漲 | bull_researcher | On-Bar Thread |
| | Bear 看跌 | bear_researcher | On-Bar Thread |
| | 研究經理 | research_manager | On-Bar Thread |
| 風控 | 激進風控 | aggressive_debator | On-Bar Thread |
| | 中立風控 | neutral_debator | On-Bar Thread |
| | 保守風控 | conservative_debator | On-Bar Thread |
| 決策 | 交易員 | trader | On-Bar Thread |
| | 投資組合經理 | portfolio_manager | On-Bar Thread |
| 宏觀背景 | 宏觀分析師 | MacroAnalysisAgent | Macro Thread (獨立週期) |

### Agent 建構（`agents/agent_factory.py` create_trading_agent）
- 統一用 `pi_agent_core.Agent` + `AgentOptions`（model、model_router、tools）
- **stream_fn 不傳 → 用 default（`_get_default_stream_fn` 包 stream_simple_with_retry）**
- 每個角色掛對應工具集（`get_tools_for_agent`）

---

## 6. LLM 層（重要）

### 架構
```
pi_agent_core (agent loop)  →  stream_fn  →  pi_ai (stream_simple_with_retry)
    │                                        │
    │  AgentOptions.stream_fn                ▼
    │  (default: _get_default_stream_fn)  provider.stream() → AsyncOpenAI
    │                                        │
    └── model_router ── 選 deep/quick model   └─ opencode.ai (DeepSeek V4 Flash)
```

### 兩個 package（⚠️ 歷史教訓）
- **`pi_ai`**：LLM 抽象層（`llm.py` / `enhanced_stream.py` / `retry_handler.py` / `model_router.py` / `config.py`）
- **`pi_agent_core`**：Agent loop（`agent.py` / `agent_loop.py` / `types.py`）
- ⚠️ 兩邊**各自定義同名的 `ToolCall` / `Message` / `AssistantMessage`**（一個 dataclass、一個 Pydantic）→ 跨 package `isinstance` 永遠 False（2026-08-04 修復：duck typing）
- ⚠️ site-packages 的 pi_agent_core 是 copy 安裝 → 已 symlink 到 backend/src

### 模型設定（`backend/src/vibe_trading/config/llm.yaml`）
- `use_llm: opencode_zen_deepseek_v4_flash`
- base_url: `https://opencode.ai/zen/go/v1`（AsyncOpenAI 自動加 `/chat/completions`）
- 多 config：openai_gpt4o、claude_sonnet4、gemini_pro、ollama、deepseek、opencode_zen 等
- ⚠️ `LLM_MODEL` env var 覆蓋 llm.yaml 的 `use_llm`（`config/settings.py:72`）

### 串流保護（2026-08-04 修復）
- `stream_simple_with_retry` + TimeoutConfig(stream_timeout=60s)
- `_stream_once()` 用 `asyncio.timeout` 包整個 streaming 迭代（消費階段）
- rate limiter release 對稱修復

---

## 7. 執行層（`execution/`）

### OrderExecutor 抽象（`order_executor.py`）
```
OrderExecutor (ABC)
├── PaperOrderExecutor      # 模擬交易，order_id 前綴 paper_，寫入 DB + JSON state 檔
└── BinanceOrderExecutor    # 真交易所（testnet/live），dry_run 可只印
```
- `create_executor(mode, dry_run, paper_state_file, reset_paper)`：paper → PaperOrderExecutor；testnet → Binance(testnet=True, dry_run)；live → Binance(dry_run)
- ⚠️ testnet 沒 `--execute` 時 dry_run=True → **只印不執行**（之前 5 根 BUY 沒成交的原因）

### Paper 帳本（2026-08-05 起，`d140d36` `8abb462`）
- **真實保證金帳本**：BUY 扣保證金（notional/leverage）、SELL 退還原保證金 + 結算 realized_pnl
- **realized_pnl 在 executor 層級累計**：全平倉 `del` 後不丟失
- **跨重啟持久化**：state 檔（預設 `data/paper_account.json`）存 balance/positions/realized_pnl，啟動自動還原；`--reset-paper`（或 `RESET_PAPER=1`）才重置
- 詳見 `docs/VBT_PAPER_LEDGER_FIX_2026-08-05.md`

### PositionManager（`position_manager.py`）
- 持倉追蹤：update_positions / get_positions / close_position
- 風險評估：get_total_exposure / assess_position_risks / get_risk_summary

### 其他
- `pre_trade_risk.py`：下單前風控
- `risk_manager.py`：風險管理
- `advanced_risk_tools.py`：進階風險工具
- `exchange_filters.py`：交易所過濾驗證
- `order_audit.py`：訂單稽核

---

## 8. 資料層

### Data Sources（`data_sources/`）
| 檔案 | 用途 |
|------|------|
| binance_client.py | Binance API 客戶端 |
| kline_storage.py | K 線儲存 |
| technical_indicators.py | 20+ 技術指標 |
| vendor_router.py | ~~多數據源路由（Binance/CoinGecko 備援）~~（現 Binance-only，多交易所路由已移除；收斂計畫 Q3/Q10） |
| providers/ | ~~Binance/OKX provider 抽象~~（OKX provider 已物理刪除，現 Binance-only；收斂計畫 Q10） |
| rate_limiter.py | API 限流 |
| fundamental_storage / news_storage / sentiment_storage / macro_storage | 各類數據儲存 |
| cache.py | 快取 |

### DB Schema（SQLite，`vibe_trading.db`）
| Table | 用途 |
|-------|------|
| execution_orders | 訂單（status: FILLED/REJECTED_BY_RISK 等） |
| execution_fills | 成交明細 |
| execution_position_snapshots | 持倉快照（positions_json/balances_json） |
| execution_risk_checks | 風控檢查紀錄 |
| macro_states | 宏觀狀態 |
| bar_decision_journal | K 線決策日誌（**web-only**，CLI 模式不寫入） |

---

## 9. 記憶系統（`memory/`）

### BM25Memory（`memory/memory.py`）
- BM25 演算法（k1=1.5, b=0.75）離線記憶系統
- `add_memory` / `retrieve_relevant`（top_k 檢索）
- 用於歷史交易經驗學習

### TradeReflector（`memory/reflection.py`）
- 決策後反思：回看已成熟的決策快照
- `_reflect_on_matured_decisions`：N 根 bar 後評估決策品質

### DecisionSnapshot（`memory/decision_snapshots.py`）
- 每根決策記錄：decision_id / price_at_decision / benchmark_price / confidence / context_digest

---

## 10. 品質追蹤（`coordinator/quality_tracker.py`）

- `record_decision()`：記錄決策（signal/confidence/strength/agent_contributions）
- `record_outcome()`：記錄結果（決策對照實際價格）
- `_update_agent_performances()`：更新各 agent 表現評分
- 決策品質分：**0.90 = 有完整信號；0.30 = UNKNOWN**（2026-08-04 觀察到 0.90/0.30 交替）
- `get_agent_ranking` / `get_top_performers` / `get_underperformers`（threshold 0.4）

---

## 11. 狀態機（`coordinator/state_machine.py`）

```
PENDING → ANALYZING → DEBATING → ASSESSING_RISK → PLANNING → EXECUTING → COMPLETED
   │          │           │            │             │            │
   └──────────┴───────────┴────────────┴─────────────┴────────────┴── FAILED / CANCELLED
```
- `DecisionStateMachine`：合法的 state 轉換表
- 每階段 transition 都會記錄原因（log）

---

## 12. Web 監控層（`web/`）

- `server.py`：FastAPI + WebSocket（即時推送 agent 報告）
- `journal_storage.py`：bar_decision_journal 持久化（**只被 web 模式呼叫**）
- `visualizer.py`：視覺化
- 前端：React（`frontend/`，Agent Arena 介面）

---

## 13. Backtest Engine（`backtest/`）

### 架構（2026-08-09 優化）
- **位置**：`backend/src/vibe_trading/backtest/engine.py`
- **策略**：MA-crossover（簡單移動平均線交叉）— 僅做多（long-only），無做空/槓桿/手續費
- **資料**：歷史 OHLCV K 線 → 信號 → 模擬交易 → 統計

### SMA 計算優化
- **舊版**：O(N·P) — 每個 bar 重新計算整個 window
- **新版**：O(N) sliding window — `window_sum += values[i] - values[i - period]`
- **加速**：N=1000, P=30 時約 **30x** 加速
- **實現**：`_sma_series()` 使用滑動窗口，首個 window 用 `sum(values[:period])` 初始化

### 交易模擬
- **Entry/Exit**：next bar's open（1-bar delay 簡化）
- **Position sizing**：`initial_balance * position_pct`（0-100%）
- **Force-close**：最後一根 bar 若仍持倉則強制平倉

### 統計指標
- **P&L**：total_pnl / total_pnl_pct / avg_pnl / avg_win / avg_loss
- **Win rate**：winning_trades / losing_trades / win_rate
- **Risk**：max_drawdown / max_drawdown_pct（equity curve 計算）
- **Sharpe ratio**：per-trade return，sample standard deviation
- **Single-pass**：所有統計在一次迴圈中完成（PnL + equity curve drawdown 同步計算）

### 模型（`backtest/models.py`）
- `BacktestConfig`：symbol / interval / initial_balance / start_time / end_time
- `BacktestResult`：完整結果（trades + stats + metadata）
- `Trade`：單筆交易（entry/exit price/time / pnl / bars_held）

---

## 14. Triggers / 事件系統（`triggers/`）

- `price_triggers.py`：價格異常觸發
- `risk_triggers.py`：風險超標觸發
- `trigger_registry.py`：註冊表
- `base_trigger.py`：抽象基類
- 事件 → `event_queue.py` → `_handle_trigger_event` → emergency handler

---

## 15. 配置系統

| 配置 | 位置 | 說明 |
|------|------|------|
| LLM 模型 | `backend/src/vibe_trading/config/llm.yaml` | use_llm + 多 config |
| 環境變數 | `.env`（gitignored） | API keys、LLM_MODEL、BINANCE_* |
| 系統設定 | `config/settings.py` | 讀 LLM_MODEL、debate_rounds、skip_debate 等 |
| Agent 設定 | `config/agent_config.py` | AgentRole / AgentConfig |
| Prompt | `config/prompts.py` | 各 agent system prompt |

**新增設定項（2026-08-09）**：
- `skip_debate: bool`：跳過 Phase 2 debate（env: `SKIP_DEBATE=true`）

⚠️ `.env` 與 `llm.yaml` 都 gitignored → 換機器要手動重建

---

## 16. 已知問題 / TODO

### ✅ 已修復（2026-08-05 ~ 08-09）
- [x] **Paper ledger 持久化**：`state_file` + `--reset-paper`，重啟自動還原（d140d36, 8abb462）
- [x] **PM 決策保險**：BUY/SELL 漏呼叫 tool 時 coordinator 自動執行（7853355）
- [x] **Debate timeout 防護**：45s timeout + 3 retries + skip_debate 選項（fc7f089）
- [x] **Backtest SMA 優化**：O(N·P) → O(N) sliding window（30033a5）
- [x] **Log rotation**：三層日誌輪替（c22e9c1）

### 🔧 待解決
- [ ] QualityTracker 0.90/0.30 交替原因（部分決策某 agent 被判 UNKNOWN）
- [ ] 工具參數格式（opencode.ai 回 `arguments={'type':...}`）— LLM 目前自癒重試
- [ ] 持倉數量對不上：8 筆 BUY = 0.01226 BTC vs snapshot 0.00156 BTC（0.0107 BTC 去向不明）
- [ ] bar_decision_journal 只在 web 模式寫入（by design）
- [ ] `_execute_trade` 是 placeholder（目前靠 executor 直接下單）
- [ ] `VBT_DEBUG_LLM` 是否該常駐（目前 production 也開著）

---

## 附錄：常用指令

```bash
# 啟動（paper mode）
vibe-trade start BTCUSDT --interval 30m --mode paper --web --web-port 8001

# 重啟（推薦用 script）
MODE=paper ./scripts/restart_vbt.sh

# 查進程
pgrep -f "vibe-trade start"

# 看決策 log
tail -f logs/trading_BTCUSDT_*.log
```
