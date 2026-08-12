"""Large-scale performance benchmark: BM25 vs FTS5"""
import time
import tempfile
from pathlib import Path

from vibe_trading.memory.memory import BM25Memory
from vibe_trading.memory.fts5_memory import FTS5Memory
from vibe_trading.memory.hybrid_memory import HybridMemory
from vibe_trading.memory.compression import ContextCompressor
from vibe_trading.memory.monitor import get_memory_monitor


def generate_test_data(count: int):
    """Generate realistic test memories"""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
               "ADAUSDT", "DOGEUSDT", "DOTUSDT", "AVAXUSDT", "MATICUSDT"]
    patterns = [
        "breakout above resistance with high volume",
        "breakdown below support on heavy selling",
        "consolidation pattern forming triangle",
        "double top reversal signal detected",
        "bullish engulfing candle at support",
        "bearish divergence on RSI indicator",
        "golden cross moving average signal",
        "death cross moving average signal",
        "oversold bounce from key level",
        "overbought rejection at resistance",
    ]
    advices = [
        "Enter long position with 2% risk, stop loss below support",
        "Enter short position with 1.5% risk, stop loss above resistance",
        "Wait for breakout confirmation before entering",
        "Take profit at next resistance level",
        "Scale in gradually over 3 entries",
        "Use tight stop loss due to high volatility",
        "Hold position until trend reversal confirmed",
        "Exit position and wait for clearer signal",
    ]

    data = []
    for i in range(count):
        symbol = symbols[i % len(symbols)]
        pattern = patterns[i % len(patterns)]
        advice = advices[i % len(advices)]
        pnl = ((i * 7) % 20) - 10  # Range: -10 to +10
        data.append({
            "situation": f"{symbol} {pattern} #{i} with volume spike and momentum shift",
            "advice": f"{advice} #{i} based on technical analysis and market structure",
            "pnl": float(pnl),
            "symbol": symbol,
            "tags": f"{pattern.split()[0]},{symbol.lower().replace('usdt','')}",
        })
    return data


def benchmark_bm25(data: list, queries: list):
    """Benchmark BM25 search performance"""
    memory = BM25Memory()

    # Indexing
    start = time.time()
    for item in data:
        memory.add_memory(
            situation=item["situation"],
            advice=item["advice"],
            pnl=item["pnl"],
            symbol=item["symbol"],
        )
    index_time = time.time() - start

    # Searching
    start = time.time()
    for query in queries:
        memory.retrieve_relevant(query, top_k=5)
    search_time = time.time() - start

    return {
        "count": len(data),
        "index_time": index_time,
        "search_time": search_time,
        "avg_search_ms": (search_time / len(queries)) * 1000,
    }


def benchmark_fts5(data: list, queries: list):
    """Benchmark FTS5 search performance"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "bench_fts5.db")
        memory = FTS5Memory(db_path)

        # Indexing
        start = time.time()
        for item in data:
            memory.add_memory(
                situation=item["situation"],
                advice=item["advice"],
                pnl=item["pnl"],
                symbol=item["symbol"],
                tags=item["tags"],
            )
        index_time = time.time() - start

        # Searching
        start = time.time()
        for query in queries:
            memory.search(query, top_k=5)
        search_time = time.time() - start

    return {
        "count": len(data),
        "index_time": index_time,
        "search_time": search_time,
        "avg_search_ms": (search_time / len(queries)) * 1000,
    }


def benchmark_hybrid(data: list, queries: list):
    """Benchmark HybridMemory (FTS5 primary, BM25 fallback)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkl_path = str(Path(tmpdir) / "bench.pkl")
        fts5_path = str(Path(tmpdir) / "bench_fts5.db")
        memory = HybridMemory(storage_path=pkl_path, fts5_db_path=fts5_path)

        # Indexing
        start = time.time()
        for item in data:
            memory.add_memory(
                situation=item["situation"],
                advice=item["advice"],
                pnl=item["pnl"],
                symbol=item["symbol"],
            )
        index_time = time.time() - start

        # Searching (uses FTS5)
        start = time.time()
        for query in queries:
            memory.retrieve_relevant(query, top_k=5)
        search_time = time.time() - start

    return {
        "count": len(data),
        "index_time": index_time,
        "search_time": search_time,
        "avg_search_ms": (search_time / len(queries)) * 1000,
    }


