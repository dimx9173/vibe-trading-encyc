#!/usr/bin/env python
"""Phase 5 L3 — 跨市場體制壓力測試 (短回測).

每個體制 ~21 bars (LLM 回測), 驗證:
- 體制 A (下跌段): 做空能力
- 體制 B (上漲段): 做多能力
- 體制 C (橫盤段): HOLD 觀望

用法:
    python -m replay.run_l3_stress  [--limit N]   # N = 每段 bars (預設 21)
"""
import asyncio
import sys

from vibe_trading.backtest.agent_models import AgentReplayConfig
from vibe_trading.backtest.agent_replay import run_replay

SEGMENTS = {
    "A_downtrend": {
        "bars_path": "replay/data/bars_90d.json",
        "start": 1742,  # 06-22 00:30 warmup 起
        "log": "replay/data/l3_A_downtrend.jsonl",
    },
    "B_uptrend": {
        "bars_path": "replay/data/bars_90d.json",
        "start": 2696,  # 07-11 21:30 warmup 起
        "log": "replay/data/l3_B_uptrend.jsonl",
    },
    "C_choppy": {
        "bars_path": "replay/data/bars.json",  # 08-07~16 橫盤
        "start": 120,  # warmup 後
        "log": "replay/data/l3_C_choppy.jsonl",
    },
}


async def run_segment(name: str, seg: dict, limit: int) -> None:
    config = AgentReplayConfig(
        symbol="BTCUSDT",
        interval="30m",
        bars_path=seg["bars_path"],
        start=seg["start"],
        end=seg["start"] + limit,
        skip_debate=True,
        quiet=True,
        use_cache=True,
        yes=True,
        log_path=seg["log"],
        usage_db_path="vibe_trading.db",
    )
    print(f"[L3] 開始 {name}: start={seg['start']} bars={limit} → {seg['log']}", flush=True)
    result = await run_replay(config)
    print(f"[L3] 完成 {name}: {result}", flush=True)


def main():
    limit = 21
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    async def _all():
        for name, seg in SEGMENTS.items():
            try:
                await run_segment(name, seg, limit)
            except Exception as e:
                print(f"[L3] {name} 失敗: {e}", flush=True)
    asyncio.run(_all())
    print("[L3] 全部完成")


if __name__ == "__main__":
    main()
