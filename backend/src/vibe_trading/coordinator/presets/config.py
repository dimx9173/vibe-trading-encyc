"""
Swarm Preset Configuration

YAML-based configuration for pipeline orchestration presets:
- Investment Committee preset
- Risk Committee preset
- Custom presets

Each preset defines:
- Which agents to activate
- Execution order and dependencies
- Timeout and retry policies
- Resource allocation
"""
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class PresetType(str, Enum):
    """Pre-defined preset types"""
    INVESTMENT_COMMITTEE = "investment_committee"
    RISK_COMMITTEE = "risk_committee"
    QUANT_STRATEGY_DESK = "quant_strategy_desk"
    CUSTOM = "custom"


@dataclass
class AgentConfig:
    """Agent configuration within a preset"""
    name: str
    enabled: bool = True
    timeout_seconds: int = 300
    max_retries: int = 3
    priority: int = 0
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineStage:
    """Pipeline stage configuration"""
    name: str
    agents: List[AgentConfig] = field(default_factory=list)
    timeout_seconds: int = 600
    parallel: bool = False
    dependencies: List[str] = field(default_factory=list)


@dataclass
class SwarmPreset:
    """Complete swarm preset configuration"""
    name: str
    type: PresetType
    description: str
    stages: List[PipelineStage] = field(default_factory=list)
    global_timeout_seconds: int = 3600
    max_concurrent_agents: int = 10
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "stages": [
                {
                    "name": stage.name,
                    "agents": [
                        {
                            "name": agent.name,
                            "enabled": agent.enabled,
                            "timeout_seconds": agent.timeout_seconds,
                            "max_retries": agent.max_retries,
                            "priority": agent.priority,
                            "parameters": agent.parameters,
                        }
                        for agent in stage.agents
                    ],
                    "timeout_seconds": stage.timeout_seconds,
                    "parallel": stage.parallel,
                    "dependencies": stage.dependencies,
                }
                for stage in self.stages
            ],
            "global_timeout_seconds": self.global_timeout_seconds,
            "max_concurrent_agents": self.max_concurrent_agents,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SwarmPreset":
        """Create from dictionary"""
        stages = [
            PipelineStage(
                name=stage["name"],
                agents=[
                    AgentConfig(
                        name=agent["name"],
                        enabled=agent.get("enabled", True),
                        timeout_seconds=agent.get("timeout_seconds", 300),
                        max_retries=agent.get("max_retries", 3),
                        priority=agent.get("priority", 0),
                        parameters=agent.get("parameters", {}),
                    )
                    for agent in stage.get("agents", [])
                ],
                timeout_seconds=stage.get("timeout_seconds", 600),
                parallel=stage.get("parallel", False),
                dependencies=stage.get("dependencies", []),
            )
            for stage in data.get("stages", [])
        ]
        
        return cls(
            name=data["name"],
            type=PresetType(data["type"]),
            description=data["description"],
            stages=stages,
            global_timeout_seconds=data.get("global_timeout_seconds", 3600),
            max_concurrent_agents=data.get("max_concurrent_agents", 10),
            metadata=data.get("metadata", {}),
        )


