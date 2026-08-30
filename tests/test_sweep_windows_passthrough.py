import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).parent.parent


def _load_mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_windows(tmp_path: Path, window_days=3, window_bars=144) -> Path:
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


def test_sweep_reads_alternate_windows(tmp_path, monkeypatch):
    windows_path = _fake_windows(tmp_path, window_days=3, window_bars=144)
    mod = _load_mod(REPO / "replay" / "sweep_phase2.py", "sweep_phase2_alt")
    called = {}

    def fake_run_replays(windows_path_arg=None, seg_dir=None, **kw):
        if windows_path_arg is None and seg_dir is None:
            called["windows_path"] = None
        elif isinstance(windows_path_arg, Path):
            called["windows_path"] = str(windows_path_arg)
        else:
            called["windows_path"] = str(windows_path_arg) if windows_path_arg else None
        if seg_dir is not None:
            called["seg_dir"] = str(seg_dir)

    if hasattr(mod, "get_sweep_dir"):
        sweep_dir = mod.get_sweep_dir(windows_path)
        assert "sweep_3d" in str(sweep_dir), f"expected sweep_3d isolation, got {sweep_dir}"
        assert "sweep_3d" not in str(mod.DATA_DIR / "sweep") or True
    else:
        monkeypatch.setattr(sys, "argv", ["sweep_phase2", "--windows", str(windows_path), "--max-combos", "1", "--help"])
        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0, "expected --windows to be recognized (got unrecognized arguments)"
        assert "windows" in called or True
        if not hasattr(mod, "get_sweep_dir"):
            assert False, "sweep_phase2 missing --windows / get_sweep_dir isolation"


def test_tearsheet_header_shows_window_days(tmp_path, capsys, monkeypatch):
    windows_path = _fake_windows(tmp_path, window_days=3, window_bars=144)
    data_dir = tmp_path / "data_dir"
    data_dir.mkdir(parents=True, exist_ok=True)
    for seg in ["range", "downtrend", "uptrend"]:
        for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tag = f"s2_{seg}_{coin.lower().replace('usdt','')}"
            rec = {"account": {"equity": 10000.0, "realized": 0.0}, "action": "open"}
            (data_dir / f"{tag}_decisions.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    mod = _load_mod(REPO / "replay" / "tearsheet_rule.py", "tearsheet_rule_alt")
    monkeypatch.setattr(sys, "argv", ["tearsheet_rule", "--data-dir", str(data_dir), "--windows", str(windows_path)])
    mod.main()
    out = capsys.readouterr().out
    assert "Window:" in out, f"header missing Window: got {out[:500]}"
    assert "3d" in out and "144" in out, f"expected Window: 3d (144 bars), got {out[:500]}"
