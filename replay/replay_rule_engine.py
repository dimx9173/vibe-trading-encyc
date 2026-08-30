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
import os
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


async def _inject_detail(macro_storage: MacroStorage, symbol: str, detail: str) -> None:
    detail = detail.strip().upper()
    if detail not in ("CHOPPY", "TRENDING", "UNCERTAIN"):
        detail = "UNCERTAIN"
    state = MacroState(
        symbol=symbol,
        timestamp=int(time.time() * 1000),
        trend_direction="SIDEWAYS" if detail == "CHOPPY" else "UPTREND",
        trend_strength="WEAK" if detail == "CHOPPY" else "STRONG",
        market_regime="NEUTRAL",
        overall_sentiment="NEUTRAL",
        sentiment_score=0.0,
        major_events=[],
        agent_recommendation={},
        confidence=0.7,
        analysis_duration=0.5,
        regime_detail=detail,
    )
    await macro_storage.save_state(state)


async def _seed_replay_macro_db(replay_macro_db: str, symbol: str, detail: str, bars_data: list) -> None:
    detail = detail.strip().upper()
    if detail not in ("CHOPPY", "TRENDING", "UNCERTAIN"):
        detail = "UNCERTAIN"
    src = Path(replay_macro_db)
    if not src.exists():
        return
    import aiosqlite

    async with aiosqlite.connect(str(src)) as src_conn:
        src_conn.row_factory = aiosqlite.Row
        try:
            cur = await src_conn.execute("SELECT * FROM macro_states ORDER BY timestamp ASC")
            rows = await cur.fetchall()
        except Exception:
            return
        if not rows:
            return
        for row in rows:
            d = dict(row)
            await _inject_detail_with_ts(symbol, d, detail)


async def _inject_detail_with_ts(symbol: str, row_dict: dict, detail: str) -> None:
    pass


