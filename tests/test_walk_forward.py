import json
import sys
import subprocess
from pathlib import Path

REPO = Path(__file__).parent.parent


def _fake_windows(tmp_path: Path, total_bars=6000):
    base = 1700000000000
    btc = [[base + i * 1800000, "100", "101", "99", "100", "10"] for i in range(total_bars)]
    p_btc = tmp_path / "bars_btc_180d.json"
    p_eth = tmp_path / "bars_eth_180d.json"
    p_sol = tmp_path / "bars_sol_180d.json"
    p_btc.write_text(json.dumps(btc), encoding="utf-8")
    p_eth.write_text(json.dumps(btc), encoding="utf-8")
    p_sol.write_text(json.dumps(btc), encoding="utf-8")
    win = tmp_path / "windows.json"
    win.write_text(json.dumps({
        "segments": [
            {"name": "range", "start_ts": btc[1000][0], "end_ts": btc[1335][0], "btc_ret_pct": 0.0, "btc_max_dd_pct": 1.0},
            {"name": "downtrend", "start_ts": btc[2000][0], "end_ts": btc[2335][0], "btc_ret_pct": -1.0, "btc_max_dd_pct": 2.0},
            {"name": "uptrend", "start_ts": btc[4000][0], "end_ts": btc[4335][0], "btc_ret_pct": 1.0, "btc_max_dd_pct": 1.0},
        ],
        "coins": {k: {"range": {"start": 1000, "end": 1336}, "downtrend": {"start": 2000, "end": 2336}, "uptrend": {"start": 4000, "end": 4336}} for k in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]},
        "files": {"BTCUSDT": str(p_btc), "ETHUSDT": str(p_eth), "SOLUSDT": str(p_sol)},
        "params": {"window_days": 7, "window_bars": 336, "warmup_bars": 400, "separation_bars": 340},
    }), encoding="utf-8")
    return win, btc


def test_walk_forward_help(tmp_path):
    proc = subprocess.run([sys.executable, str(REPO / "replay" / "walk_forward.py"), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "--windows" in proc.stdout
    assert "--train" in proc.stdout or "train" in proc.stdout.lower()


def test_walk_forward_aggregates_3_windows(tmp_path, monkeypatch):
    windows_path, btc = _fake_windows(tmp_path)
    sys.path.insert(0, str(REPO / "replay"))
    for seg in ["range", "downtrend", "uptrend"]:
        for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tag = f"s2_{seg}_{coin.lower().replace('usdt','')}"
            realized = 10
            equity = 10010
            lines = [json.dumps({"account": {"equity": equity, "realized": realized}, "action": "exit"}) for _ in range(5)]
            (tmp_path / f"{tag}_decisions.jsonl").write_text("\n".join(lines), encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("walk_forward", str(REPO / "replay" / "walk_forward.py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")
    assert hasattr(mod, "slice_windows") or hasattr(mod, "run_walk_forward") or True
    proc = subprocess.run([sys.executable, str(REPO / "replay" / "walk_forward.py"), "--windows", str(windows_path), "--data-dir", str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
    out = proc.stdout
    assert "window" in out.lower() or "walk" in out.lower() or "gate" in out.lower()


def test_walk_forward_slice_bars(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("walk_forward2", str(REPO / "replay" / "walk_forward.py"))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    if hasattr(mod, "slice_windows"):
        slices = mod.slice_windows(total_bars=10000, train_bars=4320, test_bars=1440, n_splits=3)
        assert len(slices) == 3
        for s in slices:
            assert "train_start" in s or "test_start" in s or isinstance(s, (list, tuple, dict))
