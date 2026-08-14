"""Agent replay tool isolation — 消除 look-ahead 污染.

產品化移植自 replay/replay_tool_isolation.py (SWDA 2026-08-09 P0 Fix ①),
並修復 2026-08-14 審計發現的 3 個漏洞 (audit agent://AuditLookAhead):

  MUST-FIX:
  1. ft.get_funding_rates (複數) — coordinator._get_analyst_data 直接呼叫,
     原 harness 只 patch 了 mdt.get_funding_rate (單數) → 今天 funding 注入歷史決策
  2. ft.get_open_interest — 原 patch 錯 namespace (patch 了 mdt.* 而非 ft.*)
  3. ft.get_fear_and_greed_index — 同類防禦性漏洞 (coordinator 走 sentiment_tools 版,
     但 ft 版若被未來呼叫同樣洩漏)
  SHOULD-FIX:
  4. _replay_get_current_price 接受 storage= kwarg (coordinator._fetch_benchmark_price
     以 keyword 傳入, 原簽名 storage_ 會 TypeError → 靜默 None)

問題: replay 用完整 13-agent TradingCoordinator, agents 的 tools
(get_current_price / get_funding_rate / get_order_book ...) 全部打 live API,
決策混入當下市場數據, 而非 replay bar 的歷史數據 → 回測不可信。

修復: monkey-patch vibe_trading.tools 各 module 的函數, 讓 replay 環境下:
- 價格類工具 → 從 replay storage 讀最新 bar close (無 look-ahead)
- 技術指標類工具 → 帶入 replay storage 計算 (吃 bar 內歷史)
- 其餘 live 數據工具 (funding/多空比/訂單簿/情緒/新聞...) → 回傳「replay 不可用」

安裝時機: replay driver 建立 coordinator 之後、跑 bar 之前。
"""

from __future__ import annotations

import logging
from typing import Optional

from vibe_trading.data_sources.kline_storage import KlineQuery

logger = logging.getLogger("replay.isolation")

_UNAVAILABLE = "N/A (replay 不可用)"


def install_replay_tool_isolation(storage, interval: str = "30m") -> None:
    """Monkey-patch 所有 live 數據 tools，改從 replay storage 讀取或回傳不可用。"""
    import vibe_trading.tools.market_data_tools as mdt
    import vibe_trading.tools.fundamental_tools as ft
    import vibe_trading.tools.sentiment_tools as st
    import vibe_trading.tools.technical_tools as tt

    # ---------- 價格：從 replay storage 讀最新 bar close ----------
    # 接受 storage= kwarg (audit SHOULD-FIX #4): coordinator._fetch_benchmark_price
    # 以 keyword 傳入 storage, 原簽名 storage_ 會 TypeError → 靜默 None
    async def _replay_get_current_price(symbol: str, **kwargs) -> dict:
        kline = await storage.get_latest_kline(symbol, interval)
        if kline is None:
            return {"error": "replay: no kline in storage"}
        return {
            "symbol": symbol,
            "price": kline.close,
            "timestamp": kline.close_time,
            "volume": kline.volume,
            "source": "replay-storage",
        }

    mdt.get_current_price = _replay_get_current_price

    # ---------- 24h ticker：從 storage 算近似 ----------
    async def _replay_get_24hr_ticker(symbol: str) -> dict:
        klines = await storage.query_klines(
            KlineQuery(symbol=symbol, interval=interval, limit=49)
        )
        if len(klines) < 2:
            return {"symbol": symbol, "price_change_percent": _UNAVAILABLE, "volume": _UNAVAILABLE}
        first_close = klines[0].close
        last_close = klines[-1].close
        vol = sum(k.volume for k in klines)
        pct = (last_close / first_close - 1.0) * 100.0 if first_close else 0.0
        return {
            "symbol": symbol,
            "price_change_percent": round(pct, 4),
            "volume": round(vol, 4),
            "source": "replay-storage",
        }

    mdt.get_24hr_ticker = _replay_get_24hr_ticker

    # ---------- 其他 live 數據：回傳不可用 ----------
    async def _unavailable(*args, **kwargs) -> dict:
        return {"error": "replay 模式：此 live 數據不可用（避免 look-ahead 污染）"}

    # market_data_tools 其餘函數
    mdt.get_funding_rate = _unavailable
    mdt.get_open_interest = _unavailable
    mdt.get_order_book = _unavailable
    # get_kline_data 在 market_data_tools，但 wrapper 從 technical_tools 呼叫 — 兩個都 patch

    async def _replay_get_kline_data(symbol: str, interval_: str = "30m", limit: int = 100, **kwargs) -> dict:
        klines = await storage.query_klines(
            KlineQuery(symbol=symbol, interval=interval_, limit=limit)
        )
        return {
            "symbol": symbol,
            "interval": interval_,
            "klines": [[k.open_time, k.open, k.high, k.low, k.close, k.volume] for k in klines],
            "source": "replay-storage",
        }

    mdt.get_kline_data = _replay_get_kline_data  # type: ignore[assignment]  # 故意替換簽名 (storage kwarg → 內建 closure)

    # fundamental_tools：多空比/吃單比/大戶比/清算 — live，禁用
    ft.get_long_short_ratio = _unavailable
    ft.get_taker_buy_sell_ratio = _unavailable
    ft.get_top_trader_long_short_ratio = _unavailable
    ft.get_liquidation_orders = _unavailable
    # ==== AUDIT MUST-FIX (2026-08-14) ====
    # coordinator._get_analyst_data 直接呼叫這三個, 原 harness 漏 patch →
    # 今天 funding/OI/F&G 注入歷史決策 (HIGH look-ahead)
    ft.get_funding_rates = _unavailable          # 複數 — trading_coordinator.py:1188,1219
    ft.get_open_interest = _unavailable          # 錯 namespace — trading_coordinator.py:1196
    ft.get_fear_and_greed_index = _unavailable   # 防禦性 — fundamental_tools.py:48

    # sentiment_tools：情緒/新聞/社交/熱門 — live，禁用
    st.get_fear_and_greed_index = _unavailable
    st.get_news_sentiment = _unavailable
    st.get_social_sentiment = _unavailable
    st.get_comprehensive_sentiment = _unavailable
    st.get_trending_symbols = _unavailable

    # ---------- 技術指標：帶入 replay storage ----------
    def _with_storage(fn):
        async def _wrapper(symbol: str, *args, **kwargs) -> dict:
            kwargs["storage"] = storage
            return await fn(symbol, *args, **kwargs)
        return _wrapper

    tt.get_technical_indicators = _with_storage(tt.get_technical_indicators)
    tt.get_comprehensive_technical_analysis = _with_storage(tt.get_comprehensive_technical_analysis)
    tt.analyze_trend = _with_storage(tt.analyze_trend)
    tt.detect_support_resistance = _with_storage(tt.detect_support_resistance)
    tt.calculate_pivots = _with_storage(tt.calculate_pivots)
    tt.detect_candlestick_patterns = _with_storage(tt.detect_candlestick_patterns)
    tt.detect_divergence = _with_storage(tt.detect_divergence)
    tt.analyze_volume_patterns = _with_storage(tt.analyze_volume_patterns)
    # get_kline_data 定義在 market_data_tools，wrapper 卻呼叫 technical_tools.get_kline_data
    # （既有 bug：原本會 AttributeError）— 補上 replay 版本避免 crash
    tt.get_kline_data = _replay_get_kline_data  # type: ignore[attr-defined]

    logger.info("Replay tool isolation installed: live tools disabled, data from replay storage")
