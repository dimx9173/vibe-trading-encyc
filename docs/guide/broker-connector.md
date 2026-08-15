# Broker Connector 使用指南

## 概述

Broker Connector 是 Vibe Trading 的多交易所抽象層，支持 Binance 和 OKX 雙交易所路由。

### 核心組件

| 組件 | 文件 | 功能 |
|---|---|---|
| `BrokerConnector` | `broker_connector.py` | 抽象基類，定義統一接口 |
| `BrokerConfig` | `broker_connector.py` | 配置數據類 |
| `BrokerType` | `broker_connector.py` | 交易所類型枚舉 |
| `BrokerRouter` | `broker_connector.py` | 多 broker 路由器 |
| `OkxOrderExecutor` | `okx_executor.py` | OKX 訂單執行器 |
| `BinanceOrderExecutor` | `order_executor.py` | Binance 訂單執行器 |
| `PaperOrderExecutor` | `order_executor.py` | 模擬交易執行器 |

---

## 快速開始

### 1. 使用默認 Broker（Binance）

```python
from vibe_trading.execution.order_executor import create_executor, TradingMode

# 創建 Binance 實盤執行器
executor = create_executor(
    mode=TradingMode.LIVE,
    dry_run=False,  # True 為 dry-run 模式
)

# 下單
result = await executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=0.001,
    price=50000.0,
)
```

### 2. 使用 OKX 交易所

```python
from vibe_trading.execution.order_executor import create_executor, TradingMode

# 創建 OKX 實盤執行器
executor = create_executor(
    mode=TradingMode.OKX_LIVE,
    dry_run=False,
)

# 下單（接口與 Binance 相同）
result = await executor.place_order(
    symbol="BTC-USDT",  # OKX 使用 - 分隔
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=0.001,
    price=50000.0,
)
```

### 3. 使用 Broker Router（雙交易所路由）

```python
from vibe_trading.execution.broker_connector import BrokerRouter, BrokerType

# 創建路由器
router = BrokerRouter(default_broker=BrokerType.BINANCE)

# 註冊交易所
from vibe_trading.execution.order_executor import BinanceOrderExecutor
from vibe_trading.execution.okx_executor import OkxOrderExecutor
from vibe_trading.execution.broker_connector import BrokerConfig

binance_config = BrokerConfig(
    broker_type=BrokerType.BINANCE,
    api_key="your_binance_key",
    api_secret="your_binance_secret",
)
okx_config = BrokerConfig(
    broker_type=BrokerType.OKX,
    api_key="your_okx_key",
    api_secret="your_okx_secret",
    passphrase="your_okx_passphrase",
)

router.register_connector(BrokerType.BINANCE, BinanceOrderExecutor(binance_config))
router.register_connector(BrokerType.OKX, OkxOrderExecutor(okx_config))

# 路由到指定交易所
result = await router.place_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    quantity=0.001,
    price=50000.0,
    broker=BrokerType.OKX,  # 指定使用 OKX
)
```

---

## API 參考

### BrokerConnector 接口

所有交易所執行器必須實現以下接口：

```python
class BrokerConnector(ABC):
    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        position_side: Optional[PositionSide] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """下單"""
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消訂單"""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """獲取持倉"""
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, float]:
        """獲取餘額"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """關閉連接"""
        pass
```

### BrokerConfig 配置

```python
@dataclass
class BrokerConfig:
    broker_type: BrokerType  # BINANCE, OKX, PAPER
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None  # OKX 需要
    testnet: bool = False
    dry_run: bool = False
```

### TradingMode 枚舉

```python
class TradingMode(str, Enum):
    PAPER = "paper"           # 模擬交易
    TESTNET = "testnet"       # Binance 測試網
    LIVE = "live"             # Binance 實盤
    OKX_LIVE = "okx_live"     # OKX 實盤
    OKX_TESTNET = "okx_testnet"  # OKX 測試網
```

---

## 配置環境變量

### Binance

```bash
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
BINANCE_TESTNET_API_KEY=your_testnet_key
BINANCE_TESTNET_API_SECRET=your_testnet_secret
```

### OKX

```bash
OKX_API_KEY=your_api_key
OKX_API_SECRET=your_api_secret
OKX_PASSPHRASE=your_passphrase
```

---

## Dry-Run 模式

所有執行器都支持 dry-run 模式，只打印訂單不實際執行：

