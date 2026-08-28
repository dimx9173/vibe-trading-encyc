"""Replay smoke — RuleEngineLoop driven over historical bars (spec phase1 §8).

Usage (from repo root, backend venv):
    python replay/replay_rule_engine.py --symbol BTCUSDT --bars replay/data/bars.json
    python replay/replay_rule_engine.py --symbol ETHUSDT --bars replay/data/bars_eth_7d.json
    python replay/replay_rule_engine.py --symbol SOLUSDT --bars replay/data/bars_sol_7d.json

RISK_OFF injection drill:
    python replay/replay_rule_engine.py --symbol BTCUSDT --bars replay/data/bars.json \
        --inject-regime RISK_OFF --macro-db replay/data/rule_macro_riskoff.db
    (asserts zero new opens across the whole run; exits non-zero on failure)

Each bar: store_kline -> update_price -> on_bar (rule loop). Output JSONL of
RuleDecision per bar + account snapshot.
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

from vibe_trading.data_sources.kline_storage import Kline, KlineStorage  # noqa: E402
from vibe_trading.data_sources.macro_storage import MacroState, MacroStorage  # noqa: E402
from vibe_trading.execution.order_audit import ExecutionAuditStorage  # noqa: E402
from vibe_trading.execution.order_executor import PaperOrderExecutor  # noqa: E402
from vibe_trading.rule_engine.config import RuleEngineConfig  # noqa: E402
from vibe_trading.rule_engine.loop import RuleEngineLoop  # noqa: E402

WARMUP_BARS = 120


def _to_kline(symbol: str, interval: str, bar: list) -> Kline:
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


async def _inject_regime(macro_storage: MacroStorage, symbol: str, regime: str) -> None:
    state = MacroState(
        symbol=symbol,
        timestamp=int(time.time() * 1000),
        trend_direction="DOWNTREND",
        trend_strength="STRONG",
        market_regime=regime,
        overall_sentiment="NEGATIVE",
        sentiment_score=-50.0,
        major_events=[],
        agent_recommendation={},
        confidence=0.9,
        analysis_duration=1.0,
    )
    await macro_storage.save_state(state)


async def _account_snapshot(executor) -> dict:
    balances = await executor.get_balance()
    usdt = balances.get("USDT", 0.0)
    balance = float(usdt.get("available", usdt.get("balance", 0.0))) if isinstance(usdt, dict) else float(usdt)
    positions = await executor.get_positions()
    pos_list = [
        {
            "symbol": p.symbol,
            "position_side": str(getattr(p.position_side, "value", p.position_side)),
            "position_amount": p.position_amount,
            "entry_price": p.entry_price,
        }
        for p in positions
    ]
    return {"balance": balance, "positions": pos_list}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--bars", default="replay/data/bars.json")
    ap.add_argument("--state", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--macro-db", default=None)
    ap.add_argument("--start", type=int, default=WARMUP_BARS)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--inject-regime", default=None,
                    help="RISK_ON/NEUTRAL/RISK_OFF; 断言 inject RISK_OFF 时全程零新开仓")
    args = ap.parse_args()

    symbol = args.symbol
    tag = symbol.lower().replace("usdt", "")
    args.state = args.state or f"replay/data/rule_{tag}_state.json"
    args.log = args.log or f"replay/data/rule_{tag}_decisions.jsonl"
    args.db = args.db or f"replay/data/rule_{tag}.db"
    args.macro_db = args.macro_db or f"replay/data/rule_macro_{tag}.db"

    bars_data = json.loads(Path(args.bars).read_text(encoding="utf-8"))
    replay = bars_data[args.start: args.end if args.end is not None else len(bars_data)]
    print(f"RuleEngine replay [{symbol}]: {len(replay)} bars "
          f"({datetime.fromtimestamp(replay[0][0]/1000, tz=timezone.utc):%m-%d %H:%M} -> "
          f"{datetime.fromtimestamp(replay[-1][0]/1000, tz=timezone.utc):%m-%d %H:%M})")

    db_url = f"sqlite+aiosqlite:///{Path(args.db).resolve()}"
    storage = KlineStorage(database_url=db_url)
    await storage.init()
    warmup = bars_data[: args.start]
    for bar in warmup:
        await storage.store_kline(_to_kline(symbol, "30m", bar))
    print(f"Seeded {len(warmup)} warmup bars into {args.db}")

    executor = PaperOrderExecutor(
        initial_balance=10_000.0,
        state_file=str(Path(args.state)),
        reset=True,
        enable_exit_ladder=False,  # 出场单一权威: RuleEngineLoop 内的 ExitLadderEngine
    )

    macro_storage = MacroStorage(database_url=f"sqlite+aiosqlite:///{Path(args.macro_db).resolve()}")
    await macro_storage.init()
    if args.inject_regime:
        await _inject_regime(macro_storage, symbol, args.inject_regime)
        print(f"Injected macro regime {args.inject_regime} for {symbol} -> {args.macro_db}")

    audit = ExecutionAuditStorage(
        database_url=f"sqlite+aiosqlite:///{Path(args.db).resolve()}.audit"
    )

    config = RuleEngineConfig.from_env()
    config.interval = "30m"
    loop = RuleEngineLoop(
        symbol=symbol,
        interval="30m",
        storage=storage,
        executor=executor,
        macro_storage=macro_storage,
        config=config,
        audit_storage=audit,
    )

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_handler = RotatingFileHandler(
        str(log_path), maxBytes=100 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    jsonl_handler.setFormatter(logging.Formatter("%(message)s"))
    jsonl_logger = logging.getLogger(f"replay.rule.{symbol}")
    jsonl_logger.setLevel(logging.INFO)
    jsonl_logger.propagate = False
    jsonl_logger.addHandler(jsonl_handler)

    opens = 0
    risk_off_blocks = 0
    t0 = time.time()
    for i, bar in enumerate(replay):
        k = _to_kline(symbol, "30m", bar)
        decision = await loop.on_bar(k)
        snapshot = await _account_snapshot(executor)
        if decision.action == "open":
            opens += 1
        if decision.blocked_by == "RISK_OFF":
            risk_off_blocks += 1
        rec = {
            "symbol": symbol,
            "interval": "30m",
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **decision.to_dict(),
            "account": snapshot,
        }
        # RuleSignal 是 dataclass — to_dict 已 asdict 展开
        rec["signal"] = decision.signal.__dict__ if decision.signal else None
        jsonl_logger.info(json.dumps(rec, ensure_ascii=False, default=str))
        if (i + 1) % 50 == 0 or i == len(replay) - 1:
            print(f"  bar {i+1}/{len(replay)} @ {datetime.fromtimestamp(bar[0]/1000, tz=timezone.utc):%m-%d %H:%M} "
                  f"action={decision.action} regime={decision.regime} [{time.time()-t0:.0f}s]")

    print(f"bars={len(replay)} actions_opens={opens} risk_off_blocks={risk_off_blocks} jsonl={args.log}")

    fail = False
    if args.inject_regime == "RISK_OFF" and opens > 0:
        print(f"FAIL: RISK_OFF injection expected zero new opens, got {opens}")
        fail = True
    if args.inject_regime == "RISK_OFF" and opens == 0:
        print(f"PASS: RISK_OFF injection blocked all new entries "
              f"(gate fired {risk_off_blocks}x, zero opens)")
    await storage.close()
    await macro_storage.close()
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    asyncio.run(main())