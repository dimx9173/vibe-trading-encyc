"""Phase-2 3x168h segment backtest driver.

For each (segment, coin) from replay/data/windows.json, run the pure rule-engine
replay over the selected 336-bar window with Warmup (< window.start) bars seeded
for indicator warmup (no look-ahead). The LLM regime gate is NOT part of the
backtest loop (收敛计划 §4: "LLM regime gate 不进回测回路"); all segments inject
RISK_ON so the strategy can express LONG (uptrend) and SHORT (downtrend) alpha;
regime 命中率 is validated post-hoc by the window labels (btc_ret sign/level).

Outputs per (segment, coin): replay/data/s2_{seg}_{coin}_decisions.jsonl (+ .db/.state/.audit)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPLAY_DIR = Path(__file__).resolve().parent
DATA_DIR = REPLAY_DIR / "data"


def main() -> None:
    windows = json.loads((DATA_DIR / "windows.json").read_text(encoding="utf-8"))
    segments = [s["name"] for s in windows["segments"]]
    coins = windows["files"]  # {coin: bars_path}
    runs = []
    for seg in segments:
        for coin, bars_path in coins.items():
            idx = windows["coins"][coin][seg]
            tag = f"s2_{seg}_{coin.lower().replace('usdt', '')}"
            runs.append({
                "symbol": coin,
                "bars": bars_path,
                "start": idx["start"],
                "end": idx["end"],
                "inject": "RISK_ON",
                "log": str(DATA_DIR / f"{tag}_decisions.jsonl"),
                "db": str(DATA_DIR / f"{tag}.db"),
                "state": str(DATA_DIR / f"{tag}_state.json"),
                "macro_db": str(DATA_DIR / f"{tag}_macro.db"),
            })

    for r in runs:
        cmd = [
            sys.executable, str(REPLAY_DIR / "replay_rule_engine.py"),
            "--symbol", r["symbol"],
            "--bars", r["bars"],
            "--start", str(r["start"]),
            "--end", str(r["end"]),
            "--inject-regime", r["inject"],
            "--log", r["log"],
            "--db", r["db"],
            "--state", r["state"],
            "--macro-db", r["macro_db"],
        ]
        print(f"== {r['symbol']} [{r['start']}:{r['end']}] -> {r['log']}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        tail = (proc.stdout or "").strip().splitlines()
        if tail:
            print("   " + tail[-1])
        if proc.returncode != 0:
            print("   STDERR:", (proc.stderr or "")[-500:], file=sys.stderr)
            sys.exit(proc.returncode)


if __name__ == "__main__":
    main()