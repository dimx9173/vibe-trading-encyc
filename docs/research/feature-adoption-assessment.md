# 競品功能採納評估 (2026-08-15 全面重審)

> **狀態**: 正式評估報告 — 基於對競品原始碼的深讀 (功能目錄, 非僅宣稱驗證)
> **評估對象**: HKUDS/Vibe-Trading (`~/project/vibe-trading-hkuds`) + AlphaGPT (`~/project/AlphaGPT`)
> **評估框架**: 每個功能 × (解決我們什麼弱點 / 實作成本 / 是否真能用)
> **前置**: 我們已實作 QuantLib (Phase 1.1) + Grounding Gate (Phase 1.2) + Agent Replay — 評估在此基礎上

---

## 一、真正值得採納 (Top 8)

按價值密度排序 (價值/成本):

| # | 功能 | 來源 | 解決我們什麼 | 成本 | 採納方式 |
|---|---|---|---|---|---|
| **A1** | **微觀結構因子包** (PRESSURE/FOMO/VOL_CLUSTER/MOMENTUM_REV/CLOSE_POS/VOL_TREND) | AlphaGPT | 技術分析師只用固定指標 (SMA/RSI/MACD), 缺訂單流/微觀訊號 — SWOT W2 | S | 6 個純 OHLCV 函數 (~40 行) + agent tool 註冊。**F3 PRESSURE 用我們真實 taker_buy_base 資料升級** (比 AlphaGPT 的蠟燭體代理更強) |
| **A2** | **StackVM 運算元引擎** (GATE/JUMP/DECAY/DELAY1/MAX3 + 算術) | AlphaGPT | 分析師無法組合自定義因子表達式 (固定指標硬編碼) | M | 純函式運算元 (arity-checked, NaN-safe), 作為「compose-factor」tool。**取 StackVM 本身, 不取 RL 循環** |
| **A3** | **加密永續回測保真度** (8h 資金費率結算 + OKX 分級維持保證金 + 標記價強平) | HKUDS | 我們 agent replay 的成交模擬無資金費率/強平 — 永續策略回測失真 | S | `crypto.py` 標準模式 ~150 行自包含移植; 嚴格模式 (逐交易所 bracket) 之後看 loader 能力 |
| **A4** | **動態標的宇宙** (trending→流動性/市值過濾管線) | AlphaGPT | 我們標的硬編碼 BTCUSDT/ETHUSDT, `get_trending_symbols` 是 stub | M | Binance 24h tickers 按 quote volume 排名 → 過濾穩定幣/槓桿代幣/市值區間 |
| **A5** | **退出管理階梯** (trailing stop + moonbag TP) | AlphaGPT | 我們只有固定 SL/TP, 無峰值回撤追蹤 | S | 狀態機: +5% 啟動 trailing, 峰值回撤 3% 全出; TP1 +10% 賣 50%。直接進 Binance executor config |
| **A6** | **Grounding 升級** (unsourced-symbol 檢查 + 0.5% 容差 + 有界唯讀恢復) | HKUDS | 我們的 Grounding Gate 只做價格帶檢查; 缺「數字未附來源標的」檢查與恢復循環 | M | 在現有 gate 上加: 無來源標的數字檢查 + `search→get_market_data` 有界恢復 (省 LLM 重試成本, 對應 SWOT W3) |
| **A7** | **RunManifest 方法論指紋** (prompt/tools/套件版本 hash, diff 偵測漂移) | HKUDS | agent replay 可重現性只是宣稱, 無證明; 無法偵測方法論漂移 | S | content-addressed hash: system prompt + skills + tools + pkg 版本; 兩次 run 相同組成 → 相同 hash。**比哈希鏈帳本有用 10 倍** |
| **A8** | **多標的張量因子篩選回測** (MemeBacktest pattern) | AlphaGPT | 我們 rule backtest 單標的 O(N); 因子 zoo 篩選無批量通道 | M | [tokens×time] 向量化: 一次跑完所有候選因子評分 (Binance taker fee + 深度衝擊), **在 Agent Replay 花 LLM 預算前預篩因子** |

## 二、次級可採納 (值得記入 backlog)

