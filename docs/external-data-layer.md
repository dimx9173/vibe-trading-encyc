# 外部數據層使用指南

## 概述

VBT 外部數據層採用**核心 + 插件**架構：

- **核心層**：K-line、技術指標、Alpha 因子、Skills（回測/即時共用）
- **插件層**：新聞情緒、清算數據（可選，即時專用）
- **智能路由**：動態選擇最佳數據源
- **證據門控**：Paper 14 天驗證 → Live 配置決策

---

## 快速開始

### 1. 基本使用

```python
from vibe_trading.data_sources import SmartRouter, LRUCache, CircuitBreaker, HealthMonitor

# 創建組件
cache = LRUCache(max_size=1000)
circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
health_monitor = HealthMonitor(ema_alpha=0.1)

# 創建路由器
router = SmartRouter(
    sources=[your_data_source],
    cache=cache,
    circuit_breaker=circuit_breaker,
    health_monitor=health_monitor
)

# 獲取數據
result = await router.route("BTCUSDT", "indicators")
print(result.data)
```

### 2. 使用插件

```python
from vibe_trading.data_sources.plugins.sentiment.cryptopanic import CryptoPanicSentiment
from vibe_trading.data_sources.plugins.sentiment.null import NullSentiment

# 即時模式：使用真實插件
sentiment_plugin = CryptoPanicSentiment(api_key="your_key")

# 回測模式：使用空插件
sentiment_plugin = NullSentiment()

# 獲取情緒數據
sentiment = await sentiment_plugin.get_sentiment("BTCUSDT")
if sentiment is not None:
    print(f"Sentiment: {sentiment}")
```

---

## 核心模組

### LRUCache

LRU 緩存 + TTL 過期機制。

```python
cache = LRUCache(max_size=1000)

# 設置緩存（不同數據類型有不同 TTL）
cache.set("BTCUSDT:indicators", {"rsi": 65.5}, "indicators")  # 5 分鐘 TTL
cache.set("BTCUSDT:kline", [...], "kline")                    # 1 分鐘 TTL

# 獲取緩存
data = cache.get("BTCUSDT:indicators", "indicators")

# 統計
stats = cache.stats()  # {"size": 10, "max_size": 1000}
```

**TTL 配置**：
- `kline`: 1 分鐘
- `indicators`: 5 分鐘
- `alpha_factors`: 10 分鐘
- `sentiment`: 5 分鐘
- `liquidation`: 10 分鐘

---

### CircuitBreaker

熔斷器模式，防止級聯故障。

```python
cb = CircuitBreaker(
    failure_threshold=5,      # 失敗 5 次後熔斷
    recovery_timeout=60,      # 60 秒後嘗試恢復
    half_open_max_calls=1     # 半開狀態允許 1 次測試調用
)

# 檢查是否可用
if cb.is_available("binance"):
    data = await fetch_data()
    cb.record_success("binance")
else:
    # 使用降級方案
    data = await fetch_from_backup()

# 記錄失敗
cb.record_failure("binance")

# 獲取狀態
state = cb.get_state("binance")  # CLOSED / OPEN / HALF_OPEN
```

**狀態轉換**：
```
CLOSED → (失敗 N 次) → OPEN → (等待 T 秒) → HALF_OPEN → (成功) → CLOSED
                                                          → (失敗) → OPEN
```

---

### HealthMonitor

健康監測，使用 EMA 算法平滑指標。

```python
hm = HealthMonitor(ema_alpha=0.1)

# 記錄請求
hm.record_success("binance", latency_ms=150.0)
hm.record_failure("binance")

# 獲取指標
success_rate = hm.get_success_rate("binance")      # 0-1
latency_score = hm.get_latency_score("binance")    # 0-1 (越低越好)
freshness = hm.get_freshness("binance")            # 0-1
request_count = hm.get_request_count("binance")    # int

# 獲取所有統計
stats = hm.get_stats("binance")
```

**EMA 算法**：
```
new_value = old_value * (1 - alpha) + new_sample * alpha
```

---

### SmartRouter

智能路由，根據健康指標動態選擇最佳數據源。

```python
router = SmartRouter(
    sources=[source1, source2, source3],
    cache=cache,
    circuit_breaker=circuit_breaker,
    health_monitor=health_monitor,
    weights={
        "freshness": 0.30,
        "latency": 0.25,
        "success_rate": 0.25,
        "completeness": 0.20,
    }
)

# 路由請求
result = await router.route("BTCUSDT", "indicators")

# 獲取所有源的統計
stats = router.get_source_stats()
```

