import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location("select_windows", Path(__file__).parent.parent / "replay" / "select_windows.py")
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["select_windows"] = _mod
_spec.loader.exec_module(_mod)
sw = _mod


def _fake_bars(n=5000, start_ts=1700000000000):
    bars = []
    for i in range(n):
        ts = start_ts + i * 30 * 60 * 1000
        close = 100.0 + (i * 0.02) + (10 if i % 700 < 350 else -10) * 0.5
        if close <= 0:
            close = 10.0
        bars.append([ts, close, close + 1, close - 1, close, 1000.0])
    return bars


def test_window_bars_derived_from_days(tmp_path, monkeypatch):
    monkeypatch.delenv("REPLAY_WINDOW_BARS", raising=False)
    monkeypatch.delenv("REPLAY_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("REPLAY_WARMUP_BARS", raising=False)
    monkeypatch.delenv("REPLAY_SEPARATION_BARS", raising=False)
    out = tmp_path / "windows_3d.json"
    fake = _fake_bars()
    with patch.object(sw, "_load_bars", return_value=fake):
        monkeypatch.setattr(sys, "argv", ["select_windows", "--window-days", "3", "--out", str(out)])
        sw.main()
    data = json.loads(out.read_text())
    assert data["params"]["window_bars"] == 144
    assert data["params"]["window_days"] == 3
    assert len(data["segments"]) == 3
    separation = data["params"]["separation_bars"]
    assert separation >= 144 + 4


def test_env_fallback_and_cli_precedence(tmp_path, monkeypatch):
    fake = _fake_bars()
    monkeypatch.delenv("REPLAY_WINDOW_BARS", raising=False)
    monkeypatch.delenv("REPLAY_WARMUP_BARS", raising=False)
    monkeypatch.delenv("REPLAY_SEPARATION_BARS", raising=False)

    monkeypatch.setenv("REPLAY_WINDOW_DAYS", "5")
    out1 = tmp_path / "w_env.json"
    with patch.object(sw, "_load_bars", return_value=fake):
        monkeypatch.setattr(sys, "argv", ["select_windows", "--out", str(out1)])
        sw.main()
    data1 = json.loads(out1.read_text())
    assert data1["params"]["window_bars"] == 240

    out2 = tmp_path / "w_cli.json"
    with patch.object(sw, "_load_bars", return_value=fake):
        monkeypatch.setattr(sys, "argv", ["select_windows", "--window-bars", "100", "--out", str(out2)])
        sw.main()
    data2 = json.loads(out2.read_text())
    assert data2["params"]["window_bars"] == 100

    monkeypatch.delenv("REPLAY_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("REPLAY_WINDOW_BARS", raising=False)


def test_default_compatible_has_same_336(tmp_path, monkeypatch):
    monkeypatch.delenv("REPLAY_WINDOW_BARS", raising=False)
    monkeypatch.delenv("REPLAY_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("REPLAY_WARMUP_BARS", raising=False)
    monkeypatch.delenv("REPLAY_SEPARATION_BARS", raising=False)
    out = tmp_path / "windows_default.json"
    fake = _fake_bars()
    with patch.object(sw, "_load_bars", return_value=fake):
        monkeypatch.setattr(sys, "argv", ["select_windows", "--out", str(out)])
        sw.main()
    data = json.loads(out.read_text())
    assert data["params"]["window_bars"] == 336
    assert data["params"]["warmup_bars"] == 400
    assert data["params"]["separation_bars"] == 340
    assert len(data["segments"]) == 3
    assert set(data["files"].keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
