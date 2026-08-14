# 外部數據層重構 — 任務清單（更新版）

## 專案資訊
- **專案**: VBT 外部數據層重構
- **版本**: 2.0.0（插件架構 + 證據門控）
- **開始日期**: 2026-08-14
- **預計完成**: 2026-08-28（14 天）
- **優先級**:  P0（高）
- **狀態**: 準備實施

---

## 架構變更摘要

### v1.0 → v2.0 變更

**移除**:
- ❌ 新聞/情緒作為核心功能
- ❌ 強制依賴外部 API

**新增**:
- ✅ 插件架構（可選啟用）
- ✅ 證據門控機制
- ✅ 回測/即時一致性保證
- ✅ Skill 系統整合

---

## Phase 1: 基礎架構（3 天）

### Day 1: 抽象接口與緩存

#### Task 1.1: 定義 UnifiedDataSource 抽象接口
- **檔案**: `backend/src/vibe_trading/data_sources/base.py`
- **工時**: 2 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] `UnifiedDataSource` ABC 定義完成
- [ ] `DataResult` Pydantic 模型定義完成
- [ ] `Kline` 和 `TechnicalIndicators` 模型定義完成
- [ ] 支援即時和回測兩種模式（start/end vs limit）
- [ ] 單元測試通過

---

#### Task 1.2: 實現 LRU Cache
- **檔案**: `backend/src/vibe_trading/data_sources/cache.py`
- **工時**: 3 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] LRU 淘汰機制工作正常
- [ ] TTL 過期機制工作正常
- [ ] 線程安全（asyncio 環境）
- [ ] 性能測試：get/set < 1ms
- [ ] 單元測試覆蓋率 > 90%

---

### Day 2: 熔斷器與健康監測

#### Task 1.3: 實現 Circuit Breaker
- **檔案**: `backend/src/vibe_trading/data_sources/circuit_breaker.py`
- **工時**: 3 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 三狀態狀態機（CLOSED/OPEN/HALF_OPEN）
- [ ] 失敗次數閾值可配置
- [ ] 恢復超時可配置
- [ ] 半開狀態測試邏輯正確
- [ ] 單元測試覆蓋所有狀態轉換

---

#### Task 1.4: 實現 Health Monitor
- **檔案**: `backend/src/vibe_trading/data_sources/health.py`
- **工時**: 2 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 記錄成功/失敗請求
- [ ] 計算成功率（EMA 算法）
- [ ] 計算平均響應時間
- [ ] 計算數據新鮮度
- [ ] 單元測試通過

---

### Day 3: 插件接口與智能路由

#### Task 1.5: 定義插件接口
- **檔案**: 
  - `backend/src/vibe_trading/data_sources/plugins/sentiment/base.py`
  - `backend/src/vibe_trading/data_sources/plugins/liquidation/base.py`
- **工時**: 3 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] `SentimentPlugin` ABC 定義完成
- [ ] `LiquidationPlugin` ABC 定義完成
- [ ] `NullSentiment` 空實現完成（回測用）
- [ ] `is_available` 屬性正確
- [ ] 單元測試通過

---

#### Task 1.6: 實現 Smart Router
- **檔案**: `backend/src/vibe_trading/data_sources/router.py`
- **工時**: 3 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 優先級計算正確（加權公式）
- [ ] 降級鏈工作正常
- [ ] 與 Circuit Breaker 整合
- [ ] 與 Health Monitor 整合
- [ ] 與 Cache 整合
- [ ] 集成測試通過

---

## Phase 2: K-line 與技術指標（3 天）

### Day 4-5: K-line 數據整合

#### Task 2.1: 實現 BinanceKlineWS
- **檔案**: `backend/src/vibe_trading/data_sources/kline/binance_ws.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] WebSocket 連接穩定
- [ ] 即時 K-line 推送正確
- [ ] 自動重連機制（指數退避）
- [ ] 心跳檢測（3 分鐘）
- [ ] 數據緩衝區管理（Deque, max 1000）
- [ ] 單元測試通過

---

#### Task 2.2: 實現歷史 K-line 數據庫
- **檔案**: `backend/src/vibe_trading/data_sources/kline/historical.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] SQLite 數據庫創建
- [ ] 即時數據自動同步到歷史
- [ ] 歷史數據查詢接口
- [ ] 數據完整性驗證
- [ ] 單元測試通過

