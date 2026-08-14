"""
Skill Manager

Manages learned trading skills/patterns:
- Store skills learned from historical trades
- Match skills to current market conditions
- Share skills between live trading and backtest
"""
import sqlite3
import json
from typing import List, Dict, Optional, Any
from datetime import datetime


class Skill:
    """Trading skill/pattern"""
    
    def __init__(
        self,
        name: str,
        pattern: Dict[str, Any],
        success_rate: float,
        sample_size: int,
        created_at: datetime,
        last_used: Optional[datetime] = None
    ):
        self.name = name
        self.pattern = pattern  # Market conditions that trigger this skill
        self.success_rate = success_rate  # 0-1
        self.sample_size = sample_size
        self.created_at = created_at
        self.last_used = last_used
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "pattern": self.pattern,
            "success_rate": self.success_rate,
            "sample_size": self.sample_size,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(
            name=data["name"],
            pattern=data["pattern"],
            success_rate=data["success_rate"],
            sample_size=data["sample_size"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=datetime.fromisoformat(data["last_used"]) if data.get("last_used") else None,
        )


class SkillManager:
    """Skill manager with SQLite storage"""
    
    def __init__(self, db_path: str = "skills.db", max_skills: int = 100):
        self.db_path = db_path
        self.max_skills = max_skills
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    name TEXT PRIMARY KEY,
                    pattern TEXT NOT NULL,
                    success_rate REAL NOT NULL,
                    sample_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used TEXT
                )
            """)
            conn.commit()
    
    async def add_skill(self, skill: Skill) -> bool:
        """Add or update a skill"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skills 
                (name, pattern, success_rate, sample_size, created_at, last_used)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                skill.name,
                json.dumps(skill.pattern),
                skill.success_rate,
                skill.sample_size,
                skill.created_at.isoformat(),
                skill.last_used.isoformat() if skill.last_used else None,
            ))
            conn.commit()
        return True
    
    async def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM skills WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
        
        if not row:
            return None
        
        return Skill(
            name=row[0],
            pattern=json.loads(row[1]),
            success_rate=row[2],
            sample_size=row[3],
            created_at=datetime.fromisoformat(row[4]),
            last_used=datetime.fromisoformat(row[5]) if row[5] else None,
        )
    
    async def get_all_skills(self) -> List[Skill]:
        """Get all skills"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM skills ORDER BY success_rate DESC")
            rows = cursor.fetchall()
        
        return [
            Skill(
                name=row[0],
                pattern=json.loads(row[1]),
                success_rate=row[2],
                sample_size=row[3],
                created_at=datetime.fromisoformat(row[4]),
                last_used=datetime.fromisoformat(row[5]) if row[5] else None,
            )
            for row in rows
        ]
    
    async def match_skills(self, market_conditions: Dict[str, float]) -> List[Skill]:
        """Match skills to current market conditions"""
        all_skills = await self.get_all_skills()
        
        matched = []
        for skill in all_skills:
            if self._matches_pattern(skill.pattern, market_conditions):
                matched.append(skill)
        
        # Sort by success rate and sample size
        matched.sort(key=lambda s: (s.success_rate, s.sample_size), reverse=True)
        
        return matched[:10]  # Return top 10 matches
    
    def _matches_pattern(self, pattern: Dict[str, Any], conditions: Dict[str, float]) -> bool:
        """Check if market conditions match skill pattern"""
        for key, value in pattern.items():
            if key not in conditions:
                return False
            
            condition_value = conditions[key]
            
            # Check if value is within range
            if isinstance(value, dict):
                min_val = value.get("min", float("-inf"))
                max_val = value.get("max", float("inf"))
                
                if not (min_val <= condition_value <= max_val):
                    return False
            else:
                # Exact match
                if abs(condition_value - value) > 0.01:
                    return False
        
        return True
    
    async def update_skill_usage(self, name: str, success: bool):
        """Update skill usage statistics"""
        skill = await self.get_skill(name)
        if not skill:
            return
        
        # Update success rate with EMA
        alpha = 0.1
        new_success_rate = skill.success_rate * (1 - alpha) + (1.0 if success else 0.0) * alpha
        
        # Update last used
        skill.last_used = datetime.now()
        skill.success_rate = new_success_rate
        
        await self.add_skill(skill)
    
    async def delete_skill(self, name: str) -> bool:
        """Delete a skill"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            conn.commit()
        return True
    
    async def get_skill_count(self) -> int:
        """Get total number of skills"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM skills")
            return cursor.fetchone()[0]
    
    async def cleanup_old_skills(self, min_sample_size: int = 10):
        """Remove skills with insufficient sample size"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM skills WHERE sample_size < ?",
                (min_sample_size,)
            )
            conn.commit()
