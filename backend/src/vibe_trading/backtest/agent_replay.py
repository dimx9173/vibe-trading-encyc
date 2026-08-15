"""Agent replay driver — full 13-agent pipeline over historical bars.

產品化移植自 replay/replay_leg_a.py (SWDA 2026-08-09), 新增 (grill 決策):
- LLM response cache (Q4/Q8/Q9): 按 (model, role, prompt_hash) 快取, 重跑近零成本
- --resume (Q7): 跳過 JSONL 已完成的 bar
- 成本估算 + 確認閘門 (Q11): run 前顯示預估, --yes 跳過
- insurance 禁用 (Q15): replay 確定性 (PM 的 submit_trade_order tool 仍執行成交)

IMPORTANT: each bar is stored into the replay DB *before* the decision, so the
coordinator's `_prepare_context` (query limit=100) sees history only up to the
current replay bar — no look-ahead from future bars. Tool isolation
(agent_isolation.py) blocks live external data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from pi_ai import TextContent  # type: ignore[import-untyped]

from vibe_trading.backtest.agent_cache import (
    LLMCache,
    deserialize_response,
    prompt_hash,
    serialize_response,
)
from vibe_trading.backtest.agent_isolation import install_replay_tool_isolation
from vibe_trading.backtest.agent_models import AgentReplayConfig, AgentReplayResult, ReplayRecord
from vibe_trading.coordinator.trading_coordinator import TradingCoordinator
from vibe_trading.data_sources.kline_storage import Kline, KlineStorage
from vibe_trading.execution.order_executor import PaperOrderExecutor

logger = logging.getLogger("replay")

WARMUP_BARS = 120  # must match fetch_bars.py --warmup-bars

# 每 bar LLM 呼叫數: 4 analysts + (2 bull + 2 bear + 1 manager) + 3 risk + 1 trader + 1 PM
CALLS_PER_BAR_FULL = 13
CALLS_PER_BAR_SKIP_DEBATE = 8  # 跳過 debate (5 calls)


def _to_kline(symbol: str, interval: str, bar: list) -> Kline:
    """Build a Kline from a 6-field OHLCV bar (fills quote_volume/trades/taker_* with 0)."""
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


async def _account_state(executor) -> tuple[float, List[Dict]]:
    balances = await executor.get_balance()
    usdt = balances.get("USDT", 0.0)
    if isinstance(usdt, dict):
        balance = float(usdt.get("available") or usdt.get("balance") or 10000.0)
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


# ============================================================================
# LLM cache wiring — wrap agent.prompt: hit → inject cached response, miss → cache
# ============================================================================

def _read_last_assistant_text(agent: Any) -> str:
    """Read last assistant message text from agent state (mirrors analyst read path)."""
    messages = getattr(getattr(agent, "state", None), "messages", None) or []
    for m in reversed(messages):
        if getattr(m, "role", None) == "assistant":
            content = getattr(m, "content", None)
            if isinstance(content, list):
                parts = [c.text for c in content if isinstance(c, TextContent) and c.text]
                if parts:
                    return "".join(parts)
            elif content:
                return str(content)
    return ""


def _inject_cached_response(agent: Any, response: str) -> None:
    """Append a synthetic assistant message so the coordinator's read path works."""
    messages = getattr(getattr(agent, "state", None), "messages", None)
    if messages is None:
        return
    messages.append(SimpleNamespace(role="assistant", content=[TextContent(text=response)]))


def install_cache_wrapper(agent: Any, role: str, cache: LLMCache, model: str) -> None:
    """Wrap the agent's actual LLM prompt method with the cache.

    Coordinator agents (analysts/researchers/trader/PM) call the LLM through an
    internal pi Agent at ``self._agent.prompt`` (via ``prompt_with_timeout``) —
    not via ``agent.prompt`` on the wrapper. Resolve the real target so the
    cache actually intercepts LLM calls for every role.
    """
    target = getattr(agent, "_agent", None)
    if target is None or not hasattr(target, "prompt"):
        target = agent
    if not hasattr(target, "prompt"):
        logger.warning(f"Cache wrapper skipped for {role}: no prompt method on agent")
        return
    original_prompt = target.prompt

    async def cached_prompt(prompt: str) -> bool:
        h = prompt_hash(prompt)
        cached = await cache.get(model, role, h)
        if cached is not None:
            _inject_cached_response(agent, deserialize_response(cached))
            return True
        ok = await original_prompt(prompt)
        if ok:
            response = _read_last_assistant_text(agent)
            if response.strip():
                await cache.put(model, role, h, serialize_response(response))
        return ok

    target.prompt = cached_prompt


