"""Swarm Preset models for configurable pipeline orchestration"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class PipelinePhase(str, Enum):
    """Available pipeline phases"""
    ANALYZING = "analyzing"
    DEBATING = "debating"
    ASSESSING_RISK = "assessing_risk"
    PLANNING = "planning"


class PresetMode(str, Enum):
    """Preset execution modes"""
    LIGHTWEIGHT = "lightweight"  # Skip debate, direct analysis→risk→plan
    FULL = "full"  # All 4 phases
    RISK_ONLY = "risk_only"  # Skip analysis/debate, only risk assessment
    ANALYSIS_ONLY = "analysis_only"  # Only analyst phase


class AgentConfig(BaseModel):
    """Agent configuration within a preset"""
    enabled: bool = True
    parallel: bool = False  # Run agents in parallel
    timeout_seconds: Optional[int] = None
    max_retries: int = 0
    config: Dict[str, Any] = Field(default_factory=dict)


class PhaseConfig(BaseModel):
    """Configuration for a single pipeline phase"""
    enabled: bool = True
    agents: Dict[str, AgentConfig] = Field(default_factory=dict)
    skip_if_cached: bool = False
    timeout_seconds: Optional[int] = None


class SwarmPreset(BaseModel):
    """Swarm preset configuration"""
    name: str
    description: str
    mode: PresetMode
    phases: Dict[PipelinePhase, PhaseConfig] = Field(default_factory=dict)
    global_timeout_seconds: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @validator("phases")
    def validate_phases(cls, v):
        """Ensure at least one phase is enabled"""
        enabled_phases = [p for p, config in v.items() if config.enabled]
        if not enabled_phases:
            raise ValueError("At least one phase must be enabled")
        return v

    def get_enabled_phases(self) -> List[PipelinePhase]:
        """Get list of enabled phases in execution order"""
        phase_order = [
            PipelinePhase.ANALYZING,
            PipelinePhase.DEBATING,
            PipelinePhase.ASSESSING_RISK,
            PipelinePhase.PLANNING,
        ]
        return [p for p in phase_order if p in self.phases and self.phases[p].enabled]


class PresetRegistry(BaseModel):
    """Registry of available presets"""
    presets: Dict[str, SwarmPreset] = Field(default_factory=dict)

    def get_preset(self, name: str) -> Optional[SwarmPreset]:
        return self.presets.get(name)

    def list_presets(self) -> List[str]:
        return list(self.presets.keys())
