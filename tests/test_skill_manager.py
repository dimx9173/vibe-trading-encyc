"""Tests for SkillManager (Wave D — coverage 85% plan)."""
from datetime import datetime

import pytest

from vibe_trading.data_sources.skills.manager import Skill, SkillManager


def _skill(name: str = "s1", rate: float = 0.6, sample: int = 20) -> Skill:
    return Skill(
        name=name, pattern={"rsi": {"min": 20, "max": 40}},
        success_rate=rate, sample_size=sample,
        created_at=datetime(2026, 1, 1),
    )


class TestSkill:
    def test_roundtrip(self):
        s = _skill()
        d = s.to_dict()
        s2 = Skill.from_dict(d)
        assert s2.name == s.name
        assert s2.success_rate == s.success_rate
        assert s2.pattern == s.pattern

    def test_to_dict_last_used_none(self):
        s = _skill()
        assert s.to_dict()["last_used"] is None

    def test_from_dict_with_last_used(self):
        s = _skill()
        s.last_used = datetime(2026, 2, 1)
        s2 = Skill.from_dict(s.to_dict())
        assert s2.last_used == datetime(2026, 2, 1)


class TestSkillManager:
    @pytest.fixture
    def mgr(self, tmp_path):
        return SkillManager(db_path=str(tmp_path / "skills.db"))

    @pytest.mark.asyncio
    async def test_add_get(self, mgr):
        await mgr.add_skill(_skill())
        got = await mgr.get_skill("s1")
        assert got is not None
        assert got.name == "s1"
        assert got.success_rate == 0.6

    @pytest.mark.asyncio
    async def test_get_missing(self, mgr):
        assert await mgr.get_skill("nope") is None

    @pytest.mark.asyncio
    async def test_get_all_sorted(self, mgr):
        await mgr.add_skill(_skill("a", rate=0.5))
        await mgr.add_skill(_skill("b", rate=0.9))
        skills = await mgr.get_all_skills()
        assert skills[0].name == "b"  # 高成功率在前

    @pytest.mark.asyncio
    async def test_match_skills(self, mgr):
        await mgr.add_skill(_skill("a", rate=0.9))
        await mgr.add_skill(Skill(
            name="b", pattern={"rsi": {"min": 70, "max": 90}},
            success_rate=0.5, sample_size=10,
            created_at=datetime(2026, 1, 1),
        ))
        matched = await mgr.match_skills({"rsi": 30})
        assert len(matched) == 1
        assert matched[0].name == "a"

    @pytest.mark.asyncio
    async def test_match_no_conditions(self, mgr):
        await mgr.add_skill(_skill())
        assert await mgr.match_skills({}) == []

    def test_matches_pattern_range(self, mgr):
        assert mgr._matches_pattern({"rsi": {"min": 20, "max": 40}}, {"rsi": 30}) is True
        assert mgr._matches_pattern({"rsi": {"min": 20, "max": 40}}, {"rsi": 50}) is False

    def test_matches_pattern_exact(self, mgr):
        assert mgr._matches_pattern({"rsi": 30}, {"rsi": 30.005}) is True
        assert mgr._matches_pattern({"rsi": 30}, {"rsi": 50}) is False

    @pytest.mark.asyncio
    async def test_update_skill_usage(self, mgr):
        await mgr.add_skill(_skill(rate=0.5))
        await mgr.update_skill_usage("s1", success=True)
        got = await mgr.get_skill("s1")
        assert got.success_rate > 0.5  # EMA 提升
        assert got.last_used is not None

    @pytest.mark.asyncio
    async def test_update_missing_skill(self, mgr):
        await mgr.update_skill_usage("nope", True)  # 不 raise

    @pytest.mark.asyncio
    async def test_delete(self, mgr):
        await mgr.add_skill(_skill())
        assert await mgr.delete_skill("s1") is True
        assert await mgr.get_skill("s1") is None

    @pytest.mark.asyncio
    async def test_get_skill_count(self, mgr):
        await mgr.add_skill(_skill("a"))
        await mgr.add_skill(_skill("b"))
        assert await mgr.get_skill_count() == 2

    @pytest.mark.asyncio
    async def test_cleanup_old_skills(self, mgr):
        await mgr.add_skill(_skill("good", sample=20))
        await mgr.add_skill(_skill("bad", sample=3))
        await mgr.cleanup_old_skills(min_sample_size=10)
        assert await mgr.get_skill("good") is not None
        assert await mgr.get_skill("bad") is None
