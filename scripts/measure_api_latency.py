"""
Measure real API latency for spec §6.2 performance acceptance.

Passively measures the external APIs the live system actually uses:
- Binance REST (klines/ticker — main data source)
- OKX REST (multi-exchange fallback)
- alternative.me F&G (sentiment)

Computes mean / P95 / P99 per source and parallel multi-source aggregation
latency. Run manually (or in CI with network access):

    PYTHONPATH=backend/src python scripts/measure_api_latency.py --samples 30

Exit 0 if all spec §6.2 thresholds hold, 1 otherwise.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx

# spec §6.2 thresholds
API_P95_MAX_MS = 500.0
AGGREGATE_MAX_MS = 1000.0

SOURCES = {
    "binance": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    "okx": "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT",
    "alternative_me": "https://api.alternative.me/fng/?limit=1",
}


async def _measure_once(client: httpx.AsyncClient, url: str) -> float | None:
    try:
        t0 = time.perf_counter()
        r = await client.get(url, timeout=15.0)
        elapsed = (time.perf_counter() - t0) * 1000.0
        if r.status_code != 200:
            return None
        return elapsed
    except Exception:
        return None


async def measure_source(
    name: str, url: str, samples: int, client: httpx.AsyncClient
) -> dict[str, object]:
    latencies: list[float] = []
    for _ in range(samples):
        ms = await _measure_once(client, url)
        if ms is not None:
            latencies.append(ms)
        await asyncio.sleep(0.05)

    if not latencies:
        return {"name": name, "ok": False, "error": "all requests failed"}

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    p99 = latencies[int(len(latencies) * 0.99) - 1]
    return {
        "name": name,
        "ok": True,
        "samples": len(latencies),
        "mean_ms": round(statistics.mean(latencies), 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "passes_500ms": p95 < API_P95_MAX_MS,
    }


async def measure_aggregate(client: httpx.AsyncClient, samples: int) -> dict[str, object]:
    """Parallel fetch of all 3 sources — multi-source aggregation latency."""
    agg_latencies: list[float] = []
    for _ in range(samples):
        t0 = time.perf_counter()
        await asyncio.gather(
            *(_measure_once(client, url) for url in SOURCES.values())
        )
        agg_latencies.append((time.perf_counter() - t0) * 1000.0)
        await asyncio.sleep(0.05)

    agg_latencies.sort()
    p95 = agg_latencies[int(len(agg_latencies) * 0.95) - 1]
    return {
        "samples": len(agg_latencies),
        "mean_ms": round(statistics.mean(agg_latencies), 1),
        "p95_ms": round(p95, 1),
        "passes_1s": p95 < AGGREGATE_MAX_MS,
    }


async def main(samples: int) -> int:
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[
                measure_source(name, url, samples, client)
                for name, url in SOURCES.items()
            ],
            measure_aggregate(client, samples),
        )

    print("=== spec §6.2 API latency measurement ===")
    print(f"{'source':<18} {'n':>3} {'mean':>7} {'p95':>7} {'p99':>7}  <500ms")
    print("-" * 62)
    for r in results[:-1]:
        if not r["ok"]:
            print(f"{r['name']:<18}  FAILED — {r['error']}")
            continue
        print(
            f"{r['name']:<18} {r['samples']:>3} {r['mean_ms']:>6}ms "
            f"{r['p95_ms']:>6}ms {r['p99_ms']:>6}ms  "
            f"{'✅' if r['passes_500ms'] else '❌'}"
        )

    agg = results[-1]
    print("-" * 62)
    print(
        f"aggregate(3src)   {agg['samples']:>3} {agg['mean_ms']:>6}ms "
        f"{agg['p95_ms']:>6}ms     —  {'✅ <1s' if agg['passes_1s'] else '❌ >=1s'}"
    )

    all_pass = all(
        (r.get("ok") and r.get("passes_500ms")) for r in results[:-1]
    ) and agg["passes_1s"]
    print(f"\nRESULT: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.samples)))
