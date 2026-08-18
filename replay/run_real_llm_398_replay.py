#!/usr/bin/env python
"""Real LLM 398-Bar Replay Driver.

Executes the full real 13-Agent LLM pipeline over all 398 historical bars
(BTCUSDT 30m, 2026-08-07 to 2026-08-16) with Harvested Alpha contexts injected,
LLM cache enabled, and automated state logging.
"""
import asyncio
import sys
from pathlib import Path

from vibe_trading.backtest.agent_models import AgentReplayConfig
from vibe_trading.backtest.agent_replay import run_replay


async def main():
    config = AgentReplayConfig(
        symbol="BTCUSDT",
        interval="30m",
        bars_path="replay/data/bars.json",
        start=120,
        end=518,  # exactly 398 bars
        skip_debate=True,  # Fast 8-call pipeline (analysts -> risk -> trader -> PM)
        quiet=True,
        use_cache=True,
        resume=True,
        yes=True,
        log_path="replay/data/real_llm_398_decisions.jsonl",
        db_path="replay/data/real_llm_398.db",
        state_path="replay/data/real_llm_398_state.json",
        usage_db_path="vibe_trading.db",
    )
    print("=" * 75, flush=True)
    print(f"🚀 開始執行【真實 LLM 398 根 Bar 全量 Replay】", flush=True)
    print(f"   • 標的/週期: {config.symbol} {config.interval}", flush=True)
    print(f"   • 樣本區間: Bar 120 .. 518 (共 398 根)", flush=True)
    print(f"   • 決策日誌: {config.log_path}", flush=True)
    print(f"   • 快取狀態: LLM Cache 啟用 / 斷點續傳 Resume 啟用", flush=True)
    print("=" * 75, flush=True)

    result = await run_replay(config)
    print("=" * 75, flush=True)
    print(f"✅ 真實 LLM 398 根 Bar 回測完成: {result}", flush=True)
    print("=" * 75, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