| 功能 | 來源 | 價值 | 註記 |
|---|---|---|---|
| portfolio_risk_xray (HHI/VaR/ES/多樣化比) | HKUDS | 給 PM agent 的持倉籃風險 X 光 | S, 直接可用 |
| 5 優化器 (risk_parity/turnover_aware) | HKUDS | 再平衡權重優化 | S, 獨立 |
| quantlib 進階 (GARCH/Markov regime/PBO/過擬合診斷/purged CV) | HKUDS | 我們 quantlib 已建基礎, 加這 5 模組補完 | M, 分批 |
| Swarm DAG preset 格式 | HKUDS | 把 13 agent 組成主題桌面 (資金費率桌/風控委員會) | M, 與我們辯論循環互補 |
| quantlib_call MCP 鏡像模式 | HKUDS | 我們 MCP server（2026-08-28 收斂計畫已物理刪除）原只鏡影 agent tools; 加 quantlib 計算 tool | S |
| financial_rigor_tool (Benford/十進制驗證) | HKUDS | 分析師數值謊言偵測 | S, 小 |

## 三、明確不採納 (誠實原因)

| 功能 | 來源 | 不採納原因 |
|---|---|---|
| AlphaEngine RL 因子挖掘循環 | AlphaGPT | 標籤用 `roll(open, -2)` 未來數據 (lookahead 污染, 違反我們 PIT replay 紀律); 獎勵無 IC/Sharpe; 架構綁定 LoopedTransformer |
| Honeypot 賣路檢查 | AlphaGPT | Solana rug 概念, Binance CEX 無意義 |
| LoRD/Newton-Schulz 正則化 | AlphaGPT | 訓練側, 對 LLM-agent 系統無益 |
| 哈希鏈審計帳本 | HKUDS | 單 operator 無外部審計方, 防篡改無動機 (已確認 LOW)。**RunManifest (A7) 是它的有用替代** |
| fixedincome/credit/fundmath/attribution/valuation | HKUDS | 債券/信用/私募/權益估值 — 非加密 |
| China 市場工具 (fund_flow/dragon_tiger/iwencai) | HKUDS | 權益市場專屬 |
| QVeris marketplace | HKUDS | 付費研究閘道, 非我們場景 |
| 13 券商連接器 | HKUDS | 我們定位垂直加密 (Binance), 非全資產 — SWOT W1 是策略選擇, 非缺陷 |

## 四、採納路線圖 (建議順序)

```
現在 (Phase 2 起點):   A1 微觀因子包 + A3 永續回測保真度
                        (都 S 成本, 直接改善現有分析師與回測)
接著:                 A2 StackVM 運算元 → A8 張量因子篩選
                        (構成 Phase 2: 因子工具庫 + 快速預篩)
並行:                 A7 RunManifest + A5 退出階梯 (S 成本小步快跑)
之後:                 A4 動態標的宇宙 + A6 Grounding 升級 (M)
backlog:              portfolio_risk_xray, 優化器, quantlib 進階, Swarm DAG
```

## 五、關鍵洞察

1. **AlphaGPT 的精華不是 RL, 是微觀因子 + StackVM** — 它的因子公式全公開、純函式、直接可用; RL 循環反而有 lookahead 污染不可複製。取其「工具」, 棄其「學習」。
2. **HKUDS 的精華是確定性層與治理模式** — Grounding 恢復循環、RunManifest 指紋、回測保真度公式。哈希鏈帳本被高估 (機構場景才需要), 但同模組的 RunManifest 對我們的可重現性宣稱是即時升級。
3. **我們已有基礎讓採納成本大幅下降**: quantlib 已建 (加模組即可), Grounding Gate 已建 (加檢查即可), agent tool 註冊模式已成熟, replay PIT 紀律可保護新因子不被污染。
4. **「真的有用」過濾原則**: 只採納 (a) 解決我們明確弱點、(b) 純函式/確定性、(c) 不違反 PIT 紀律、(d) 非權益市場專屬。不符合任一 → 不採納。

## 參考
- 功能目錄原始輸出: `agent://AlphaGPTFunctionInventory`, `agent://HKUDSFunctionInventory`
- 宣稱驗證: `docs/research/competitive-analysis.md` (核驗註記)