def benchmark_compression(data: list):
    """Benchmark compression at different scales"""
    from vibe_trading.memory.fts5_memory import FTS5Entry

    compressor = ContextCompressor()

    results = []
    for scale in [10, 50, 100, 200]:
        memories = [
            FTS5Entry(
                id=i,
                situation=f"Long situation description for memory {i} " * 3,
                advice=f"Detailed trading advice for memory {i} " * 3,
                pnl=float((i % 10) - 5),
                symbol="BTCUSDT",
            )
            for i in range(min(scale, len(data)))
        ]

        start = time.time()
        compressed = compressor.compress_memories(memories, target_tokens=500)
        elapsed = time.time() - start

        original_tokens = len(" ".join([m.situation + " " + m.advice for m in memories]).split())
        compressed_tokens = len(compressed.split())

        results.append({
            "scale": scale,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "ratio": compressed_tokens / original_tokens if original_tokens > 0 else 1.0,
            "time_ms": elapsed * 1000,
        })

    return results


def run_benchmarks():
    """Run all benchmarks"""
    queries = [
        "BTC breakout",
        "ETH breakdown",
        "moving average cross",
        "RSI divergence",
        "volume spike",
        "support resistance",
        "trend reversal",
        "consolidation pattern",
        "stop loss take profit",
        "risk management",
    ]

    print("=" * 70)
    print("MEMORY SYSTEM PERFORMANCE BENCHMARK")
    print("=" * 70)

    for count in [100, 1000, 5000, 10000]:
        print(f"\n{'─' * 70}")
        print(f"Dataset size: {count:,} memories")
        print(f"{'─' * 70}")

        data = generate_test_data(count)

        bm25 = benchmark_bm25(data, queries)
        fts5 = benchmark_fts5(data, queries)
        hybrid = benchmark_hybrid(data, queries)

        print(f"\n{'Metric':<25} {'BM25':>15} {'FTS5':>15} {'Hybrid':>15} {'Speedup':>10}")
        print(f"{'─' * 80}")

        idx_speedup = bm25["index_time"] / fts5["index_time"] if fts5["index_time"] > 0 else 0
        print(f"{'Index time (s)':<25} {bm25['index_time']:>15.3f} {fts5['index_time']:>15.3f} {hybrid['index_time']:>15.3f} {idx_speedup:>9.1f}x")

        srch_speedup = bm25["avg_search_ms"] / fts5["avg_search_ms"] if fts5["avg_search_ms"] > 0 else 0
        print(f"{'Avg search (ms)':<25} {bm25['avg_search_ms']:>15.2f} {fts5['avg_search_ms']:>15.2f} {hybrid['avg_search_ms']:>15.2f} {srch_speedup:>9.1f}x")

        print(f"{'Total search (s)':<25} {bm25['search_time']:>15.3f} {fts5['search_time']:>15.3f} {hybrid['search_time']:>15.3f}")

    # Compression benchmark
    print(f"\n{'─' * 70}")
    print("COMPRESSION BENCHMARK")
    print(f"{'─' * 70}")

    data = generate_test_data(200)
    comp_results = benchmark_compression(data)

    print(f"\n{'Scale':>8} {'Original':>12} {'Compressed':>12} {'Ratio':>10} {'Time (ms)':>12}")
    print(f"{'─' * 60}")
    for r in comp_results:
        print(f"{r['scale']:>8} {r['original_tokens']:>12} {r['compressed_tokens']:>12} {r['ratio']:>9.1%} {r['time_ms']:>11.2f}")

    # Monitor stats
    print(f"\n{'─' * 70}")
    print("MONITOR STATISTICS")
    print(f"{'─' * 70}")

    monitor = get_memory_monitor()
    stats = monitor.get_comprehensive_stats()

    print(f"\nSearch stats:")
    print(f"  Total searches: {stats['search']['total_searches']}")
    print(f"  FTS5 avg latency: {stats['fts5_search']['avg_latency_ms']:.2f}ms")
    print(f"  BM25 avg latency: {stats['bm25_search']['avg_latency_ms']:.2f}ms")

    print(f"\nCompression stats:")
    print(f"  Total compressions: {stats['compression']['total_compressions']}")
    print(f"  Avg compression ratio: {stats['compression']['avg_compression_ratio']:.1%}")

    print(f"\n{'=' * 70}")
    print("BENCHMARK COMPLETE")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    run_benchmarks()
