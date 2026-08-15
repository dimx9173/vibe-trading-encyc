"""Tests for RunManifest (Phase 4.3) — methodology fingerprint."""
from vibe_trading.governance.manifest import (
    _package_versions,
    build_manifest,
    diff_manifests,
)


def _manifest(prompts=None, tools=None, config=None):
    return build_manifest(
        prompts=prompts or {"tech": "analyze RSI"},
        tools=tools or ["get_klines"],
        config=config or {"symbol": "BTCUSDT"},
    )


class TestManifest:
    def test_same_input_same_hash(self):
        assert _manifest()["manifest_hash"] == _manifest()["manifest_hash"]

    def test_diff_prompt_changes_hash(self):
        m1 = _manifest()
        m2 = _manifest(prompts={"tech": "analyze MACD"})
        assert m1["manifest_hash"] != m2["manifest_hash"]

    def test_diff_tool_changes_hash(self):
        m1 = _manifest()
        m2 = _manifest(tools=["get_klines", "get_orderbook"])
        assert m1["manifest_hash"] != m2["manifest_hash"]

    def test_diff_config_changes_hash(self):
        m1 = _manifest()
        m2 = _manifest(config={"symbol": "ETHUSDT"})
        assert m1["manifest_hash"] != m2["manifest_hash"]

    def test_hash_stable_across_runs(self):
        """相同方法論兩次建構 → 相同 hash (可重現性核心)."""
        a = _manifest(config={"symbol": "BTCUSDT", "skip_debate": True, "use_cache": True})
        b = _manifest(config={"symbol": "BTCUSDT", "skip_debate": True, "use_cache": True})
        assert a["manifest_hash"] == b["manifest_hash"]

    def test_prompts_hashed_not_plaintext(self):
        m = _manifest()
        # prompts 值應為 hash (64 hex), 非明文
        assert len(m["prompts"]["tech"]) == 64
        assert m["prompts"]["tech"] != "analyze RSI"


class TestDiff:
    def test_no_diff(self):
        d = diff_manifests(_manifest(), _manifest())
        assert all(v == [] for v in d.values())

    def test_diff_prompts(self):
        m1 = _manifest()
        m2 = _manifest(prompts={"tech": "MACD", "fund": "read balance"})
        d = diff_manifests(m1, m2)
        assert "tech" in d["prompts"]
        assert "fund" in d["prompts"]

    def test_diff_tools(self):
        m1 = _manifest()
        m2 = _manifest(tools=["get_klines", "get_orderbook"])
        d = diff_manifests(m1, m2)
        assert d["tools"] != []

    def test_diff_packages(self):
        m1 = _manifest()
        m2 = build_manifest(
            prompts={"tech": "RSI"}, tools=["get_klines"],
            config={"symbol": "BTCUSDT"},
        )
        # 手動改 packages
        m2["packages"] = {"numpy": "9.9.9"}
        d = diff_manifests(m1, m2)
        assert "numpy" in d["packages"]


class TestPackages:
    def test_package_versions_dict(self):
        pkgs = _package_versions()
        assert isinstance(pkgs, dict)
        assert "numpy" in pkgs
        assert pkgs["numpy"] != "unknown"  # numpy 已安裝

    def test_missing_package_unknown(self):
        pkgs = _package_versions()
        # pi_agent_core 可能未安裝 → "unknown" 或版本 (不崩潰)
        assert isinstance(pkgs.get("pi_agent_core", "unknown"), str)