```python
# 方式 1：通過 create_executor
executor = create_executor(mode=TradingMode.LIVE, dry_run=True)

# 方式 2：通過 BrokerConfig
config = BrokerConfig(
    broker_type=BrokerType.OKX,
    api_key="...",
    api_secret="...",
    dry_run=True,
)
executor = OkxOrderExecutor(config)
```

Dry-run 模式會返回模擬的 `OrderResult`，訂單 ID 以 `dryrun_` 或 `okx_dryrun_` 開頭。

---

## 錯誤處理

```python
try:
    result = await executor.place_order(...)
    if result.status == "FILLED":
        print(f"訂單成交：{result.filled_price}")
    elif result.status == "REJECTED":
        print(f"訂單被拒絕")
    elif result.status == "ERROR":
        print(f"訂單錯誤")
except Exception as e:
    print(f"下單失敗：{e}")
```

---

## 最佳實踐

### 1. 使用環境變量管理憑證

```python
import os
from vibe_trading.execution.broker_connector import BrokerConfig, BrokerType

config = BrokerConfig(
    broker_type=BrokerType.OKX,
    api_key=os.getenv("OKX_API_KEY"),
    api_secret=os.getenv("OKX_API_SECRET"),
    passphrase=os.getenv("OKX_PASSPHRASE"),
)
```

### 2. 正確關閉連接

```python
executor = create_executor(mode=TradingMode.LIVE)
try:
    # 執行交易...
    pass
finally:
    await executor.close()
```

### 3. 使用 Broker Router 管理多交易所

```python
router = BrokerRouter(default_broker=BrokerType.BINANCE)

# 註冊所有交易所
router.register_connector(BrokerType.BINANCE, binance_executor)
router.register_connector(BrokerType.OKX, okx_executor)

# 使用默認交易所
result = await router.place_order(...)

# 使用指定交易所
result = await router.place_order(..., broker=BrokerType.OKX)

# 關閉所有連接
await router.close_all()
```

### 4. 檢查餘額和持倉

```python
# 獲取餘額
balance = await executor.get_balance()
print(f"USDT 餘額：{balance.get('USDT', 0)}")

# 獲取持倉
positions = await executor.get_positions()
for pos in positions:
    print(f"{pos.symbol}: {pos.quantity} @ {pos.entry_price}")
```

---

## 故障排除

### Q1: OKX 下單失敗 "Invalid API key"

**原因**：API 憑證配置錯誤

**解決方案**：
1. 檢查環境變量是否正確設置
2. 確認 OKX API key 有交易權限
3. 驗證 passphrase 是否正確

### Q2: 訂單被拒絕 "Insufficient balance"

**原因**：餘額不足

**解決方案**：
1. 使用 `get_balance()` 檢查可用餘額
2. 減少訂單數量
3. 充值到交易所

### Q3: Dry-run 模式訂單 ID 格式

**說明**：
- Binance dry-run: `dryrun_xxxxxxxxxx`
- OKX dry-run: `okx_dryrun_xxxxxxxxxx`

這些是模擬訂單 ID，不會在交易所實際存在。

### Q4: 如何切換測試網和實盤？

```python
# 測試網
executor = create_executor(mode=TradingMode.TESTNET)  # Binance
executor = create_executor(mode=TradingMode.OKX_TESTNET)  # OKX

# 實盤
executor = create_executor(mode=TradingMode.LIVE)  # Binance
executor = create_executor(mode=TradingMode.OKX_LIVE)  # OKX
```

---

## 性能優化

### 1. 重用執行器實例

```python
# 推薦：創建一次，多次使用
executor = create_executor(mode=TradingMode.LIVE)
for trade in trades:
    result = await executor.place_order(...)
await executor.close()

# 不推薦：每次下單都創建新實例
for trade in trades:
    executor = create_executor(mode=TradingMode.LIVE)
    result = await executor.place_order(...)
    await executor.close()
```

### 2. 批量查詢

```python
# 一次性獲取所有持倉
positions = await executor.get_positions()

# 一次性獲取所有餘額
balance = await executor.get_balance()
```

---

## 示例代碼

完整示例見 `tests/test_okx_executor.py` 和 `tests/test_broker_connector.py`。

---

## 更新日誌

### v1.0.0 (2026-08-12)

- ✅ 實現 BrokerConnector 抽象基類
- ✅ 實現 OkxOrderExecutor
- ✅ 實現 BrokerRouter 多交易所路由
- ✅ 擴展 TradingMode 支持 OKX
- ✅ 完整單元測試覆蓋（16 tests）
- ✅ Dry-run 模式支持
