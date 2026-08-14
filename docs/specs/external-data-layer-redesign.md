# 外部數據層重構規格書（更新版）

## 版本資訊
- **版本**: 2.0.0
- **日期**: 2026-08-14
- **狀態**: 已批准，準備實施
- **預估工期**: 14 天（4 個階段）
- **架構原則**: 核心技術指標 + 可選新聞插件 + 證據門控

---

## 1. 專案概述

### 1.1 問題陳述

當前 VBT 系統依賴的外部 API 存在以下問題：
1. **CryptoCompare News API** — 持續返回空數據（status=200 但無內容）
2. **Liquidation Orders API** — 返回空 response body
3. **無緩存機制** — 每次決策循環重複調用（每 30 分鐘 9 次）
4. **無降級策略** — API 故障時完全不可用
5. **單一數據源** — 無冗餘，故障風險高
6. **回測與即時不一致** — 回測無法使用新聞數據，導致策略驗證失效

### 1.2 解決方案

重構外部數據層，採用**核心 + 插件**架構：

**核心層**（回測/即時共用）：
- ✅ K-line 數據（WebSocket + REST）
- ✅ 技術指標計算
- ✅ Alpha 因子（23 個預設因子）
- ✅ Skill 系統（學習後的交易規則）

**可選插件層**（即時專用）：
- ✅ 新聞/情緒插件（CryptoPanic + RSS）
- ✅ 清算數據插件（Binance WebSocket + 多交易所）
- ✅ 智能路由（動態選擇最佳數據源）
- ✅ 統一緩存（LRU + TTL）
- ✅ 健康監測（熔斷器模式）

**證據門控**：
- ✅ Paper mode 14 天追蹤
- ✅ 績效評估（Sharpe > 0.8, Max DD < 20%）
- ✅ 半自動決策（系統建議 + 人工確認）

### 1.3 預期效益

| 指標 | 當前 | 目標 | 改善 |
|---|---|---|---|
| API 調用次數/天 | 432 次 | ~50 次 | -88% |
| 數據可用性 | ~60% | ~99% | +65% |
| 響應時間（P95） | 2-5s | <500ms | -80% |
| 故障恢復時間 | N/A | <60s | 新增 |
| 回測/即時一致性 | 60% | 100% | +67% |

---

## 2. 架構設計

### 2.1 系統架構圖

```
─────────────────────────────────────────────────────────────┐
│                    VBT 系統架構                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐         ┌──────────────────┐        │
│  │  即時交易系統     │         │   回測系統        │        │
│  │  (Live Trading)  │         │  (Backtest)       │        │
│  ├──────────────────┤         ├──────────────────┤        │
│  │ • TradingCoord   │         │ • BacktestEngine  │        │
│  │ • Analysts       │         │ • Alpha Zoo       │        │
│  │ • Risk Agents    │         │ • Shadow Account  │        │
│  │ • Decision Layer │         │ • Validation      │        │
│  ────────┬─────────┘         ────────┬─────────┘        │
│           │                            │                   │
│           ──────────┬─────────────────┘                   │
│                      ▼                                     │
│         ┌────────────────────────┐                        │
│         │    統一數據層           │                        │
│         ├────────────────────────┤                        │
│         │ 核心層（共用）         │                        │
│         │ • K-line 數據          │                        │
│         │ • 技術指標             │                        │
│         │ • Alpha 因子           │                        │
│         │ • Skill 系統           │                        │
│         ├────────────────────────┤                        │
│         │ 插件層（即時專用）     │                        │
│         │ • 新聞/情緒（可選）    │                        │
│         │ • 清算數據（可選）     │                        │
│         │ • 智能路由             │                        │
│         │ • 緩存系統             │                        │
│         │ • 熔斷器               │                        │
│         └────────────────────────┘                        │
│                                                             │
└─────────────────────────────────────────────────────────────
```

### 2.2 核心模組

```
backend/src/vibe_trading/data_sources/
├── base.py                 # 抽象接口定義
├── router.py               # 智能路由管理器
├── cache.py                # 統一緩存管理器
├── health.py               # 健康監測器
├── circuit_breaker.py      # 熔斷器實現
├── plugins/
│   ├── __init__.py
│   ├── sentiment/
│   │   ├── __init__.py
│   │   ├── base.py         # SentimentPlugin ABC
│   │   ├── cryptopanic.py  # CryptoPanic 實現
│   │   ├── rss.py          # RSS 聚合實現
│   │   └── null.py         # 空實現（回測用）
│   └── liquidation/
│       ├── __init__.py
│       ├── base.py         # LiquidationPlugin ABC
│       ├── binance_ws.py   # Binance WebSocket
│       └── aggregator.py   # 多交易所聚合
├── kline/
│   ├── __init__.py
│   ├── binance_ws.py       # K-line WebSocket
│   └── historical.py       # 歷史數據查詢
├── indicators/
│   ├── __init__.py
│   └── technical.py        # 技術指標計算引擎
├── alphas/
│   ├── __init__.py
│   └── zoo.py              # Alpha 因子整合
── skills/
    ├── __init__.py
    └── manager.py          # Skill 管理器
```