**優先級計算**：
```
priority = freshness * 0.30 + latency * 0.25 + success_rate * 0.25 + completeness * 0.20
```

---

## 插件系統

### SentimentPlugin

新聞情緒插件接口。

```python
class SentimentPlugin(ABC):
    @abstractmethod
    async def get_sentiment(self, symbol: str) -> Optional[float]:
        """返回 -1.0 到 +1.0，None 表示不可用"""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """插件是否可用"""
        pass
```

**可用實現**：
- `CryptoPanicSentiment` - CryptoPanic API
- `RSSSentiment` - RSS 聚合
- `NullSentiment` - 空實現（回測用）

---

### LiquidationPlugin

清算數據插件接口。

```python
class LiquidationPlugin(ABC):
    @abstractmethod
    async def fetch(self, symbol: str, **kwargs) -> Optional[List[LiquidationData]]:
        """獲取清算數據"""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """插件是否可用"""
        pass
```

**可用實現**：
- `BinanceLiquidationWS` - Binance WebSocket 即時推送
- `MultiExchangeAggregator` - 多交易所聚合

---

## 配置

### YAML 配置

```yaml
# config/trading.yaml
trading:
  mode: paper
  
  data_sources:
    kline:
      source: binance
      interval: 30m
    
    technical_indicators:
      enabled: true
      indicators: [rsi, macd, bollinger]
    
    alpha_factors:
      enabled: true
      factors: [momentum_12_1, volatility]
    
    sentiment:
      enabled: false  # 全局開關
      plugin: cryptopanic
      api_key: ${CRYPTOPANIC_API_KEY}
    
    liquidation:
      enabled: true
      sources: [binance_ws]
    
    overrides:
      BTCUSDT:
        sentiment.enabled: true  # per-symbol 覆蓋

  evidence_gate:
    enabled: true
    evaluation_period_days: 14
    metrics:
      min_sharpe: 0.8
      max_drawdown: 0.20
    auto_switch: false  # 半自動模式
```

### 環境變量

```bash
# .env
CRYPTOPANIC_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 證據門控

### 工作流程

```
回測（歷史數據 + 指標 + Skills）
    │
    ▼ 驗證通過
    │
Paper Mode（可開關新聞）
    │
    ├── 2 週 with news OFF 績效良好 → Live with news OFF
    └── 2 週 with news ON  績效良好 → Live with news ON
```

### 績效指標

- **Sharpe Ratio** > 0.8
- **Max Drawdown** < 20%
- **Win Rate** > 55%（參考）
- **Profit Factor** > 1.5（參考）

### 使用示例

```python
from vibe_trading.data_sources.evidence_gate import EvidenceGate

gate = EvidenceGate(config)

# 評估 Paper 績效
result = await gate.evaluate_paper_performance(period_days=14)

if result.passed:
    print(f"建議切換到 Live mode")
    print(f"Sharpe: {result.sharpe_ratio:.2f}")
    print(f"Max DD: {result.max_drawdown:.2%}")
else:
    print(f"建議繼續 Paper mode")
    print(result.recommendation)
```

---

## 回測整合

### 回測引擎適配

```python
from vibe_trading.data_sources.backtest_adapter import BacktestAdapter

adapter = BacktestAdapter(
    data_source=unified_data_source,
    skills=skill_list
)

# 運行回測（硬編碼不調用新聞插件）
report = await adapter.run(
    symbol="BTCUSDT",
    start=datetime(2026, 1, 1),
    end=datetime(2026, 8, 1)
)

print(f"Sharpe: {report.sharpe_ratio:.2f}")
print(f"Win Rate: {report.win_rate:.2%}")
print(f"Data Sources: {report.data_sources}")
# 輸出：["歷史 K-line", "技術指標", "Alpha 因子", "Skills"]
```

### 統一報告格式

```python
{
    "sharpe_ratio": 1.2,
    "win_rate": 0.58,
    "max_drawdown": 0.12,
    "total_return": 0.15,
    "data_sources": ["歷史 K-line", "技術指標", "Alpha 因子", "Skills"],
    "note": "回測未使用新聞/情緒數據"
}
```

---

## 遷移指南

### 從舊系統遷移

```python
# 舊代碼
from vibe_trading.tools import sentiment_tools

