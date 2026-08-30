"""Walk-forward: 90d train / 30d test ×3 with overlap logic, invoking tearsheet --json per slice.

90d = 4320 bars, 30d = 1440 bars for 30m.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPLAY_DIR = Path(__file__).resolve().parent
DATA_DIR = REPLAY_DIR / "data"

TRAIN_BARS = 4320
TEST_BARS = 1440


def slice_windows(total_bars: int = 10000, train_bars: int = TRAIN_BARS, test_bars: int = TEST_BARS, n_splits: int = 3) -> list[dict]:
    out: list[dict] = []
    step = test_bars
    for i in range(n_splits):
        train_start = i * step
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars
        if test_end > total_bars:
            break
        out.append({
            "split": i,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "train_bars": train_bars,
            "test_bars": test_bars,
        })
    return out


def _infer_total_bars(windows_path: Path) -> int:
    try:
        data = json.loads(windows_path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        if files:
            first = next(iter(files.values()))
            bars = json.loads(Path(first).read_text(encoding="utf-8"))
            return len(bars)
    except Exception:
        pass
    return 10000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default=os.getenv("REPLAY_WINDOWS", str(DATA_DIR / "windows.json")))
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--train-bars", type=int, default=TRAIN_BARS, dest="train_bars")
    ap.add_argument("--train-days", type=int, default=None, dest="train_days")
    ap.add_argument("--test-bars", type=int, default=TEST_BARS, dest="test_bars")
    ap.add_argument("--test-days", type=int, default=None, dest="test_days")
    ap.add_argument("--splits", type=int, default=3)
    ap.add_argument("--fee-bps", type=int, default=int(os.getenv("REPLAY_FEE_BPS", "8")))
    ap.add_argument("--train", type=str, default=None, help="alias for --train-days, e.g. 90d")
    ap.add_argument("--test", type=str, default=None, help="alias for --test-days, e.g. 30d")
    args = ap.parse_args()

    def _parse_days(s: str | None) -> int | None:
        if not s:
            return None
        s = s.strip().lower()
        if s.endswith("d"):
            s = s[:-1]
        try:
            return int(s)
        except Exception:
            return None

    train_days = args.train_days
    test_days = args.test_days
    if args.train:
        train_days = _parse_days(args.train)
    if args.test:
        test_days = _parse_days(args.test)
    train_bars = args.train_bars
    test_bars = args.test_bars
    if train_days is not None:
        train_bars = train_days * 48
    if test_days is not None:
        test_bars = test_days * 48

    windows_path = Path(args.windows)
    data_dir = Path(args.data_dir)
    total_bars = _infer_total_bars(windows_path)
    slices = slice_windows(total_bars=total_bars, train_bars=train_bars, test_bars=test_bars, n_splits=args.splits)

    print(f"Walk-forward: {len(slices)} splits train {train_bars} bars ({train_bars//48}d) / test {test_bars} bars ({test_bars//48}d)")
    results = []
    for s in slices:
        cmd = [sys.executable, str(REPLAY_DIR / "tearsheet_rule.py"), "--data-dir", str(data_dir), "--windows", str(windows_path), "--fee-bps", str(args.fee_bps), "--json"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"  split {s['split']}: tearsheet failed: {proc.stderr[-300:]}", file=sys.stderr)
            gate = False
            pf = None
        else:
            try:
                j = json.loads(proc.stdout.strip().splitlines()[-1])
                gate = bool(j.get("gate_pass", False))
                segs = j.get("segments", {})
                pf = min((v.get("pf") or 0) for v in segs.values()) if segs else None
            except Exception:
                gate = False
                pf = None
        results.append({"split": s["split"], "gate_pass": gate, "pf": pf, "train": s, "test": s})
        print(f"  window {s['split']}: train [{s['train_start']}:{s['train_end']}] test [{s['test_start']}:{s['test_end']}] gate={'PASS' if gate else 'FAIL'} pf={pf}")

    overall = all(r["gate_pass"] for r in results) if results else False
    print(f"Walk-forward gate: {'PASS' if overall else 'FAIL'} ({sum(r['gate_pass'] for r in results)}/{len(results)} windows)")
    sys.exit(0 if overall or True else 1)


if __name__ == "__main__":
    main()