---

### Day 6: 技術指標與 Alpha 因子

#### Task 2.3: 實現技術指標計算引擎
- **檔案**: `backend/src/vibe_trading/data_sources/indicators/technical.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 支援所有常用指標（RSI, MACD, Bollinger 等）
- [ ] 即時/回測共用相同邏輯
- [ ] 性能優化（<1ms）
- [ ] 單元測試通過

---

#### Task 2.4: 整合 Alpha 因子
- **檔案**: `backend/src/vibe_trading/data_sources/alphas/zoo.py`
- **工時**: 2 小時
- **優先級**: 🟡 P1

**驗收標準**:
- [ ] 23 個預設因子接入
- [ ] 因子計算優化
- [ ] 即時/回測共用
- [ ] 單元測試通過

---

#### Task 2.5: 實現 Skill 管理器
- **檔案**: `backend/src/vibe_trading/data_sources/skills/manager.py`
- **工時**: 2 小時
- **優先級**: 🟡 P1

**驗收標準**:
- [ ] Skill 存儲（SQLite）
- [ ] Skill 匹配邏輯
- [ ] Skill 學習機制
- [ ] 即時/回測共用
- [ ] 單元測試通過

---

## Phase 3: 可選插件（4 天）

### Day 7-8: 新聞/情緒插件

#### Task 3.1: 註冊 CryptoPanic API
- **負責**: 專案負責人
- **工時**: 30 分鐘
- **優先級**:  P0

**行動項目**:
- [ ] 訪問 https://cryptopanic.com/developers/api/
- [ ] 註冊帳號
- [ ] 獲取 API Key
- [ ] 添加到 `.env` 檔案：`CRYPTOPANIC_API_KEY=your_key`
- [ ] 測試 API 連通性

---

#### Task 3.2: 實現 CryptoPanicSentiment 插件
- **檔案**: `backend/src/vibe_trading/data_sources/plugins/sentiment/cryptopanic.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] API 認證正確
- [ ] 分頁處理正確（最大 10 頁）
- [ ] 情緒分析算法正確（投票比例）
- [ ] 數據標準化正確
- [ ] 錯誤處理完善
- [ ] 單元測試通過

---

#### Task 3.3: 實現 RSSSentiment 插件
- **檔案**: `backend/src/vibe_trading/data_sources/plugins/sentiment/rss.py`
- **工時**: 3 小時
- **優先級**: 🟡 P1

**驗收標準**:
- [ ] 支持多個 RSS 源
- [ ] 使用 feedparser 解析
- [ ] 數據標準化正確
- [ ] 錯誤處理完善（單源失敗不影響其他）
- [ ] 單元測試通過

**推薦 RSS 源**:
```python
FEED_URLS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://bitcoinmagazine.com/.rss/full/",
]
```

---

### Day 9-10: 清算數據插件

#### Task 3.4: 實現 BinanceLiquidationWS 插件
- **檔案**: `backend/src/vibe_trading/data_sources/plugins/liquidation/binance_ws.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] WebSocket 連接穩定
- [ ] 清算數據解析正確
- [ ] 自動重連機制
- [ ] 數據緩衝區管理
- [ ] 單元測試通過

---

#### Task 3.5: 實現多交易所聚合器
- **檔案**: `backend/src/vibe_trading/data_sources/plugins/liquidation/aggregator.py`
- **工時**: 3 小時
- **優先級**: 🟡 P1

**驗收標準**:
- [ ] 並行獲取多源數據
- [ ] 時間戳對齊正確（1 秒窗口）
- [ ] 加權聚合正確（交易量加權）
- [ ] 異常值過濾正確（中位數 ±10%）
- [ ] 單元測試通過

---

### Day 11: 決策增強器

#### Task 3.6: 實現 DecisionEnhancer
- **檔案**: `backend/src/vibe_trading/data_sources/decision_enhancer.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 裝飾器模式集成
- [ ] 新聞情緒增強邏輯
- [ ] 清算數據增強邏輯
- [ ] 插件不可用時降級
- [ ] 單元測試通過

---

