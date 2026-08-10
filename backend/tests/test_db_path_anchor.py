"""TDD Red for F4: database_url must anchor to repo root (absolute path).

Root cause (2026-08-10): settings.py default database_url is
"sqlite+aiosqlite:///./vibe_trading.db" — a CWD-relative path.
The daemon starts from repo root (334 rows), tests/tools from backend/
(1 row) → two drifting sqlite files; journal persistence looked broken
only because the wrong DB was inspected.

Expected: default database_url resolves to an ABSOLUTE path anchored at the
repo root regardless of CWD. Explicit DATABASE_URL env must still win.
"""
import os
from pathlib import Path

import pytest

import vibe_trading.config.settings as settings_mod
from vibe_trading.config.settings import Settings


# repo root = 3 levels up from this file (backend/tests/test_x.py -> repo)
REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DB = REPO_ROOT / "vibe_trading.db"


def _url_to_path(url: str) -> Path:
    """sqlite+aiosqlite:////abs/path -> /abs/path (4 slashes = absolute)."""
    prefix = "sqlite+aiosqlite:///"
    assert url.startswith(prefix), f"unexpected scheme: {url}"
    return Path(url[len(prefix):]).resolve()


def _fresh_settings(monkeypatch):
    """Rebuild Settings.from_env() with a clean env (no singleton involved)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return Settings.from_env()


class TestDatabaseUrlAnchor:
    def test_default_database_url_is_absolute(self, monkeypatch):
        settings = _fresh_settings(monkeypatch)
        path = _url_to_path(settings.database_url)
        assert path.is_absolute(), f"database_url must be absolute, got {settings.database_url}"

    def test_default_db_anchors_at_repo_root(self, monkeypatch):
        settings = _fresh_settings(monkeypatch)
        assert _url_to_path(settings.database_url) == EXPECTED_DB

    def test_default_db_ignores_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        settings = _fresh_settings(monkeypatch)
        assert _url_to_path(settings.database_url) == EXPECTED_DB

    def test_explicit_database_url_env_wins(self, monkeypatch):
        custom = "sqlite+aiosqlite:////tmp/custom_vibe.db"
        monkeypatch.setenv("DATABASE_URL", custom)
        settings = Settings.from_env()
        assert settings.database_url == custom