---

## 3. 技術規格

### 3.1 核心數據接口

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime

class DataResult(BaseModel):
    """統一數據結果"""
    source: str
    symbol: str
    data: Any
    timestamp: datetime
    freshness_score: float  # 0-1
    confidence: float       # 0-1

class UnifiedDataSource(ABC):
    """統一數據源（即時 + 回測）"""
    
    @abstractmethod
    async def get_klines(
        self, 
        symbol: str, 
        interval: str,
        start: Optional[datetime] = None,  # 回測用
        end: Optional[datetime] = None,     # 回測用
        limit: Optional[int] = None         # 即時用
    ) -> List[Kline]:
        """獲取 K-line 數據"""
        pass
    
    async def get_technical_indicators(
        self,
        symbol: str,
        interval: str,
        **kwargs
    ) -> Dict[str, float]:
        """計算技術指標（即時和回測共用）"""
        klines = await self.get_klines(symbol, interval, **kwargs)
        return TechnicalAnalyzer.calculate(klines)
    
    async def get_alpha_factors(
        self,
        symbol: str,
        interval: str,
        **kwargs
    ) -> Dict[str, float]:
        """計算 Alpha 因子（即時和回測共用）"""
        klines = await self.get_klines(symbol, interval, **kwargs)
        return AlphaZoo.calculate(klines)
```

### 3.2 插件接口（策略模式）

```python
class SentimentPlugin(ABC):
    """新聞情緒插件接口"""
    
    @abstractmethod
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        """
        返回情緒評分 -1.0 到 +1.0
        None 表示不可用
        """
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """插件是否可用"""
        pass
    
    @property
    def name(self) -> str:
        """插件名稱"""
        return self.__class__.__name__

class NullSentiment(SentimentPlugin):
    """空實現（回測/降級用）"""
    
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        return None
    
    @property
    def is_available(self) -> bool:
        return False

