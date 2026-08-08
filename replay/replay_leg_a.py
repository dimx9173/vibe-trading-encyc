"""Replay driver — leg A (vibe-trading VBT bot, 13-agent coordinator).

Feeds the same historical BTCUSDT 30m bars used by leg B into the full
TradingCoordinator pipeline (analysts -> researchers -> risk -> trader -> PM),
with isolated KlineStorage (separate sqlite DB), isolated paper executor state,
and memory=None (avoids live benchmark-price reflection calls).

IMPORTANT: each bar is stored into the replay DB *before* the decision, so the
coordinator's `_prepare_context` (query limit=100) sees history only up to the
current replay bar — no look-ahead from future bars.

Usage (from backend/ dir, with the backend venv):
    python ../replay/replay_leg_a.py --bars ../replay/data/bars.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from vibe_trading.coordinator.trading_coordinator import TradingCoordinator  # noqa: E402
from vibe_trading.data_sources.kline_storage import Kline, KlineStorage  # noqa: E402
from vibe_trading.execution.order_executor import PaperOrderExecutor  # noqa: E402

WARMUP_BARS = 120  # must match fetch_bars.py --warmup-bars


def _to_kline(symbol: str, interval: str, bar: list) -> Kline:
    """Build a Kline from a 6-field OHLCV bar (fills quote_volume/trades/taker_* with 0).

    The fetch_bars.py pipeline stores only [open_ms, open, high, low, close, volume].
    KlineModel requires four extra columns (quote_volume, trades, taker_buy_base,
    taker_buy_quote); replay decisions are price/indicator-driven and do not need
    them, so 0 is a safe placeholder.
    """
    open_ms, o, h, l, c, v = bar
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time=int(open_ms),
        open=float(o),
        high=float(h),
        low=float(l),
        close=float(c),
        volume=float(v),
        close_time=int(open_ms) + 30 * 60 * 1000 - 1,
        quote_volume=0.0,
        trades=0,
        taker_buy_base=0.0,
        taker_buy_quote=0.0,
        is_final=True,
    )


async def _account_state(executor) -> tuple[float, list]:
    balances = await executor.get_balance()
    usdt = balances.get("USDT", 0.0)
    if isinstance(usdt, dict):
        balance = float(usdt.get("available", usdt.get("balance", 10000.0)))
    else:
        balance = float(usdt)
    positions = await executor.get_positions()
    pos_list = [
        {
            "symbol": p.symbol,
            "position_side": str(getattr(p.position_side, "value", p.position_side)),
            "position_amount": p.position_amount,
            "entry_price": p.entry_price,
            "mark_price": p.mark_price,
            "unrealized_profit": p.unrealized_profit,
            "leverage": p.leverage,
        }
        for p in positions
    ]
    return balance, pos_list


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", default="replay/data/bars.json")
    ap.add_argument("--state", default="replay/data/leg_a_state.json")
    ap.add_argument("--log", default="replay/data/leg_a_decisions.jsonl")
    ap.add_argument("--db", default="replay/data/replay_a.db")
    ap.add_argument("--start", type=int, default=WARMUP_BARS, help="first replay bar index")
    ap.add_argument("--end", type=int, default=None, help="exclusive last replay bar index")
    ap.add_argument("--quiet", action="store_true", help="disable LLM streaming output (only show decision summary)")
    args = ap.parse_args()

    bars = json.loads(Path(args.bars).read_text(encoding="utf-8"))
    replay = bars[args.start : args.end if args.end is not None else len(bars)]
    print(f"Leg A replay: {len(replay)} bars "
          f"({datetime.fromtimestamp(replay[0][0]/1000, tz=timezone.utc):%m-%d %H:%M} -> "
          f"{datetime.fromtimestamp(replay[-1][0]/1000, tz=timezone.utc):%m-%d %H:%M})")

    # Isolated storage: seed warmup bars only (up to first replay bar).
    db_url = f"sqlite+aiosqlite:///{Path(args.db).resolve()}"
    storage = KlineStorage(database_url=db_url)
    await storage.init()
    warmup = bars[: args.start]
    for bar in warmup:
        await storage.store_kline(_to_kline("BTCUSDT", "30m", bar))
    print(f"Seeded {len(warmup)} warmup bars into {args.db}")

    executor = PaperOrderExecutor(
        initial_balance=10_000.0,
        state_file=str(Path(args.state)),
        reset=True,
    )
    coordinator = TradingCoordinator(
        symbol="BTCUSDT",
        interval="30m",
        storage=storage,
        memory=None,  # skip reflection (avoids live benchmark fetch)
        executor=executor,
        enable_streaming=not args.quiet,
    )
    await coordinator.initialize()

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Rotating JSONL writer: 100 MB/file, 5 backups (~600 MB max)
    jsonl_handler = RotatingFileHandler(
        str(log_path), maxBytes=100 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    jsonl_handler.setFormatter(logging.Formatter("%(message)s"))
    jsonl_logger = logging.getLogger("replay.jsonl")
    jsonl_logger.setLevel(logging.INFO)
    jsonl_logger.propagate = False
    jsonl_logger.addHandler(jsonl_handler)

    t0 = time.time()
    for i, bar in enumerate(replay):
        open_ms, o, h, l, c, v = bar
        # Store this bar BEFORE deciding so context sees history up to now.
        await storage.store_kline(_to_kline("BTCUSDT", "30m", bar))
        executor.update_price("BTCUSDT", float(c))
        balance, positions = await _account_state(executor)

        bar_t0 = time.time()
        decision = await coordinator.analyze_and_decide(
            current_price=float(c),
            account_balance=balance,
            current_positions=positions,
            bar_open_time_ms=int(open_ms),
        )
        elapsed = time.time() - bar_t0

        # Read back post-decision account state (PM may have filled orders).
        balance2, positions2 = await _account_state(executor)
        rec = {
            "symbol": "BTCUSDT",
            "interval": "30m",
            "bar_open_ms": int(open_ms),
            "bar_close": float(c),
            "decision": decision.decision,
            "rationale": decision.rationale[:500],
            "confidence": getattr(decision, "confidence", None),
            "elapsed_s": round(elapsed, 1),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "account": {
                "balance": balance2,
                "positions": positions2,
                "equity": balance2 + sum(
                    p["unrealized_profit"] for p in positions2
                ),
            },
        }
        jsonl_logger.info(json.dumps(rec, ensure_ascii=False, default=str))

        if (i + 1) % 8 == 0 or i == len(replay) - 1:
            total = time.time() - t0
            print(f"  bar {i+1}/{len(replay)} @ {datetime.fromtimestamp(open_ms/1000, tz=timezone.utc):%m-%d %H:%M} "
                  f"decision={decision.decision} ({elapsed:.0f}s, total {total:.0f}s)")

    await storage.close()
    print("\n=== Leg A replay done ===")


if __name__ == "__main__":
    asyncio.run(main())
