"""RunManifest 方法論指紋 (Phase 4.3, 採納評估 A7).

Content-addressed hash of replay methodology: prompts + tools + packages + config.
排除 run_id/timestamp — 兩次相同組成的 run 有相同 hash.
定位: 可重現性證明 (哈希鏈審計帳本的有用替代, 非防篡改).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

_PACKAGES = ("numpy", "pandas", "pi-ai", "pi_agent_core", "python-telegram-bot")


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _package_versions() -> Dict[str, str]:
    """關鍵套件版本 (replay 結果依賴)."""
    out: Dict[str, str] = {}
    for pkg in _PACKAGES:
        try:
            import importlib.metadata
            out[pkg] = importlib.metadata.version(pkg)
        except Exception:
            out[pkg] = "unknown"
    return out


def build_manifest(
    *,
    prompts: Dict[str, str],
    tools: List[str],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """建構 manifest (content-addressed).

    Args:
        prompts: {role: prompt_text}
        tools: 工具名清單 (排序)
        config: replay 配置子集 (排除 timestamp/路徑 — 保證可重現性)

    Returns: manifest dict (含 manifest_hash).
    """
    payload: Dict[str, Any] = {
        "prompts": {k: _sha256(v) for k, v in sorted(prompts.items())},
        "tools": sorted(tools),
        "packages": _package_versions(),
        "config": config,
    }
    manifest_hash = _sha256(json.dumps(payload, sort_keys=True, default=str))
    return {**payload, "manifest_hash": manifest_hash}


def _agent_system_prompt(agent: Any) -> str:
    """從 agent 提取 system prompt (可能因框架結構不同而失敗 → "")."""
    try:
        state = getattr(agent, "state", None)
        options = getattr(state, "options", None) or getattr(state, "config", None)
        return str(getattr(options, "system_prompt", "") or "")
    except Exception:
        return ""


def _iter_agents(coordinator: Any):
    """Yield (role, agent) for every agent in the coordinator."""
    for role, agent in (getattr(coordinator, "_analysts", None) or {}).items():
        yield f"analyst:{role}", agent
    for role, agent in (getattr(coordinator, "_researchers", None) or {}).items():
        yield f"researcher:{role}", agent
    for role, agent in (getattr(coordinator, "_risk_analysts", None) or {}).items():
        yield f"risk:{role}", agent
    if getattr(coordinator, "_trader", None):
        yield "trader", coordinator._trader
    if getattr(coordinator, "_portfolio_manager", None):
        yield "portfolio_manager", coordinator._portfolio_manager


def manifest_from_coordinator(coordinator: Any) -> Dict[str, Any]:
    """從 coordinator 提取 prompts/tools (實際運行組成)."""
    prompts: Dict[str, str] = {}
    for role, agent in _iter_agents(coordinator):
        prompts[role] = _agent_system_prompt(agent)
    return build_manifest(prompts=prompts, tools=[], config={})


def diff_manifests(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, List[str]]:
    """比較兩 manifest, 回報漂移項.

    Returns: {"prompts": [...], "tools": [...], "packages": [...], "config": [...]}
             (值不同的鍵名)
    """
    diffs: Dict[str, List[str]] = {"prompts": [], "tools": [], "packages": [], "config": []}
    for section in diffs:
        pa = a.get(section, {})
        pb = b.get(section, {})
        if isinstance(pa, list) or isinstance(pb, list):
            if list(pa) != list(pb):
                diffs[section].append("<changed>")
            continue
        for key in set(pa) | set(pb):
            if pa.get(key) != pb.get(key):
                diffs[section].append(str(key))
    return diffs