class CryptoPanicSentiment(SentimentPlugin):
    """CryptoPanic 實現"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._available = True
    
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        try:
            # 調用 CryptoPanic API
            ...
            return sentiment_score
        except Exception:
            self._available = False
            return None
    
    @property
    def is_available(self) -> bool:
        return self._available
```

### 3.3 裝飾器集成模式

```python
class DecisionEnhancer:
    """決策增強器（裝飾器模式）"""
    
    def __init__(
        self,
        sentiment_plugin: SentimentPlugin,
        liquidation_plugin: Optional[LiquidationPlugin] = None
    ):
        self.sentiment_plugin = sentiment_plugin
        self.liquidation_plugin = liquidation_plugin
    
    async def enhance(
        self,
        base_decision: str,
        symbol: str,
        technical_data: Dict
    ) -> str:
        """增強決策"""
        final_decision = base_decision
        
        # 新聞情緒增強
        if self.sentiment_plugin.is_available:
            sentiment = await self.sentiment_plugin.get_sentiment(symbol)
            if sentiment is not None:
                final_decision = self._apply_sentiment(
                    final_decision, sentiment
                )
        
        # 清算數據增強
        if self.liquidation_plugin and self.liquidation_plugin.is_available:
            liquidation_data = await self.liquidation_plugin.fetch(symbol)
            if liquidation_data:
                final_decision = self._apply_liquidation(
                    final_decision, liquidation_data
                )
        
        return final_decision
    
    def _apply_sentiment(self, decision: str, sentiment: float) -> str:
        """應用情緒增強"""
        # 邏輯：根據情緒評分調整決策信心
        ...
    
    def _apply_liquidation(self, decision: str, data: Dict) -> str:
        """應用清算數據增強"""
        # 邏輯：根據清算數據調整風險評估
        ...
```

### 3.4 回測引擎適配

```python
class BacktestEngine:
    """回測引擎（硬編碼不調用新聞插件）"""
    
    def __init__(
        self,
        data_source: UnifiedDataSource,
        skills: List[Skill]
    ):
        self.data_source = data_source
        self.skills = skills
        # 注意：不初始化任何插件
    
    async def run(self, symbol: str, start: datetime, end: datetime):
        """運行回測"""
        for bar in await self.data_source.get_klines(
            symbol, "30m", start, end
        ):
            # 技術指標計算
            indicators = await self.data_source.get_technical_indicators(
                symbol, "30m"
            )
            
            # Skill 匹配
            matched_skills = self._match_skills(indicators)
            
            # Agent 決策（不含新聞）
            decision = await self.agent.decide(
                indicators, matched_skills
            )
            
            # 記錄結果
            self._record_trade(bar, decision)
        
        return self._generate_report()
    
    def _generate_report(self) -> BacktestReport:
        """生成回測報告"""
        return BacktestReport(
            sharpe_ratio=self._calculate_sharpe(),
            win_rate=self._calculate_win_rate(),
            max_drawdown=self._calculate_max_dd(),
            data_sources=["歷史 K-line", "技術指標", "Alpha 因子", "Skills"],
            note="回測未使用新聞/情緒數據"
        )
```

### 3.5 證據門控機制

```python
class EvidenceGate:
    """證據門控"""
    
    def __init__(self, config: EvidenceGateConfig):
        self.config = config
        self.db = SQLiteConnection()
    
    async def evaluate_paper_performance(
        self,
        period_days: int = 14
    ) -> EvidenceGateResult:
        """評估 Paper 績效"""
        # 查詢最近 14 天績效
        performance = await self.db.query_performance(
            days=period_days
        )
        
        # 計算指標
        sharpe = self._calculate_sharpe(performance.trades)
        max_dd = self._calculate_max_drawdown(performance.equity_curve)
        
        # 評估是否達標
        passed = (
            sharpe >= self.config.min_sharpe and
            max_dd <= self.config.max_drawdown
        )
        
        # 生成建議
        recommendation = self._generate_recommendation(
            passed, sharpe, max_dd
        )
        
        return EvidenceGateResult(
            passed=passed,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            recommendation=recommendation
        )
    
    def _generate_recommendation(
        self,
        passed: bool,
        sharpe: float,
        max_dd: float
    ) -> str:
        """生成建議"""
        if passed:
            return (
                f"Paper 績效良好（Sharpe: {sharpe:.2f}, "
                f"Max DD: {max_dd:.2%}）。"
                f"建議切換到 Live mode。"
            )
        else:
            return (
                f"Paper 績效未達標（Sharpe: {sharpe:.2f} < {self.config.min_sharpe}, "
                f"Max DD: {max_dd:.2%} > {self.config.max_drawdown}）。"
                f"建議繼續 Paper mode 或調整策略。"
            )
```

### 3.6 配置結構

```yaml
# config/trading.yaml
trading:
  mode: paper  # paper | live
  
  data_sources:
    kline:
      source: binance
      interval: 30m
    
    technical_indicators:
      enabled: true
      indicators: [rsi, macd, bollinger, ...]
    
    alpha_factors:
      enabled: true
      factors: [momentum_12_1, volatility, ...]
    
    # 可選插件
    sentiment:
      enabled: false  # 全局開關
      plugin: cryptopanic
      api_key: ${CRYPTOPANIC_API_KEY}
    
    liquidation:
      enabled: true
      sources: [binance_ws]
    
    # Per-symbol 覆蓋
    overrides:
      BTCUSDT:
        sentiment.enabled: true
      ETHUSDT:
        sentiment.enabled: false
  
  evidence_gate:
    enabled: true
    evaluation_period_days: 14
    metrics:
      min_sharpe: 0.8
      max_drawdown: 0.20
    auto_switch: false  # 半自動模式
    storage: sqlite
  
  skills:
    enabled: true
    storage: ./data/skills.db
    max_skills: 100
```

---

## 4. 實施計劃

### Phase 1: 基礎架構（3 天）

**目標**: 建立核心抽象層和基礎設施

**任務**:
1. ✅ 定義 `UnifiedDataSource` 抽象接口
2. ✅ 實現 `LRUCache` 緩存管理器
3. ✅ 實現 `CircuitBreaker` 熔斷器
4. ✅ 實現 `HealthMonitor` 健康監測器
5. ✅ 實現 `SmartRouter` 智能路由器
6. ✅ 定義插件接口（`SentimentPlugin`, `LiquidationPlugin`）
7. ✅ 實現 `NullSentiment` 空實現
8. ✅ 編寫單元測試（覆蓋率 >80%）

**交付物**:
- `base.py` — 抽象接口
- `cache.py` — 緩存實現
- `circuit_breaker.py` — 熔斷器
- `health.py` — 健康監測
- `router.py` — 智能路由
- `plugins/sentiment/base.py` — 插件接口
- `plugins/sentiment/null.py` — 空實現
- `tests/test_data_sources.py` — 測試

---

### Phase 2: K-line 與技術指標（3 天）

**目標**: 整合 K-line 數據和技術指標

**任務**:
1. ✅ 實現 `BinanceKlineWS` WebSocket 客戶端
2. ✅ 實現歷史 K-line 數據庫（SQLite）
3. ✅ 實現數據同步（即時 → 歷史）
4. ✅ 實現技術指標計算引擎
5. ✅ 整合 Alpha 因子（23 個預設因子）
6. ✅ 實現 Skill 管理器
7. ✅ 編寫集成測試

**交付物**:
- `kline/binance_ws.py`
- `kline/historical.py`
- `indicators/technical.py`
- `alphas/zoo.py`
- `skills/manager.py`
- `tests/test_kline_indicators.py`

---

### Phase 3: 可選插件（4 天）

**目標**: 整合新聞/情緒和清算數據插件

**任務**:
1. ✅ 註冊 CryptoPanic API Key
2. ✅ 實現 `CryptoPanicSentiment` 插件
3. ✅ 實現 `RSSSentiment` 插件
4. ✅ 實現 `BinanceLiquidationWS` 插件
5. ✅ 實現多交易所聚合器
6. ✅ 實現 `DecisionEnhancer` 裝飾器
7. ✅ 編寫插件測試

**交付物**:
- `plugins/sentiment/cryptopanic.py`
- `plugins/sentiment/rss.py`
- `plugins/liquidation/binance_ws.py`
- `plugins/liquidation/aggregator.py`
- `decision_enhancer.py`
- `tests/test_plugins.py`

---

### Phase 4: 證據門控與遷移（4 天）

**目標**: 實現證據門控和系統遷移

**任務**:
1. ✅ 實現 `EvidenceGate` 證據門控
2. ✅ 實現績效追蹤（SQLite）
3. ✅ 實現回測引擎適配
4. ✅ 實現統一報告格式
5. ✅ 遷移現有代碼到新架構
6. ✅ 編寫端到端測試
7. ✅ 更新文檔
8. ✅ 部署到生產環境

**交付物**:
- `evidence_gate.py`
- `performance_tracker.py`
- `backtest_adapter.py`
- `tests/test_evidence_gate.py`
- `docs/external-data-layer.md`
- 遷移指南

---

## 5. 遷移路徑

```
Week 1-2: 部署新外部數據層（核心層）
    ↓
Week 3:   回測系統切換到新數據層
    ↓
Week 4:   部署可選插件（新聞/清算）
    ↓
Week 5-6: Paper mode 開啟證據門控（14 天追蹤）
    ↓
Week 7:   評估績效，決定 Live 配置
```

---

## 6. 驗收標準

### 6.1 功能驗收

- [ ] 核心數據層工作正常（K-line + 技術指標 + Alpha 因子）
- [ ] 回測系統使用新數據層，結果一致
- [ ] 新聞插件可選啟用/禁用
- [ ] 清算插件可選啟用/禁用
- [ ] 證據門控追蹤 Paper 績效
- [ ] 14 天後生成評估報告
- [ ] 配置開關生效（重啟後）

### 6.2 性能驗收

- [ ] 單一 API 調用 < 500ms (P95)
- [ ] 智能路由決策 < 10ms
- [ ] 緩存命中 < 1ms
- [ ] 多源聚合 < 1s (3 個源)

### 6.3 一致性驗收

- [ ] 回測和即時使用相同技術指標邏輯
- [ ] 回測和即時使用相同 Alpha 因子邏輯
- [ ] 回測和即時使用相同 Skill 匹配邏輯
- [ ] 回測報告標記「未使用新聞」

---

## 7. 風險與緩解

### 7.1 技術風險

| 風險 | 影響 | 可能性 | 緩解措施 |
|---|---|---|---|
| 插件接口變更 | 高 | 低 | 抽象接口，易於替換 |
| WebSocket 不穩定 | 中 | 中 | 自動重連 + REST 備源 |
| 證據門控誤判 | 中 | 低 | 半自動決策，人工確認 |
| 回測/即時不一致 | 高 | 低 | 統一數據接口，嚴格測試 |

### 7.2 專案風險

| 風險 | 影響 | 可能性 | 緩解措施 |
|---|---|---|---|
| 工期延誤 | 高 | 中 | 分階段交付，優先核心功能 |
| 需求變更 | 中 | 中 | 模組化設計，易於擴展 |
| 第三方 API 限制 | 高 | 低 | 多源冗餘，降級策略 |

---

## 8. 附錄

### 8.1 API 註冊連結

- **CryptoPanic**: https://cryptopanic.com/developers/api/
- **Coinglass**: https://www.coinglass.com/pro/api

### 8.2 參考文檔

- [Binance WebSocket API](https://binance-docs.github.io/apidocs/futures/en/)
- [CryptoPanic API Docs](https://cryptopanic.com/developers/api/)
- [Python websockets](https://websockets.readthedocs.io/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

---

**文件結束**
