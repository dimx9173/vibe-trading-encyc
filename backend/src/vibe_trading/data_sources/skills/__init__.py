"""
Skills Module

Manages learned trading skills/patterns for both live trading and backtest.
"""

from .manager import SkillManager, Skill

__all__ = [
    "SkillManager",
    "Skill",
]
