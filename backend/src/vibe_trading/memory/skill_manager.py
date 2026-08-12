"""Skill CRUD 操作 - 技能管理系統"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能定義"""
    id: str
    name: str
    description: str
    category: str = "general"
    version: str = "1.0.0"
    author: str = "Vibe Trading"
    created_at: str = ""
    updated_at: str = ""
    enabled: bool = True
    config: Dict = field(default_factory=dict)
    prompt_template: str = ""
    examples: List[str] = field(default_factory=list)

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class SkillManager:
    """
    技能管理器

    提供技能的完整 CRUD 操作：
    - Create: 創建新技能
    - Read: 讀取/搜索技能
    - Update: 更新技能
    - Delete: 刪除技能
    """

    def __init__(self, storage_dir: str = "./skills"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.skills: Dict[str, Skill] = {}
        self._load_skills()

    def _load_skills(self):
        """從文件加載技能"""
        skill_files = list(self.storage_dir.glob("*.json"))

        for skill_file in skill_files:
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    skill = Skill(**data)
                    self.skills[skill.id] = skill
            except Exception as e:
                logger.warning(f"Failed to load skill {skill_file}: {e}")

        logger.info(f"Loaded {len(self.skills)} skills")

    def create_skill(
        self,
        name: str,
        description: str,
        category: str = "general",
        prompt_template: str = "",
        examples: Optional[List[str]] = None,
        config: Optional[Dict] = None,
    ) -> Skill:
        """
        創建新技能

        Args:
            name: 技能名稱
            description: 技能描述
            category: 技能類別
            prompt_template: prompt 模板
            examples: 示例列表
            config: 配置字典

        Returns:
            創建的 Skill 對象
        """
        import uuid

        skill_id = f"skill_{uuid.uuid4().hex[:8]}"
        skill = Skill(
            id=skill_id,
            name=name,
            description=description,
            category=category,
            prompt_template=prompt_template,
            examples=examples or [],
            config=config or {},
        )

        self.skills[skill_id] = skill
        self._save_skill(skill)

        logger.info(f"Created skill: {name} ({skill_id})")
        return skill

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """根據 ID 獲取技能"""
        return self.skills.get(skill_id)

    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        """根據名稱獲取技能"""
        for skill in self.skills.values():
            if skill.name.lower() == name.lower():
                return skill
        return None

    def list_skills(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[Skill]:
        """
        列出技能

        Args:
            category: 按類別過濾
            enabled_only: 僅返回啟用的技能

        Returns:
            Skill 列表
        """
        skills = list(self.skills.values())

        if category:
            skills = [s for s in skills if s.category == category]

        if enabled_only:
            skills = [s for s in skills if s.enabled]

        return skills

    def update_skill(self, skill_id: str, **kwargs) -> Optional[Skill]:
        """
        更新技能

        Args:
            skill_id: 技能 ID
            **kwargs: 要更新的字段

        Returns:
            更新後的 Skill 對象，如果不存在返回 None
        """
        skill = self.skills.get(skill_id)
        if not skill:
            return None

        # 更新字段
        for key, value in kwargs.items():
            if hasattr(skill, key):
                setattr(skill, key, value)

        skill.updated_at = datetime.now().isoformat()
        self._save_skill(skill)

        logger.info(f"Updated skill: {skill.name} ({skill_id})")
        return skill

    def delete_skill(self, skill_id: str) -> bool:
        """
        刪除技能

        Args:
            skill_id: 技能 ID

        Returns:
            是否刪除成功
        """
        skill = self.skills.get(skill_id)
        if not skill:
            return False

        # 刪除文件
        skill_file = self.storage_dir / f"{skill_id}.json"
        if skill_file.exists():
            skill_file.unlink()

        # 從內存中移除
        del self.skills[skill_id]

        logger.info(f"Deleted skill: {skill.name} ({skill_id})")
        return True

    def enable_skill(self, skill_id: str) -> Optional[Skill]:
        """啟用技能"""
        return self.update_skill(skill_id, enabled=True)

    def disable_skill(self, skill_id: str) -> Optional[Skill]:
        """禁用技能"""
        return self.update_skill(skill_id, enabled=False)

    def search_skills(self, query: str) -> List[Skill]:
        """
        搜索技能

        Args:
            query: 搜索關鍵詞

        Returns:
            匹配的技能列表
        """
        query_lower = query.lower()
        results = []

        for skill in self.skills.values():
            if (
                query_lower in skill.name.lower()
                or query_lower in skill.description.lower()
                or query_lower in skill.category.lower()
            ):
                results.append(skill)

        return results

    def get_categories(self) -> List[str]:
        """獲取所有類別"""
        categories = set(skill.category for skill in self.skills.values())
        return sorted(list(categories))

    def get_stats(self) -> Dict[str, int]:
        """獲取統計信息"""
        total = len(self.skills)
        enabled = sum(1 for s in self.skills.values() if s.enabled)
        disabled = total - enabled

        categories = {}
        for skill in self.skills.values():
            categories[skill.category] = categories.get(skill.category, 0) + 1

        return {
            "total_skills": total,
            "enabled": enabled,
            "disabled": disabled,
            "categories": categories,
        }

    def _save_skill(self, skill: Skill):
        """保存技能到文件"""
        skill_file = self.storage_dir / f"{skill.id}.json"

        data = {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "version": skill.version,
            "author": skill.author,
            "created_at": skill.created_at,
            "updated_at": skill.updated_at,
            "enabled": skill.enabled,
            "config": skill.config,
            "prompt_template": skill.prompt_template,
            "examples": skill.examples,
        }

        with open(skill_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
