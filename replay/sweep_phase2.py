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
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPLAY_DIR = Path(__file__).resolve().parent
DATA_DIR = REPLAY_DIR / "data"
SWEEP_DIR = DATA_DIR / "sweep"

ENTRY_THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7]
SL_TP = [(1.5, 2.5), (2.0, 3.0), (2.0, 4.0), (3.0, 4.5)]


def _parse_window_days(windows_path: Path, windows_data: dict | None = None) -> int | None:
    if windows_data is not None:
        wd = windows_data.get("params", {}).get("window_days")
        if wd is not None:
            try:
                return int(wd)
            except Exception:
                pass
    try:
        data = windows_data if windows_data is not None else json.loads(Path(windows_path).read_text(encoding="utf-8"))
        wd = data.get("params", {}).get("window_days")
        if wd is not None:
            try:
                return int(wd)
            except Exception:
                pass
    except Exception:
        pass
    m = re.search(r"windows_(\d+)d", Path(windows_path).name)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None


def get_sweep_dir(windows_path: Path | str) -> Path:
    wd = _parse_window_days(Path(windows_path))
    if wd is not None:
        return DATA_DIR / f"sweep_{wd}d"
    return DATA_DIR / "sweep"


def _windows_fingerprint(windows_path: Path) -> str:
    p = Path(windows_path)
    try:
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    except Exception:
        h = "nohash"
    try:
        mtime = int(p.stat().st_mtime)
    except Exception:
        mtime = 0
    return f"{h}_{mtime}"


def run_replays(seg_dir: Path, windows_path: Path | str | None = None) -> None:
    if windows_path is None:
        windows_path = Path(os.getenv("REPLAY_WINDOWS", str(DATA_DIR / "windows.json")))
    windows_path = Path(windows_path)
    windows = json.loads(windows_path.read_text(encoding="utf-8"))
    for seg in [s["name"] for s in windows["segments"]]:
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


def tearsheet(seg_dir: Path, windows_path: Path | str | None = None) -> dict:
    if windows_path is None:
        windows_path = Path(os.getenv("REPLAY_WINDOWS", str(DATA_DIR / "windows.json")))
    windows_path = Path(windows_path)
    cmd = [sys.executable, str(REPLAY_DIR / "tearsheet_rule.py"),
           "--data-dir", str(seg_dir), "--windows", str(windows_path), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("tearsheet failed:", proc.stderr[-300:], file=sys.stderr)
        sys.exit(1)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default=os.getenv("REPLAY_WINDOWS", str(DATA_DIR / "windows.json")))
    ap.add_argument("--max-combos", type=int, default=20)
    args = ap.parse_args()

    windows_path = Path(args.windows)
    sweep_dir = get_sweep_dir(windows_path)
    fingerprint = _windows_fingerprint(windows_path)

    combos = list(itertools.product(ENTRY_THRESHOLDS, SL_TP))[: args.max_combos]
    results = []
    for thr, (sl, tp) in combos:
        cdir = sweep_dir / f"thr{thr:g}_sl{sl:g}tp{tp:g}"
        if cdir.exists():
            done = [p for p in cdir.glob("s2_*_decisions.jsonl") if p.exists()]
            fp_file = cdir / ".windows_fingerprint"
            fp_match = fp_file.exists() and fp_file.read_text(encoding="utf-8").strip() == fingerprint
            if len(done) >= 9 and fp_match:
                print(f"skip {cdir.name} (already complete, {len(done)} files)")
                continue
        cdir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ,
                   RULE_ENTRY_THRESHOLD=str(thr),
                   RULE_SL_ATR_MULT=str(sl),
                   RULE_TP_ATR_MULT=str(tp))
        os.environ.update(env)
        run_replays(cdir, windows_path)
        st = tearsheet(cdir, windows_path)
        (cdir / ".windows_fingerprint").write_text(fingerprint, encoding="utf-8")
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
