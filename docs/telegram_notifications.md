# Telegram 通知系統使用指南

## 概述

VBT Telegram 通知系統提供三級優先級通知推送，支持指數退避重試、inline keyboard 確認機制。

### 核心功能

| 功能 | 說明 |
|---|---|
| **三級優先級** | CRITICAL（立即+重複）、HIGH（立即）、LOW（批量） |
| **指數退避** | CRITICAL: 1→2→4→8→16 分鐘，HIGH: 5→10→20→40→80 分鐘 |
| **Inline Keyboard** | CRITICAL 通知附帶「✅ 已確認」和「📋 查看詳情」按鈕 |
| **內存隊列** | 通知隊列存於內存，系統重啟後清除 |
| **異步推送** | 基於 python-telegram-bot v20+ 的異步架構 |

---

## 快速開始

### 1. 安裝依賴

```bash
cd /home/brian/project/vibe-trading
source .venv/bin/activate
uv pip install python-telegram-bot>=20.7
```

### 2. 配置環境變量

在 `.env` 文件中添加：

```env
# Telegram Notification
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_ENABLED=true
```

### 3. 獲取 Bot Token

1. 在 Telegram 中搜索 `@BotFather`
2. 發送 `/newbot` 命令
3. 按照提示創建 bot，獲取 token
4. 將 token 填入 `TELEGRAM_BOT_TOKEN`

### 4. 獲取 Chat ID

1. 在 Telegram 中搜索你的 bot，發送任意消息
2. 訪問 `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. 在返回的 JSON 中找到 `chat.id`
4. 將 chat.id 填入 `TELEGRAM_CHAT_ID`

### 5. 啟動系統

```bash
cd /home/brian/project/vibe-trading
source .venv/bin/activate
PYTHONPATH=backend/src python -m vibe_trading.cli start BTCUSDT --mode paper
```

系統會自動初始化 Telegram Notifier（如果配置了有效的 token 和 chat_id）。

---

## 通知優先級

### CRITICAL（緊急）

**場景**：
- 止損觸發
- 緊急模式啟動
- API 連接失敗

**推送策略**：
- 立即推送
- 附帶 inline keyboard（「✅ 已確認」按鈕）
- 指數退避重複提醒：1→2→4→8→16 分鐘
- 最多重試 5 次，直到用戶確認

### HIGH（高優先級）

**場景**：
- 交易決策完成（買入/賣出）
- 止盈觸發
- 價格劇烈波動（>5%）

**推送策略**：
- 立即推送
- 不重複提醒

### LOW（低優先級）

**場景**：
- 每日交易摘要
- 因子更新
- 系統狀態報告

**推送策略**：
- 每 5 分鐘批量推送一次
- 不重複提醒

---

## 消息格式示例

### 交易決策通知

```
 交易決策: BUY BTCUSDT

操作: BUY
價格: 50,000.00
數量: 0.001000
原因: Strong bullish signal
預期 PnL: 📈 +2.50%

時間: 14:30:25
```

### 止損觸發通知

```
🚨 止損觸發: BTCUSDT

入場價: 50,000.00
出場價: 48,000.00
數量: 0.001000
PnL: 📉 -4.00%

⚠️ 請確認是否調整策略

[✅ 已確認] [📋 查看詳情]
```

### 每日摘要通知

```
📊 每日交易摘要 (2026-08-12)

總交易次數: 10
盈利: 7 | 虧損: 3
勝率: 70.0%
總 PnL: +5.50%

當前持倉:
• BTCUSDT: 0.001000 @ 50,000.00
```

---

## 配置選項

### 環境變量

| 變量 | 說明 | 默認值 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot Token（必填） | - |
| `TELEGRAM_CHAT_ID` | Chat ID（必填） | - |
| `TELEGRAM_ENABLED` | 是否啟用 | `true` |

### 代碼配置

```python
from vibe_trading.notifications import NotificationConfig

# 從環境變量加載配置
config = NotificationConfig.from_env()