news = await sentiment_tools.get_news_sentiment("BTCUSDT")

# 新代碼
from vibe_trading.data_sources.plugins.sentiment.cryptopanic import CryptoPanicSentiment

plugin = CryptoPanicSentiment(api_key="your_key")
sentiment = await plugin.get_sentiment("BTCUSDT")
```

### 配置遷移

```bash
# 1. 備份舊配置
cp config/trading.yaml config/trading.yaml.backup

# 2. 更新配置格式
# 參考上面的 YAML 配置示例

# 3. 測試新配置
python -m vibe_trading.cli start BTCUSDT --mode paper

# 4. 驗證功能
python -m vibe_trading.cli status
```

---

## 故障排除

### 問題：API 返回空數據

**原因**：API Key 無效或配額耗盡

**解決方案**：
1. 檢查 API Key 是否正確
2. 驗證 API 配額是否充足
3. 使用降級插件（如 NullSentiment）

### 問題：WebSocket 連接不穩定

**原因**：網路問題或 Binance 限流

**解決方案**：
1. 檢查網路連接
2. 驗證 IP 是否被限流
3. 使用 REST API 備源

### 問題：緩存未命中

**原因**：TTL 過期或 LRU 淘汰

**解決方案**：
1. 增加 TTL 時間
2. 增加緩存大小
3. 檢查數據類型是否正確

---

## 性能基準

| 操作 | 目標 | 實際 |
|---|---|---|
| 單一 API 調用 | < 500ms | ~200ms |
| 智能路由決策 | < 10ms | ~5ms |
| 緩存命中 | < 1ms | ~0.5ms |
| 多源聚合 | < 1s | ~500ms |

---

## 監控指標

### Prometheus 指標

```python
# API 調用次數
vbt_api_calls_total{source, data_type, status}

# API 響應時間
vbt_api_response_time_seconds{source, data_type}

# 緩存命中率
vbt_cache_hit_ratio{data_type}

# 熔斷器狀態
vbt_circuit_breaker_state{source}  # 0=closed, 1=open, 2=half_open
```

### 日誌格式

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "data_fetched",
    source="cryptopanic",
    symbol="BTCUSDT",
    data_type="sentiment",
    latency_ms=245,
    cache_hit=False
)
```

---

## 最佳實踐

### 1. 使用緩存

```python
# ✅ 正確：使用緩存
result = await router.route("BTCUSDT", "indicators")

#  錯誤：直接調用 API
result = await api.fetch("BTCUSDT")
```

### 2. 處理插件不可用

```python
# ✅ 正確：檢查可用性
if plugin.is_available:
    sentiment = await plugin.get_sentiment(symbol)
else:
    sentiment = None  # 使用默認值

# ❌ 錯誤：不檢查可用性
sentiment = await plugin.get_sentiment(symbol)  # 可能拋出異常
```

### 3. 配置證據門控

```python
# ✅ 正確：使用證據門控
gate = EvidenceGate(config)
result = await gate.evaluate_paper_performance()

# ❌ 錯誤：直接切換到 Live
# 沒有經過 Paper 驗證
```

---

## 參考資源

- [規格書](specs/external-data-layer-redesign.md)
- [任務清單](tasks/external-data-layer-tasks.md)
- [API 文檔](../backend/src/vibe_trading/data_sources/)
- [測試用例](../tests/test_data_sources.py)

---

**文件版本**: 1.0.0  
**最後更新**: 2026-08-14

---

## P3 研究脊梁模組

### P3.1 Hypothesis Registry

假設管理和驗證系統，支持完整的生命週期管理。

```python
from vibe_trading.research.registry import HypothesisRegistry

registry = HypothesisRegistry()

# 創建假設
hypothesis = await registry.create(
    title="BTC 動量策略",
    description="基於 RSI 和 MACD 的比特幣動量交易策略",
    tags=["btc", "momentum", "rsi"]
)

# 生命週期管理
await registry.activate(hypothesis.id)
await registry.start_testing(hypothesis.id)
await registry.validate(hypothesis.id, evidence={"sharpe": 1.5})
```

**功能**：
- ✅ 創建/更新/搜索/驗證/作廢假設
- ✅ 連結回測結果和實盤結果
- ✅ 證據追蹤和日誌記錄
- ✅ SQLite 數據庫持久化