class PresetManager:
    """Manages swarm presets"""
    
    def __init__(self, preset_dir: str = "presets"):
        self.preset_dir = Path(preset_dir)
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        self.presets: Dict[str, SwarmPreset] = {}
        self._load_default_presets()
    
    def _load_default_presets(self):
        """Load built-in presets"""
        
        # Investment Committee Preset
        self.presets["investment_committee"] = SwarmPreset(
            name="Investment Committee",
            type=PresetType.INVESTMENT_COMMITTEE,
            description="Full investment committee with analysts, researchers, risk managers, and portfolio manager",
            stages=[
                PipelineStage(
                    name="Analysis",
                    agents=[
                        AgentConfig(name="technical_analyst", priority=1),
                        AgentConfig(name="fundamental_analyst", priority=1),
                        AgentConfig(name="news_analyst", priority=2),
                        AgentConfig(name="sentiment_analyst", priority=2),
                    ],
                    parallel=True,
                    timeout_seconds=600,
                ),
                PipelineStage(
                    name="Research",
                    agents=[
                        AgentConfig(name="bull_researcher", priority=1),
                        AgentConfig(name="bear_researcher", priority=1),
                    ],
                    parallel=True,
                    dependencies=["Analysis"],
                    timeout_seconds=900,
                ),
                PipelineStage(
                    name="Risk Assessment",
                    agents=[
                        AgentConfig(name="aggressive_risk", priority=1),
                        AgentConfig(name="neutral_risk", priority=1),
                        AgentConfig(name="conservative_risk", priority=1),
                    ],
                    parallel=True,
                    dependencies=["Research"],
                    timeout_seconds=600,
                ),
                PipelineStage(
                    name="Decision",
                    agents=[
                        AgentConfig(name="trader", priority=1),
                        AgentConfig(name="portfolio_manager", priority=2),
                    ],
                    parallel=False,
                    dependencies=["Risk Assessment"],
                    timeout_seconds=600,
                ),
            ],
            global_timeout_seconds=3600,
            max_concurrent_agents=10,
        )
        
        # Risk Committee Preset
        self.presets["risk_committee"] = SwarmPreset(
            name="Risk Committee",
            type=PresetType.RISK_COMMITTEE,
            description="Focused risk assessment with multiple risk perspectives",
            stages=[
                PipelineStage(
                    name="Risk Analysis",
                    agents=[
                        AgentConfig(name="aggressive_risk", priority=1),
                        AgentConfig(name="neutral_risk", priority=1),
                        AgentConfig(name="conservative_risk", priority=1),
                    ],
                    parallel=True,
                    timeout_seconds=600,
                ),
                PipelineStage(
                    name="Risk Decision",
                    agents=[
                        AgentConfig(name="risk_manager", priority=1),
                    ],
                    parallel=False,
                    dependencies=["Risk Analysis"],
                    timeout_seconds=300,
                ),
            ],
            global_timeout_seconds=1800,
            max_concurrent_agents=5,
        )
        
        # Quant Strategy Desk Preset
        self.presets["quant_strategy_desk"] = SwarmPreset(
            name="Quant Strategy Desk",
            type=PresetType.QUANT_STRATEGY_DESK,
            description="Quantitative strategy development with backtesting and optimization",
            stages=[
                PipelineStage(
                    name="Strategy Development",
                    agents=[
                        AgentConfig(name="strategy_developer", priority=1),
                        AgentConfig(name="backtest_engine", priority=2),
                    ],
                    parallel=False,
                    timeout_seconds=1800,
                ),
                PipelineStage(
                    name="Optimization",
                    agents=[
                        AgentConfig(name="optimizer", priority=1),
                    ],
                    parallel=False,
                    dependencies=["Strategy Development"],
                    timeout_seconds=1200,
                ),
                PipelineStage(
                    name="Validation",
                    agents=[
                        AgentConfig(name="validator", priority=1),
                    ],
                    parallel=False,
                    dependencies=["Optimization"],
                    timeout_seconds=600,
                ),
            ],
            global_timeout_seconds=5400,
            max_concurrent_agents=3,
        )
    
    def get_preset(self, name: str) -> Optional[SwarmPreset]:
        """Get a preset by name"""
        return self.presets.get(name)
    
    def get_all_presets(self) -> List[SwarmPreset]:
        """Get all available presets"""
        return list(self.presets.values())
    
    def save_preset(self, preset: SwarmPreset) -> bool:
        """Save a preset to YAML file"""
        filepath = self.preset_dir / f"{preset.name.lower().replace(' ', '_')}.yaml"
        
        with open(filepath, 'w') as f:
            yaml.dump(preset.to_dict(), f, default_flow_style=False)
        
        self.presets[preset.name.lower().replace(' ', '_')] = preset
        return True
    
    def load_preset(self, filepath: str) -> Optional[SwarmPreset]:
        """Load a preset from YAML file"""
        filepath = Path(filepath)
        if not filepath.exists():
            return None
        
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        
        preset = SwarmPreset.from_dict(data)
        self.presets[preset.name.lower().replace(' ', '_')] = preset
        return preset
    
    def create_custom_preset(
        self,
        name: str,
        description: str,
        stages: List[PipelineStage],
        global_timeout_seconds: int = 3600,
        max_concurrent_agents: int = 10
    ) -> SwarmPreset:
        """Create a custom preset"""
        preset = SwarmPreset(
            name=name,
            type=PresetType.CUSTOM,
            description=description,
            stages=stages,
            global_timeout_seconds=global_timeout_seconds,
            max_concurrent_agents=max_concurrent_agents,
        )
        
        self.presets[name.lower().replace(' ', '_')] = preset
        return preset


# Global preset manager instance
_preset_manager: Optional[PresetManager] = None


def get_preset_manager() -> PresetManager:
    """Get global preset manager instance"""
    global _preset_manager
    if _preset_manager is None:
        _preset_manager = PresetManager()
    return _preset_manager