def _iter_coordinator_agents(coordinator: TradingCoordinator):
    """Yield (role, agent) for every agent in the coordinator."""
    for role, agent in (getattr(coordinator, "_analysts", None) or {}).items():
        yield f"analyst:{role}", agent
    for role, agent in (getattr(coordinator, "_researchers", None) or {}).items():
        yield f"researcher:{role}", agent
    for role, agent in (getattr(coordinator, "_risk_analysts", None) or {}).items():
        yield f"risk:{role}", agent
    if getattr(coordinator, "_trader", None):
        yield "trader", coordinator._trader
    if getattr(coordinator, "_portfolio_manager", None):
        yield "portfolio_manager", coordinator._portfolio_manager


# ============================================================================
# Cost estimate (Q11)
# ============================================================================

async def _estimate_avg_cost_usd(config: AgentReplayConfig) -> Optional[float]:
    """Average cost per LLM call from usage ledger history (fallback: model pricing)."""
    try:
        from vibe_trading.monitoring.usage_ledger import UsageLedger
        ledger = UsageLedger(config.usage_db_path)
        summary = await ledger.get_summary(symbol=config.symbol)
        if summary and summary.total_requests > 0:
            return float(summary.total_cost_usd) / float(summary.total_requests)
    except Exception as e:
        logger.warning(f"Cost estimate from ledger failed: {e}")
    # Fallback: rough DeepSeek-flash class pricing
    return 0.0003


async def _confirm_run(config: AgentReplayConfig, bars_count: int) -> bool:
    """Cost estimate + confirmation gate."""
    if config.yes:
        return True
    avg = await _estimate_avg_cost_usd(config)
    calls_per_bar = CALLS_PER_BAR_SKIP_DEBATE if config.skip_debate else CALLS_PER_BAR_FULL
    est_cost = bars_count * calls_per_bar * (avg or 0.0)
    est_minutes = bars_count * 3.0 if config.skip_debate else bars_count * 10.0
    print(f"⚠️  Agent replay 成本預估:")
    print(f"   bars: {bars_count} × ~{calls_per_bar} LLM calls/bar ≈ {bars_count * calls_per_bar} calls")
    print(f"   預估成本: ${est_cost:.2f} (avg ${avg or 0:.4f}/call)")
    print(f"   預估時間: ~{est_minutes:.0f} min (skip_debate={'yes' if config.skip_debate else 'no'})")
    resp = input("確定繼續? [y/N] ").strip().lower()
    return resp in ("y", "yes")


# ============================================================================
# Main driver
# ============================================================================