---

### P3.2 Memory Upgrade

FTS5 全文搜索和上下文壓縮。

```python
from vibe_trading.research.database import ResearchDatabase

db = ResearchDatabase("research.db")

# FTS5 全文搜索
results = await db.search_hypotheses("比特幣動量策略 RSI MACD")
```

**功能**：
- ✅ FTS5 全文搜索後端
- ✅ 5 層上下文壓縮
- ✅ Skill CRUD 自進化

---

### P3.3 Strategy Export

策略導出到 Pine Script 和 MQL5。

```python
from vibe_trading.exporters.strategy_exporter import PineScriptExporter, MQL5Exporter

# 導出到 Pine Script
pine_exporter = PineScriptExporter()
pine_code = pine_exporter.export(trading_plan)

# 導出到 MQL5
mql5_exporter = MQL5Exporter()
mql5_code = mql5_exporter.export(trading_plan)
```

**功能**：
- ✅ Pine Script 導出器（TradingView）
- ✅ MQL5 導出器（MetaTrader 5）
- ✅ 策略模板系統（4 個預設模板）

**預設模板**：
1. **Trend Following** - 趨勢跟隨策略
2. **Mean Reversion** - 均值回歸策略
3. **Breakout** - 突破策略
4. **Momentum** - 動能策略

---

### P3.4 Swarm Presets

管道編排預設系統。

```python
from vibe_trading.coordinator.presets.config import get_preset_manager

manager = get_preset_manager()

# 獲取預設
presets = manager.get_all_presets()

# 獲取特定預設
investment_preset = manager.get_preset("investment_committee")
risk_preset = manager.get_preset("risk_committee")
quant_preset = manager.get_preset("quant_strategy_desk")
```

**功能**：
- ✅ YAML 預設配置
- ✅ 管道編排預設
- ✅ Investment Committee 預設
- ✅ Risk Committee 預設
- ✅ Quant Strategy Desk 預設

---

## 完整模組列表

### 核心模組
- `base.py` - UnifiedDataSource 抽象接口
- `cache.py` - LRU Cache + TTL
- `circuit_breaker.py` - 熔斷器
- `health.py` - 健康監測
- `router.py` - 智能路由

### K-line 與技術指標
- `kline/binance_ws.py` - Binance WebSocket
- `kline/historical.py` - 歷史數據庫
- `indicators/technical.py` - 技術指標引擎
- `alphas/zoo.py` - 23 個 Alpha 因子
- `skills/manager.py` - Skill 管理器

### 插件系統
- `plugins/sentiment/` - 新聞情緒插件
- `plugins/liquidation/` - 清算數據插件

### 研究脊梁 (P3)
- `research/models.py` - 數據模型
- `research/database.py` - 數據庫
- `research/registry.py` - 假設註冊表
- `research/goal_manager.py` - 目標管理器
- `exporters/strategy_exporter.py` - 策略導出器
- `exporters/templates.py` - 策略模板
- `coordinator/presets/config.py` - 預設配置

---

## 測試覆蓋

### 單元測試
- `tests/test_data_sources.py` - 26 個測試
- `tests/test_research.py` - 21 個測試
- `tests/test_strategy_exporter.py` - 16 個測試
- `tests/test_swarm_presets.py` - 11 個測試

**總計**: 74 個測試，全部通過 ✅

---

## 性能指標

| 操作 | 目標 | 實際 |
|---|---|---|
| 單一 API 調用 | < 500ms | ~200ms |
| 智能路由決策 | < 10ms | ~5ms |
| 緩存命中 | < 1ms | ~0.5ms |
| 多源聚合 | < 1s | ~500ms |
| FTS5 搜索 | < 100ms | ~50ms |
| 假設創建 | < 50ms | ~20ms |

---

## 故障排除

### 問題：API 返回空數據
**原因**: API Key 無效或配額耗盡
**解決方案**: 檢查 API Key，驗證配額

### 問題：假設創建失敗
**原因**: 數據庫連接問題
**解決方案**: 檢查數據庫文件，重新初始化

### 問題：導出代碼為空
**原因**: 交易計劃格式不正確
**解決方案**: 驗證交易計劃格式

---

**文件版本**: 2.0.0  
**最後更新**: 2026-08-14  
**包含模組**: P2.1 Alpha Zoo + P3 Research Spine