# 手動配置
config = NotificationConfig(
    telegram=TelegramConfig(
        bot_token="your_token",
        chat_id="your_chat_id",
        enabled=True
    ),
    max_retry_count=5,
    retry_base_delay=60,  # 秒
    batch_interval=300    # 秒
)
```

---

## 集成點

### 緊急處理器

當緊急模式啟動時，自動發送 CRITICAL 級別通知：

```python
# backend/src/vibe_trading/coordinator/emergency_handler.py
if self.telegram_notifier:
    title, message = MessageFormatter.format_emergency_mode(
        event_type=trigger_event.get('type', 'UNKNOWN'),
        description=trigger_event.get('description', ''),
        action_taken=decision.action
    )
    notification = Notification(
        id=f"emergency_{trigger_event.get('id', 'unknown')}",
        priority=NotificationPriority.CRITICAL,
        title=title,
        message=message
    )
    await self.telegram_notifier.queue.enqueue(notification)
```

### 交易協調器

當交易執行完成時，自動發送 HIGH 級別通知：

```python
# backend/src/vibe_trading/coordinator/trading_coordinator.py
if self._telegram_notifier and execution_result:
    title, message = MessageFormatter.format_trade_decision(
        symbol=trading_plan.symbol,
        action=trading_plan.action,
        price=trading_plan.price,
        quantity=trading_plan.quantity,
        reason=trading_plan.reason,
        pnl=execution_result.get('pnl')
    )
    notification = Notification(
        id=f"trade_{execution_result.get('order_id', 'unknown')}",
        priority=NotificationPriority.HIGH,
        title=title,
        message=message
    )
    await self.telegram_notifier.queue.enqueue(notification)
```

---

## 測試

### 運行測試

```bash
cd /home/brian/project/vibe-trading
source .venv/bin/activate
PYTHONPATH=backend/src python -m pytest tests/test_telegram_notifications.py -v
```

### 測試覆蓋

- ✅ 通知隊列（入隊/出隊/優先級/重試/確認）
- ✅ 消息格式化器（6 種消息類型）
- ✅ 配置管理（環境變量/默認值）

---

## 故障排除

### Q1: Bot 沒有收到消息

**檢查清單**：
1. 確認 `TELEGRAM_ENABLED=true`
2. 確認 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 正確
3. 確認 bot 有權限發送消息到你的 chat
4. 檢查日誌：`grep "Telegram" logs/vbt_restart_*.log`

### Q2: 收到 rate limit 錯誤

**原因**：Telegram 限制 bot 每分鐘 30 條消息

**解決方案**：
- 系統會自動處理 rate limit，等待後重試
- 如果頻繁觸發，考慮減少 LOW 級別通知的頻率

### Q3: Inline Keyboard 按鈕無響應

**原因**：callback data 格式錯誤或 bot 未正確處理

**解決方案**：
- 確認 bot 已啟動並運行
- 檢查日誌中的 callback 處理記錄

### Q4: 系統重啟後通知丟失

**說明**：通知隊列存於內存，系統重啟後會清除

**解決方案**：
- 這是設計行為，避免重複推送舊通知
- 如需持久化，可擴展為 SQLite 隊列（未來功能）

---

## 未來擴展

### 可能的增強功能

1. **SQLite 持久化隊列**
   - 系統重啟後恢復未發送通知
   - 通知歷史記錄查詢

2. **多用戶支持**
   - 多個 chat_id 配置
   - 權限分級（管理員/觀察者）

3. **交互式命令**
   - `/status` - 查詢系統狀態
   - `/positions` - 查詢當前持倉
   - `/pnl` - 查詢今日 PnL

4. **語音通知**
   - CRITICAL 級別升級為語音電話
   - 使用 Telegram Voice Call API

5. **通知模板自定義**
   - 用戶可自定義消息格式
   - 支持 Markdown/HTML 混合

---

## 更新日誌

### v1.0.0 (2026-08-12)

- ✅ 實現三級優先級通知隊列
- ✅ 實現指數退避重試機制
- ✅ 實現 Telegram Notifier（python-telegram-bot v20+）
- ✅ 實現 6 種消息格式化器
- ✅ 集成到緊急處理器和交易協調器
- ✅ 完整單元測試覆蓋（16 tests）
- ✅ Inline Keyboard 確認機制
