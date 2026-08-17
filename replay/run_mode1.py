#!/usr/bin/env python
import asyncio
import sys
from vibe_trading.backtest.agent_models import AgentReplayConfig
from vibe_trading.backtest.agent_replay import run_replay

async def main():
    # Mode 1: 50-bar Replay over Segment A (Downtrend / Active Shorting)
    config = AgentReplayConfig(
        symbol="BTCUSDT",
        interval="30m",
        bars_path="replay/data/bars_90d.json",
        start=1742,
        end=1792,  # 50 bars
        skip_debate=True,  # Fast & focused 8-call pipeline for speed
        quiet=True,
        use_cache=True,
        yes=True,
        log_path="replay/data/mode1_decisions.jsonl",
        usage_db_path="vibe_trading.db",
    )
    print(f"[Mode 1] Starting 50-bar Replay (1742..1792) -> {config.log_path}", flush=True)
    res = await run_replay(config)
    print(f"[Mode 1] Finished Replay: {res}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
