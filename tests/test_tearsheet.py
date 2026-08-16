import pytest
"""Tests for tearsheet (Phase 5 — 規格書 §7.2)."""
import json
from pathlib import Path

from vibe_trading.replay.tearsheet import build_tearsheet, format_tearsheet


def _rec(bar_ms, equity, decision="HOLD", balance=None, positions=None, rationale="", price=100.0):
    return {
        "symbol": "BTCUSDT", "interval": "30m",
        "bar_open_ms": bar_ms, "bar_close": price,
        "decision": decision, "rationale": rationale, "confidence": 0.5,
        "elapsed_s": 1.0, "ts": "t",
        "account": {"balance": balance if balance is not None else equity,
                    "equity": equity,
                    "positions": positions or []},
    }


def _write(path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                    encoding="utf-8")


class TestBuildTearsheet:
    def test_empty(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        d = build_tearsheet(str(p))
        assert d["bars"] == 0

    def test_basic_metrics(self, tmp_path):
        # 3 bars: 10000 → 10100 → 9900 (回撤後回升)
        base = 1784876400000
        records = [
            _rec(base, 10000.0, "BUY"),
            _rec(base + 1800000, 10100.0, "BUY"),
            _rec(base + 3600000, 9900.0, "SELL", rationale="賣出"),
        ]
        p = tmp_path / "d.jsonl"
        _write(p, records)
        d = build_tearsheet(str(p))
        assert d["bars"] == 3
        assert d["total_pnl"] == pytest.approx(-100.0)  # 10000 → 9900
        assert d["max_drawdown_pct"] > 0  # 10100 → 9900 回撤
        assert d["decision_dist"]["BUY"] == 2
        assert d["decision_dist"]["SELL"] == 1
        assert d["short_ratio"] == pytest.approx(33.3, abs=0.1)

    def test_monthly_returns(self, tmp_path):
        import datetime
        # 跨月: 07-31 與 08-01
        ms_jul = int(datetime.datetime(2026, 7, 31, 12, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        ms_aug = int(datetime.datetime(2026, 8, 1, 12, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        records = [
            _rec(ms_jul, 10000.0, "HOLD"),
            _rec(ms_aug, 10050.0, "HOLD"),
        ]
        p = tmp_path / "m.jsonl"
        _write(p, records)
        d = build_tearsheet(str(p))
        months = [m["month"] for m in d["monthly_returns"]]
        assert "2026-07" in months and "2026-08" in months

    def test_drawdown_episodes(self, tmp_path):
        base = 1784876400000
        # 10000 → 10500 → 9800 → 10100: 一個大回撤
        records = [
            _rec(base, 10000.0),
            _rec(base + 1800000, 10500.0),
            _rec(base + 3600000, 9800.0),
            _rec(base + 5400000, 10100.0),
        ]
        p = tmp_path / "dd.jsonl"
        _write(p, records)
        d = build_tearsheet(str(p), top_n_drawdowns=3)
        assert len(d["drawdown_episodes"]) >= 1
        ep = d["drawdown_episodes"][0]
        assert ep["depth_pct"] > 5  # 10500→9800 = 6.7%
        assert ep["recovery_bars"] > 0

    def test_fallback_detection(self, tmp_path):
        base = 1784876400000
        records = [
            _rec(base, 10000.0, "WEAK BUY",
                 rationale="情绪面、risk表现强劲，因此建议WEAK_BUY"),
            _rec(base + 1800000, 10000.0, "BUY", rationale="正常決策"),
        ]
        p = tmp_path / "f.jsonl"
        _write(p, records)
        d = build_tearsheet(str(p))
        assert d["fallback_count"] == 1
        assert d["fallback_rate"] == pytest.approx(50.0)


class TestFormat:
    def test_format_contains_sections(self, tmp_path):
        base = 1784876400000
        records = [
            _rec(base, 10000.0, "BUY"),
            _rec(base + 1800000, 10050.0, "HOLD"),
        ]
        p = tmp_path / "f.jsonl"
        _write(p, records)
        text = format_tearsheet(build_tearsheet(str(p)))
        assert "Tearsheet" in text
        assert "Total P&L" in text
        assert "Monthly Returns" in text

    def test_format_empty(self):
        assert "無資料" in format_tearsheet({"bars": 0})


class TestShadow:
    def test_shadow_counterfactual(self, tmp_path):
        base = 1784876400000
        # 下跌行情: 100 → 99 → 98 → 97 → 96 (每 bar -1%)
        records = []
        for i in range(8):
            px = 100.0 - i
            records.append(_rec(base + i * 1800000, 10000.0 - i * 50,
                                decision="HOLD" if i < 4 else "BUY",
                                balance=10000.0 - i * 50, price=px))
        p = tmp_path / "s.jsonl"
        _write(p, records)
        d = build_tearsheet(str(p))
        shadow = d["shadow"]
        assert shadow["horizon_bars"] == 4
        # 下跌市: 無腦做空收益 > 0, 無腦做多 < 0
        assert shadow["always_short_pnl"] > 0
        assert shadow["always_long_pnl"] < 0
        # 實際 (前 4 bar HOLD + 後 BUY) 應不如無腦做空
        assert shadow["actual_pnl"] < shadow["always_short_pnl"]
        # HOLD 反事實做空 > 0
        assert shadow["hold_short_counterfactual"] > 0
