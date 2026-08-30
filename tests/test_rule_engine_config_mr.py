"""Tests for RuleEngineConfig MR / hysteresis params (Task 3)."""
from __future__ import annotations

import pytest

from vibe_trading.rule_engine.config import RuleEngineConfig


def test_mr_config_from_env(monkeypatch):
    monkeypatch.setenv("RULE_BB_WIDTH_RATIO", "0.6")
    monkeypatch.setenv("RULE_MR_SL_ATR", "2.0")
    c = RuleEngineConfig.from_env()
    assert c.bb_width_ratio == 0.6
    assert c.mr_sl_atr == 2.0
    assert c.mr_trailing == 0.0


def test_mr_config_defaults(monkeypatch):
    monkeypatch.delenv("RULE_BB_WIDTH_RATIO", raising=False)
    monkeypatch.delenv("RULE_BB_WIDTH_FLOOR", raising=False)
    monkeypatch.delenv("RULE_RSI_NEUTRAL", raising=False)
    monkeypatch.delenv("RULE_CHOPPY_ENTER_BARS", raising=False)
    monkeypatch.delenv("RULE_CHOPPY_EXIT_BARS", raising=False)
    monkeypatch.delenv("RULE_MR_SL_ATR", raising=False)
    monkeypatch.delenv("RULE_MR_TP_ATR", raising=False)
    monkeypatch.delenv("RULE_MR_TRAILING", raising=False)
    c = RuleEngineConfig.from_env()
    assert c.bb_width_ratio == 0.7
    assert c.bb_width_floor == 0.015
    assert c.rsi_neutral == 0.4
    assert c.choppy_enter_bars == 3
    assert c.choppy_exit_bars == 2
    assert c.mr_sl_atr == 2.5
    assert c.mr_tp_atr == 1.8
    assert c.mr_trailing == 0.0


def test_mr_config_all_envs(monkeypatch):
    monkeypatch.setenv("RULE_BB_WIDTH_RATIO", "0.5")
    monkeypatch.setenv("RULE_BB_WIDTH_FLOOR", "0.02")
    monkeypatch.setenv("RULE_RSI_NEUTRAL", "0.35")
    monkeypatch.setenv("RULE_CHOPPY_ENTER_BARS", "4")
    monkeypatch.setenv("RULE_CHOPPY_EXIT_BARS", "3")
    monkeypatch.setenv("RULE_MR_SL_ATR", "3.0")
    monkeypatch.setenv("RULE_MR_TP_ATR", "2.0")
    monkeypatch.setenv("RULE_MR_TRAILING", "0.5")
    c = RuleEngineConfig.from_env()
    assert c.bb_width_ratio == 0.5
    assert c.bb_width_floor == 0.02
    assert c.rsi_neutral == 0.35
    assert c.choppy_enter_bars == 4
    assert c.choppy_exit_bars == 3
    assert c.mr_sl_atr == 3.0
    assert c.mr_tp_atr == 2.0
    assert c.mr_trailing == 0.5
