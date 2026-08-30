import importlib.util
import json
import sys
import subprocess
from pathlib import Path

REPO = Path(__file__).parent.parent


def _load_mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_decisions(path: Path, deltas):
    initial = 10000.0
    realized = 0.0
    equity = initial
    recs = []
    for d in deltas:
        realized += d
        equity += d
        recs.append({"account": {"equity": equity, "realized": realized}, "action": "exit" if d != 0 else "hold"})
    path.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")


def _fake_windows(tmp_path: Path, window_days=7, window_bars=336):
    p = tmp_path / f"windows_{window_days}d.json"
    data = {
        "segments": [
            {"name": "range", "start_ts": 1000, "end_ts": 2000, "btc_ret_pct": 0.0, "btc_max_dd_pct": 1.0},
            {"name": "downtrend", "start_ts": 3000, "end_ts": 4000, "btc_ret_pct": -1.0, "btc_max_dd_pct": 2.0},
            {"name": "uptrend", "start_ts": 5000, "end_ts": 6000, "btc_ret_pct": 1.0, "btc_max_dd_pct": 1.0},
        ],
        "coins": {
            "BTCUSDT": {"range": {"start": 0, "end": 10}, "downtrend": {"start": 0, "end": 10}, "uptrend": {"start": 0, "end": 10}},
            "ETHUSDT": {"range": {"start": 0, "end": 10}, "downtrend": {"start": 0, "end": 10}, "uptrend": {"start": 0, "end": 10}},
            "SOLUSDT": {"range": {"start": 0, "end": 10}, "downtrend": {"start": 0, "end": 10}, "uptrend": {"start": 0, "end": 10}},
        },
        "files": {
            "BTCUSDT": str(tmp_path / "bars_btc.json"),
            "ETHUSDT": str(tmp_path / "bars_eth.json"),
            "SOLUSDT": str(tmp_path / "bars_sol.json"),
        },
        "params": {"window_days": window_days, "window_bars": window_bars, "warmup_bars": 400, "separation_bars": window_bars + 4},
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    for k in data["files"].values():
        Path(k).write_text("[]", encoding="utf-8")
    return p


def test_fee_bps_reduces_pf(tmp_path, monkeypatch):
    windows_path = _fake_windows(tmp_path, window_days=7, window_bars=10)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    deltas = [100, -50, 80, -40, 60]
    for seg in ["range", "downtrend", "uptrend"]:
        for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tag = f"s2_{seg}_{coin.lower().replace('usdt','')}"
            realized = 0
            equity = 10000
            lines = []
            for d in deltas:
                realized += d
                equity += d
                lines.append(json.dumps({"account": {"equity": equity, "realized": realized}, "action": "exit"}))
            (data_dir / f"{tag}_decisions.jsonl").write_text("\n".join(lines), encoding="utf-8")
    proc0 = subprocess.run([sys.executable, str(REPO / "replay" / "tearsheet_rule.py"), "--data-dir", str(data_dir), "--windows", str(windows_path), "--fee-bps", "0", "--json"], capture_output=True, text=True)
    assert proc0.returncode == 0, proc0.stderr
    j0 = json.loads(proc0.stdout.strip().splitlines()[-1])
    proc8 = subprocess.run([sys.executable, str(REPO / "replay" / "tearsheet_rule.py"), "--data-dir", str(data_dir), "--windows", str(windows_path), "--fee-bps", "8", "--json"], capture_output=True, text=True)
    assert proc8.returncode == 0, proc8.stderr
    j8 = json.loads(proc8.stdout.strip().splitlines()[-1])
    pf0 = list(j0["segments"].values())[0]["pf"]
    pf8 = list(j8["segments"].values())[0]["pf"]
    assert pf0 is not None and pf8 is not None
    assert pf8 < pf0, f"fee should reduce pf: 0bps {pf0} vs 8bps {pf8}"
    assert j8.get("fee_bps") == 8
    assert j0.get("fee_bps") == 0


def test_per_coin_isolation(tmp_path, monkeypatch):
    windows_path = _fake_windows(tmp_path, window_days=7, window_bars=10)
    data_dir = tmp_path / "data2"
    data_dir.mkdir()
    for seg in ["range", "downtrend", "uptrend"]:
        for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tag = f"s2_{seg}_{coin.lower().replace('usdt','')}"
            val = 200 if coin == "BTCUSDT" else (-30 if coin == "ETHUSDT" else 50)
            lines = []
            realized = 0
            equity = 10000
            deltas = [val, -20, 30] if coin == "BTCUSDT" else [ -10, -20, 5]
            for d in deltas:
                realized += d
                equity += d
                lines.append(json.dumps({"account": {"equity": equity, "realized": realized}, "action": "exit"}))
            (data_dir / f"{tag}_decisions.jsonl").write_text("\n".join(lines), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "replay" / "tearsheet_rule.py"), "--data-dir", str(data_dir), "--windows", str(windows_path), "--json"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    j = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "per_coin" in j, f"per_coin missing in {j.keys()}"
    assert "BTCUSDT" in j["per_coin"]
    btc_pf = j["per_coin"]["BTCUSDT"]["pf"]
    eth_pf = j["per_coin"]["ETHUSDT"]["pf"]
    assert btc_pf != eth_pf


def test_header_window_and_fee(tmp_path, capsys, monkeypatch):
    windows_path = _fake_windows(tmp_path, window_days=7, window_bars=336)
    data_dir = tmp_path / "data3"
    data_dir.mkdir()
    for seg in ["range", "downtrend", "uptrend"]:
        for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tag = f"s2_{seg}_{coin.lower().replace('usdt','')}"
            (data_dir / f"{tag}_decisions.jsonl").write_text(json.dumps({"account": {"equity": 10000, "realized": 0}, "action": "hold"}) + "\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "replay" / "tearsheet_rule.py"), "--data-dir", str(data_dir), "--windows", str(windows_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "Window:" in out
    assert "7d" in out
    assert "fee" in out.lower() and "8bps" in out.lower() or "8" in out
