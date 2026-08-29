"""Phase-2 parameter sweep over RuleEngineConfig (env-var driven, 不加新功能).

调因子/仓位 only (收敛计划 §4: 不过门槛 → 修策略). Sweeps entry_threshold ×
sl/tp ATR multiples via RULE_* env (RuleEngineConfig.from_env reads them, and
replay_rule_engine constructs config via from_env). For each combo it runs the
9 (segment, coin) replays into a temp data dir and aggregates with
tearsheet_rule.py --json.

Usage: python replay/sweep_phase2.py [--combos N]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

REPLAY_DIR = Path(__file__).resolve().parent
DATA_DIR = REPLAY_DIR / "data"
SWEEP_DIR = DATA_DIR / "sweep"

# search space (策略参数, 非新功能)
ENTRY_THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7]
SL_TP = [(1.5, 2.5), (2.0, 3.0), (2.0, 4.0), (3.0, 4.5)]


def run_replays(seg_dir: Path) -> None:
    """Re-run 9 segment/coin replays into seg_dir (s2_ prefixed artifacts)."""
    windows = json.loads((DATA_DIR / "windows.json").read_text(encoding="utf-8"))
    for seg in ["range", "downtrend", "uptrend"]:
        for coin, bars_path in windows["files"].items():
            idx = windows["coins"][coin][seg]
            tag = f"s2_{seg}_{coin.lower().replace('usdt', '')}"
            cmd = [
                sys.executable, str(REPLAY_DIR / "replay_rule_engine.py"),
                "--symbol", coin, "--bars", bars_path,
                "--start", str(idx["start"]), "--end", str(idx["end"]),
                "--inject-regime", "RISK_ON",
                "--log", str(seg_dir / f"{tag}_decisions.jsonl"),
                "--db", str(seg_dir / f"{tag}.db"),
                "--state", str(seg_dir / f"{tag}_state.json"),
                "--macro-db", str(seg_dir / f"{tag}_macro.db"),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                print("replay failed:", " ".join(cmd), proc.stderr[-300:], file=sys.stderr)
                sys.exit(1)


def tearsheet(seg_dir: Path) -> dict:
    cmd = [sys.executable, str(REPLAY_DIR / "tearsheet_rule.py"),
           "--data-dir", str(seg_dir), "--windows", str(DATA_DIR / "windows.json"), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("tearsheet failed:", proc.stderr[-300:], file=sys.stderr)
        sys.exit(1)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-combos", type=int, default=20)
    args = ap.parse_args()

    combos = list(itertools.product(ENTRY_THRESHOLDS, SL_TP))[: args.max_combos]
    results = []
    for thr, (sl, tp) in combos:
        cdir = SWEEP_DIR / f"thr{thr:g}_sl{sl:g}tp{tp:g}"
        if cdir.exists():
            # resume: skip combos that already produced all 9 segment/coin replays
            done = [p for p in cdir.glob("s2_*_decisions.jsonl") if p.exists()]
            if len(done) >= 9:
                print(f"skip {cdir.name} (already complete, {len(done)} files)")
                continue
        cdir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ,
                   RULE_ENTRY_THRESHOLD=str(thr),
                   RULE_SL_ATR_MULT=str(sl),
                   RULE_TP_ATR_MULT=str(tp))
        # propagate to replay subprocesses via os.environ (run_replays inherits)
        os.environ.update(env)
        run_replays(cdir)
        st = tearsheet(cdir)
        row = {"thr": thr, "sl": sl, "tp": tp, **st}
        results.append(row)
        pfs = {s: (v["pf"] if not v["pf_inf"] else "inf") for s, v in st["segments"].items()}
        print(f"thr={thr:>4} sl={sl:>3} tp={tp:>4}  gate={'PASS' if st['gate_pass'] else 'fail':4} "
              f"PF={pfs} totalDD={st['total_max_dd_pct']:.2f}%")
    results.sort(key=lambda r: (not r["gate_pass"],
                                min((s["pf"] or 9.9) if not s["pf_inf"] else 9.9
                                    for s in r["segments"].values())), reverse=True)
    print("\nTOP:")
    for r in results[:6]:
        print(f"  thr={r['thr']:>4} sl={r['sl']:>3} tp={r['tp']:>4} pass={r['gate_pass']}")


if __name__ == "__main__":
    main()