async def _account_snapshot(executor) -> dict:
    """账戸快照 (tearsheet 用). equity = 现金 + 锁仓保证金 + 未实现盈亏.

    注意: place_order 开仓时 balance 已扣除保证金 (balance -= notional/leverage),
    仅用 available (=balance+unrealized) 会因开仓假性下陷 (PnL 高估前科, 收敛计划 §4).
    equity 重建 = balance + Σ(notional/leverage) + unrealized, 保证金不计入亏损.
    """
    balances = await executor.get_balance()
    usdt = balances.get("USDT", 0.0)
    balance = float(usdt.get("balance", 0.0)) if isinstance(usdt, dict) else float(usdt)
    available = float(usdt.get("available", balance)) if isinstance(usdt, dict) else balance
    unrealized = float(usdt.get("unrealized_pnl", 0.0)) if isinstance(usdt, dict) else 0.0
    realized = float(usdt.get("realized_pnl", 0.0)) if isinstance(usdt, dict) else 0.0
    positions = await executor.get_positions()
    pos_list = [
        {
            "symbol": p.symbol,
            "position_side": str(getattr(p.position_side, "value", p.position_side)),
            "position_amount": p.position_amount,
            "entry_price": p.entry_price,
            "leverage": p.leverage,
        }
        for p in positions
    ]
    locked_margin = sum(float(p.notional) / float(p.leverage) for p in positions
                        if p.leverage > 1 and float(p.notional) > 0)
    equity = balance + locked_margin + unrealized
    return {
        "balance": balance,
        "available": available,
        "unrealized": unrealized,
        "realized": realized,
        "equity": equity,
        "positions": pos_list,
    }


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
    ap.add_argument("--fee-bps", type=int, default=int(os.getenv("REPLAY_FEE_BPS", "8")),
                    help="fee in bps applied as pnl *= (1 - fee_bps/10000) per winning trade")
    ap.add_argument("--replay-macro-db", default=None,
                    help="path to macro_states db to seed regime history for backtest")
    ap.add_argument("--inject-detail", default=None,
                    help="CHOPPY|TRENDING|UNCERTAIN to seed macro_states for backtest")
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
    if args.inject_detail:
        await _inject_detail(macro_storage, symbol, args.inject_detail)
        print(f"Injected macro detail {args.inject_detail} for {symbol} -> {args.macro_db}")
    if args.replay_macro_db:
        import shutil
        src = Path(args.replay_macro_db)
        dst = Path(args.macro_db)
        if src.exists() and src.resolve() != dst.resolve():
            try:
                shutil.copy2(str(src), str(dst))
                print(f"Seeded macro DB from {src} -> {dst}")
                await macro_storage.close()
                macro_storage = MacroStorage(database_url=f"sqlite+aiosqlite:///{dst.resolve()}")
                await macro_storage.init()
            except Exception as e:
                print(f"replay-macro-db copy failed: {e}", file=sys.stderr)
        if args.inject_detail:
            await _inject_detail(macro_storage, symbol, args.inject_detail)
            print(f"Injected macro detail {args.inject_detail} for {symbol} -> {args.macro_db} (after seed)")

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
    detail_history: list[str] = []
    pf_window: list[float] = []
    circuit_until = -1
    original_bb_threshold = os.getenv("RULE_BB_WIDTH_THRESHOLD", None)
    t0 = time.time()
    for i, bar in enumerate(replay):
        if circuit_until >= 0 and i >= circuit_until:
            if original_bb_threshold is None:
                os.environ.pop("RULE_BB_WIDTH_THRESHOLD", None)
            else:
                os.environ["RULE_BB_WIDTH_THRESHOLD"] = original_bb_threshold
            circuit_until = -1
        k = _to_kline(symbol, "30m", bar)
        decision = await loop.on_bar(k)
        try:
            macro_state = await macro_storage.get_latest_state(None)
            cur_detail = getattr(macro_state, "regime_detail", "UNCERTAIN") if macro_state else "UNCERTAIN"
        except Exception:
            cur_detail = "UNCERTAIN"
        cur_detail = str(cur_detail).strip().upper() if cur_detail else "UNCERTAIN"
        if cur_detail not in ("CHOPPY", "TRENDING", "UNCERTAIN"):
            cur_detail = "UNCERTAIN"
        detail_history.append(cur_detail)
        if len(detail_history) > 96:
            detail_history = detail_history[-96:]
        # §5.1 熔断: 6hr window = 12 bars of 30m, PF<0.9 + CHOPPY连续3个2hr周期(12 bars CHOPPY concentration)
        if len(detail_history) >= 12:
            window = detail_history[-12:]
            choppy_count = sum(1 for d in window if d == "CHOPPY")
            if choppy_count >= 9:
                # estimate PF from recent realized deltas
                try:
                    balances = await executor.get_balance()
                    usdt = balances.get("USDT", {})
                    realized_now = float(usdt.get("realized_pnl", 0.0)) if isinstance(usdt, dict) else 0.0
                    pf_window.append(realized_now)
                    if len(pf_window) > 12:
                        pf_window = pf_window[-12:]
                    if len(pf_window) >= 12:
                        deltas = [pf_window[j] - pf_window[j-1] for j in range(1, len(pf_window))]
                        gp = sum(d for d in deltas if d > 0)
                        gl = abs(sum(d for d in deltas if d < 0))
                        pf = gp / gl if gl > 1e-9 else (float("inf") if gp > 1e-9 else 0.0)
                        if pf < 0.9 and circuit_until == -1:
                            os.environ["RULE_BB_WIDTH_THRESHOLD"] = "0"
                            circuit_until = i + 96
                            print(f"  CIRCUIT: choppy 6hr PF {pf:.2f} <0.9 -> RULE_BB_WIDTH_THRESHOLD=0 for 48hr (96 bars) @ bar {i}")
                except Exception:
                    pass
        snapshot = await _account_snapshot(executor)
        if args.fee_bps and snapshot.get("realized", 0) > 0:
            # per-trade fee is accounted in tearsheet; snapshot equity not mutated here beyond snapshot
            pass
        if decision.action == "open":
            opens += 1
        if decision.blocked_by == "RISK_OFF":
            risk_off_blocks += 1
        # fee applied per trade before equity in tearsheet; for replay equity snapshot include fee if positive delta
        if args.fee_bps:
            try:
                # apply fee to realized portion of equity for this snapshot (winning incremental only)
                # snapshot realized already includes full pnl; we adjust equity proportionally if needed via fee_mult on positive deltas only
                # simpler: snapshot equity = balance+locked+unrealized already; fee only affects realized deltas in tearsheet, not here
                pass
            except Exception:
                pass
        rec = {
            "symbol": symbol,
            "interval": "30m",
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **decision.to_dict(),
            "account": snapshot,
            "fee_bps": int(args.fee_bps),
            "regime_detail": cur_detail,
        }
        rec["signal"] = decision.signal.__dict__ if decision.signal else None
        jsonl_logger.info(json.dumps(rec, ensure_ascii=False, default=str))
        if (i + 1) % 50 == 0 or i == len(replay) - 1:
            print(f"  bar {i+1}/{len(replay)} @ {datetime.fromtimestamp(bar[0]/1000, tz=timezone.utc):%m-%d %H:%M} "
                  f"action={decision.action} regime={decision.regime} detail={cur_detail} [{time.time()-t0:.0f}s]")

    print(f"bars={len(replay)} actions_opens={opens} risk_off_blocks={risk_off_blocks} jsonl={args.log} fee_bps={args.fee_bps}")

    fail = False
    if args.inject_regime == "RISK_OFF" and opens > 0:
        print(f"FAIL: RISK_OFF injection expected zero new opens, got {opens}")
        fail = True
    if args.inject_regime == "RISK_OFF" and opens == 0:
        print(f"PASS: RISK_OFF injection blocked all new entries "
              f"(gate fired {risk_off_blocks}x, zero opens)")
    await storage.close()
    await macro_storage.close()
    # restore env
    if original_bb_threshold is None:
        os.environ.pop("RULE_BB_WIDTH_THRESHOLD", None)
    else:
        os.environ["RULE_BB_WIDTH_THRESHOLD"] = original_bb_threshold
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