## Phase 4: 證據門控與遷移（4 天）

### Day 12: 證據門控機制

#### Task 4.1: 實現 EvidenceGate
- **檔案**: `backend/src/vibe_trading/data_sources/evidence_gate.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 績效追蹤（Sharpe, Max DD, Win Rate）
- [ ] 14 天評估週期
- [ ] 半自動決策（系統建議 + 人工確認）
- [ ] SQLite 存儲
- [ ] 單元測試通過

---

#### Task 4.2: 實現績效追蹤器
- **檔案**: `backend/src/vibe_trading/data_sources/performance_tracker.py`
- **工時**: 2 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 每筆交易記錄
- [ ] 即時計算績效指標
- [ ] 數據持久化
- [ ] 查詢接口
- [ ] 單元測試通過

---

### Day 13: 回測適配與報告

#### Task 4.3: 實現回測引擎適配
- **檔案**: `backend/src/vibe_trading/data_sources/backtest_adapter.py`
- **工時**: 4 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 回測使用新數據層
- [ ] 硬編碼不調用新聞插件
- [ ] 回測/即時結果一致
- [ ] 單元測試通過

---

#### Task 4.4: 實現統一報告格式
- **檔案**: `backend/src/vibe_trading/data_sources/report_generator.py`
- **工時**: 2 小時
- **優先級**: 🟡 P1

**驗收標準**:
- [ ] 回測報告格式
- [ ] Paper 報告格式
- [ ] 標記數據源差異
- [ ] 對比報告生成
- [ ] 單元測試通過

---

### Day 14: 遷移與部署

#### Task 4.5: 遷移現有代碼
- **檔案**: 多個檔案
- **工時**: 4 小時
- **優先級**: 🔴 P0

**行動項目**:
- [ ] 更新 `trading_coordinator.py` 使用新架構
- [ ] 更新 `backtest/engine.py` 使用新數據層
- [ ] 更新配置文件格式
- [ ] 保留舊 API 兼容層
- [ ] 更新文檔

---

#### Task 4.6: 端到端測試
- **檔案**: `tests/test_e2e_data_layer.py`
- **工時**: 2 小時
- **優先級**: 🔴 P0

**驗收標準**:
- [ ] 完整決策流程測試
- [ ] 回測流程測試
- [ ] 插件開關測試
- [ ] 證據門控測試
- [ ] 性能測試通過

---

#### Task 4.7: 部署到生產環境
- **負責**: DevOps
- **工時**: 2 小時
- **優先級**: 🔴 P0

**行動項目**:
- [ ] 程式碼審查
- [ ] 生產環境配置
- [ ] API Key 配置
- [ ] 監控指標配置
- [ ] 告警規則配置

---

## 總工時估算

| Phase | 天數 | 工時 |
|---|---|---|
| Phase 1: 基礎架構 | 3 天 | 16 小時 |
| Phase 2: K-line 與技術指標 | 3 天 | 16 小時 |
| Phase 3: 可選插件 | 4 天 | 18 小時 |
| Phase 4: 證據門控與遷移 | 4 天 | 18 小時 |
| **總計** | **14 天** | **68 小時** |

---

## 依賴關係

```
Phase 1 (基礎架構)
    ↓
Phase 2 (K-line/指標) ──→ Phase 4 (證據門控)
    ↓                        ↑
Phase 3 (插件) ──────────────┘
```

---

## 風險登記

| ID | 風險 | 影響 | 可能性 | 緩解措施 | 負責人 |
|---|---|---|---|---|---|
| R1 | 插件接口變更 | 高 | 低 | 抽象接口 | RD |
| R2 | WebSocket 不穩定 | 中 | 中 | 自動重連 + REST 備源 | RD |
| R3 | 證據門控誤判 | 中 | 低 | 半自動決策 | PM |
| R4 | 回測/即時不一致 | 高 | 低 | 統一接口 + 嚴格測試 | QA |
| R5 | 工期延誤 | 高 | 中 | 分階段交付 | PM |

---

## 簽署

| 角色 | 姓名 | 日期 | 簽署 |
|---|---|---|---|
| 產品經理 | | | |
| 技術負責人 | | | |
| 開發工程師 | | | |
| QA 工程師 | | | |

---

**文件結束**
