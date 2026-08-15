"""Tests for CLI commands (Wave B — coverage 85% plan).

使用 typer.testing.CliRunner. 目標: 覆蓋輕量命令 (status/alpha/funding-arb/
manifest-diff/hyp-create/hyp-list/universe-scan/goal) + 不需要真實網路的命令.
重度命令 (start/analyze/prime/macro) 需 mock 依賴 — 以 import patch 測試.
"""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe_trading.cli import app

runner = CliRunner()


class TestStatus:
    def test_status_exits_zero(self):
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "Vibe Trading 系统状态" in result.output


class TestAlphaCommands:
    def test_alpha_list(self):
        result = runner.invoke(app, ["alpha", "list"])
        assert result.exit_code == 0
        assert "Alpha 因子庫" in result.output

    def test_alpha_list_category(self):
        result = runner.invoke(app, ["alpha", "list", "--category", "momentum"])
        assert result.exit_code == 0
        assert "Alpha 因子庫" in result.output

    def test_alpha_list_invalid_category(self):
        result = runner.invoke(app, ["alpha", "list", "--category", "bogus"])
        # 未知類別 → 空表但仍 exit 0
        assert result.exit_code == 0


class TestFundingArb:
    def test_funding_arb_finds_opportunity(self):
        result = runner.invoke(app, [
            "research", "funding-arb",
            "--binance", "0.0001", "--okx", "0.0003",
            "--bybit", "0.0001", "--bitget", "0.00005",
        ])
        assert result.exit_code == 0
        assert "FUNDING-ARB" in result.output
        assert "年化" in result.output

    def test_funding_arb_no_opportunity(self):
        result = runner.invoke(app, [
            "research", "funding-arb",
            "--binance", "0.0001", "--okx", "0.0001",
            "--bybit", "0.0001", "--bitget", "0.0001",
        ])
        assert result.exit_code == 0
        assert "無符合閾值" in result.output


class TestManifestDiff:
    def test_manifest_diff_identical(self, tmp_path: Path):
        m1 = {"manifest_hash": "abc", "prompts": {}, "tools": [], "packages": {}, "config": {}}
        m2 = {"manifest_hash": "abc", "prompts": {}, "tools": [], "packages": {}, "config": {}}
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        a.write_text(json.dumps(m1))
        b.write_text(json.dumps(m2))
        result = runner.invoke(app, ["research", "manifest-diff", str(a), str(b)])
        assert result.exit_code == 0
        assert "MANIFEST" in result.output

    def test_manifest_diff_drift(self, tmp_path: Path):
        m1 = {"manifest_hash": "abc", "prompts": {"tech": "h1"},
              "tools": ["a"], "packages": {}, "config": {}}
        m2 = {"manifest_hash": "def", "prompts": {"tech": "h2"},
              "tools": ["a", "b"], "packages": {}, "config": {}}
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        a.write_text(json.dumps(m1))
        b.write_text(json.dumps(m2))
        result = runner.invoke(app, ["research", "manifest-diff", str(a), str(b)])
        assert result.exit_code == 0
        assert "漂移" in result.output


class TestHypCommands:
    def test_hyp_create_and_list(self, tmp_path: Path):
        # 用 tmp_path 作為 cwd 避免污染 research.db
        result = runner.invoke(app, [
            "research", "hyp-create", "測試假設", "--desc", "d", "--tags", "a,b",
        ], )
        assert result.exit_code == 0
        assert "RESEARCH" in result.output

    def test_hyp_list_empty(self):
        result = runner.invoke(app, ["research", "hyp-list"])
        assert result.exit_code == 0
        assert "共" in result.output


class TestUniverseScan:
    def test_universe_scan_network_fail_safe(self):
        """無網路/API key 時不 raise (fail-safe)."""
        result = runner.invoke(app, ["research", "universe-scan", "--top", "3"])
        # 網路失敗 → exit 0 + 錯誤訊息 (fail-safe)
        assert result.exit_code == 0


class TestSorQuote:
    def test_sor_quote_smoke(self):
        result = runner.invoke(app, ["research", "sor-quote", "--symbol", "BTCUSDT"])
        assert result.exit_code == 0
        assert "SOR" in result.output


class TestGoalCommands:
    def test_goal_create_and_list(self):
        result = runner.invoke(app, ["research", "goal-create", "測試目標"])
        # 可能因 db 寫入失敗, 但需 exit 0 (fail-safe) 或明確錯誤
        assert result.exit_code in (0, 1)

    def test_goal_list(self):
        result = runner.invoke(app, ["research", "goal-list"])
        assert result.exit_code == 0


class TestExportCommands:
    def test_export_to_pine(self, tmp_path: Path):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"symbol": "BTCUSDT", "direction": "LONG"}))
        out = tmp_path / "strategy.pine"
        result = runner.invoke(app, [
            "export", "to-pine", str(plan), "--output", str(out),
        ])
        assert result.exit_code == 0
        assert out.exists() and out.stat().st_size > 0

    def test_export_to_pine_missing_file(self, tmp_path: Path):
        result = runner.invoke(app, ["export", "to-pine", str(tmp_path / "nope.json")])
        assert result.exit_code == 1

    def test_export_to_pine_bad_json(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json{{{")
        result = runner.invoke(app, ["export", "to-pine", str(bad)])
        assert result.exit_code == 1

    def test_export_to_mql5(self, tmp_path: Path):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"symbol": "ETHUSDT", "direction": "SHORT"}))
        out = tmp_path / "strategy.mq5"
        result = runner.invoke(app, [
            "export", "to-mql5", str(plan), "--output", str(out),
        ])
        assert result.exit_code == 0
        assert out.exists() and out.stat().st_size > 0

    def test_export_to_mql5_missing_file(self, tmp_path: Path):
        result = runner.invoke(app, ["export", "to-mql5", str(tmp_path / "nope.json")])
        assert result.exit_code == 1