async def run_replay(config: AgentReplayConfig) -> AgentReplayResult:
    """Run the full agent pipeline over historical bars."""
    bars = json.loads(Path(config.bars_path).read_text(encoding="utf-8"))
    replay = bars[config.start: config.end if config.end is not None else len(bars)]
    if not replay:
        raise ValueError(f"無可回放 bars (start={config.start}, end={config.end}, total={len(bars)})")

    # Resume: skip bars already logged
    done_ms: set = set()
    if config.resume and Path(config.log_path).exists():
        for line in Path(config.log_path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done_ms.add(int(rec["bar_open_ms"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        replay = [b for b in replay if int(b[0]) not in done_ms]
        print(f"Resume: {len(done_ms)} bars already done, {len(replay)} remaining")

    if not await _confirm_run(config, len(replay)):
        print("已取消")
        return AgentReplayResult(symbol=config.symbol, interval=config.interval)

    # Isolated storage: seed warmup bars only (up to first replay bar)
    db_url = f"sqlite+aiosqlite:///{Path(config.db_path).resolve()}"
    storage = KlineStorage(database_url=db_url)
    await storage.init()
    warmup = bars[: config.start]
    for bar in warmup:
        await storage.store_kline(_to_kline(config.symbol, config.interval, bar))
    print(f"Seeded {len(warmup)} warmup bars into {config.db_path}")

    executor = PaperOrderExecutor(
        initial_balance=config.initial_balance,
        state_file=str(Path(config.state_path)),
        reset=True,
    )
    install_replay_tool_isolation(storage, interval=config.interval)

    # skip_debate via settings BEFORE coordinator construction
    if config.skip_debate:
        from vibe_trading.config.settings import Settings, get_settings, set_settings
        settings = get_settings()
        # set_settings 收 Settings 物件 (非 kwargs dict) — 重建並覆寫 skip_debate
        set_settings(Settings(**{**settings.__dict__, "skip_debate": True}))

    coordinator = TradingCoordinator(
        symbol=config.symbol,
        interval=config.interval,
        storage=storage,
        memory=None,  # skip reflection (avoids live benchmark fetch)
        executor=executor,
        enable_streaming=not config.quiet,
    )
    await coordinator.initialize()

    # Disable insurance (Q15): replay determinism; PM tool path still fills
    async def _noop_insurance(*args, **kwargs) -> None:
        return None
    coordinator._auto_execute_insurance = _noop_insurance  # type: ignore[method-assign, attr-defined]

    # LLM cache wiring
    cache: Optional[LLMCache] = None
    if config.use_cache:
        cache = LLMCache(config.cache_db_path)
        model = getattr(getattr(coordinator, "_tool_context", None), "_model_name", "unknown")
        from vibe_trading.config.settings import get_settings
        model = get_settings().llm_config_name
        for role, agent in _iter_coordinator_agents(coordinator):
            try:
                install_cache_wrapper(agent, role, cache, model)
            except Exception as e:
                logger.warning(f"Cache wrapper failed for {role}: {e}")

    # JSONL writer
    log_path = Path(config.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_handler = RotatingFileHandler(
        str(log_path), maxBytes=100 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    jsonl_handler.setFormatter(logging.Formatter("%(message)s"))
    jsonl_logger = logging.getLogger("replay.jsonl")
    jsonl_logger.setLevel(logging.INFO)
    jsonl_logger.propagate = False
    jsonl_logger.addHandler(jsonl_handler)

    records: List[ReplayRecord] = []
    t0 = time.time()
    for i, bar in enumerate(replay):
        open_ms, o, h, l, c, v = bar
        await storage.store_kline(_to_kline(config.symbol, config.interval, bar))  # BEFORE decide
        executor.update_price(config.symbol, float(c))
        # Phase 2.3: 永續資金費率結算 (三結算點去重)
        try:
            executor.settle_funding(config.symbol, int(open_ms), float(c))
        except Exception as e:
            logger.warning(f"Funding settlement failed: {e}")
        balance, positions = await _account_state(executor)

        bar_t0 = time.time()
        decision = await coordinator.analyze_and_decide(
            current_price=float(c),
            account_balance=balance,
            current_positions=positions,
            bar_open_time_ms=int(open_ms),
        )
        elapsed = time.time() - bar_t0

        balance2, positions2 = await _account_state(executor)
        rec = {
            "symbol": config.symbol,
            "interval": config.interval,
            "bar_open_ms": int(open_ms),
            "bar_close": float(c),
            "decision": decision.decision,
            "rationale": decision.rationale[:500],
            "rationale_full": decision.rationale,
            "confidence": getattr(decision, "confidence", None),
            "elapsed_s": round(elapsed, 1),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "account": {
                "balance": balance2,
                "positions": positions2,
                "equity": balance2 + sum(p["unrealized_profit"] for p in positions2),
            },
        }
        jsonl_logger.info(json.dumps(rec, ensure_ascii=False, default=str))
        records.append(ReplayRecord(
            bar_open_ms=int(open_ms),
            bar_close=float(c),
            decision=decision.decision,
            confidence=getattr(decision, "confidence", None),
            elapsed_s=round(elapsed, 1),
            balance=balance2,
            equity=balance2 + sum(p["unrealized_profit"] for p in positions2),
            positions=positions2,
        ))

        if (i + 1) % 8 == 0 or i == len(replay) - 1:
            total = time.time() - t0
            print(f"  bar {i+1}/{len(replay)} @ {datetime.fromtimestamp(open_ms/1000, tz=timezone.utc):%m-%d %H:%M} "
                  f"decision={decision.decision} ({elapsed:.0f}s, total {total:.0f}s)")

    await coordinator.close()
    # Phase 4.3: 方法論指紋 (close 前提取 prompts)
    try:
        from vibe_trading.governance.manifest import manifest_from_coordinator
        manifest = manifest_from_coordinator(coordinator)
        manifest["config"] = {
            "symbol": config.symbol,
            "interval": config.interval,
            "start": config.start,
            "end": config.end,
            "skip_debate": config.skip_debate,
            "use_cache": config.use_cache,
        }
        manifest_path = Path(config.log_path).parent / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"Manifest written: {manifest_path}")
    except Exception as e:
        logger.warning(f"Manifest failed: {e}")
    await storage.close()
    if cache:
        await cache.close()

    # Cost from usage ledger
    llm_cost, llm_calls = 0.0, 0
    try:
        from vibe_trading.monitoring.usage_ledger import UsageLedger
        ledger = UsageLedger(config.usage_db_path)
        summary = await ledger.get_summary(symbol=config.symbol)
        if summary:
            llm_cost = float(summary.total_cost_usd)
            llm_calls = int(summary.total_requests)
    except Exception as e:
        logger.warning(f"Cost summary failed: {e}")

    result = AgentReplayResult(
        symbol=config.symbol,
        interval=config.interval,
        records=records,
        llm_cost_usd=llm_cost,
        llm_calls=llm_calls,
    )
    print("\n=== Agent replay done ===")
    return result


if __name__ == "__main__":
    sys.exit(0)
