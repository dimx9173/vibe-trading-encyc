"""Preset loader and validator"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .builtin import BUILTIN_PRESETS
from .models import SwarmPreset


class PresetLoader:
    """Load and validate swarm presets from YAML files"""

    def __init__(self, preset_dir: Optional[Path] = None):
        self.preset_dir = preset_dir or Path(__file__).parent / "yaml"
        self.preset_dir.mkdir(parents=True, exist_ok=True)

    def load_builtin_presets(self) -> Dict[str, SwarmPreset]:
        """Load all built-in presets"""
        return BUILTIN_PRESETS.copy()

    def load_preset_from_file(self, filepath: Path) -> SwarmPreset:
        """Load a preset from a YAML file"""
        if not filepath.exists():
            raise FileNotFoundError(f"Preset file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return SwarmPreset(**data)

    def load_all_presets(self) -> Dict[str, SwarmPreset]:
        """Load all presets (built-in + custom from directory)"""
        presets = self.load_builtin_presets()

        # Load custom presets from directory
        if self.preset_dir.exists():
            for yaml_file in self.preset_dir.glob("*.yaml"):
                try:
                    preset = self.load_preset_from_file(yaml_file)
                    presets[preset.name] = preset
                except Exception as e:
                    print(f"Warning: Failed to load preset {yaml_file}: {e}")

        return presets

    def save_preset(self, preset: SwarmPreset, filepath: Optional[Path] = None) -> Path:
        """Save a preset to a YAML file"""
        if filepath is None:
            filepath = self.preset_dir / f"{preset.name}.yaml"

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(preset.model_dump(mode='json'), f, default_flow_style=False, allow_unicode=True)

        return filepath

    def validate_preset(self, preset: SwarmPreset) -> List[str]:
        """Validate a preset and return list of issues"""
        issues = []

        # Check at least one phase is enabled
        enabled_phases = preset.get_enabled_phases()
        if not enabled_phases:
            issues.append("At least one phase must be enabled")

        # Check phase dependencies
        from .models import PipelinePhase

        if PipelinePhase.DEBATING in enabled_phases and PipelinePhase.ANALYZING not in enabled_phases:
            issues.append("Debating phase requires Analyzing phase to be enabled")

        if PipelinePhase.ASSESSING_RISK in enabled_phases and PipelinePhase.ANALYZING not in enabled_phases:
            issues.append("Risk assessment phase typically requires Analyzing phase")

        # Check agent configurations
        for phase_name, phase_config in preset.phases.items():
            if phase_config.enabled and not phase_config.agents:
                issues.append(f"Phase {phase_name.value} is enabled but has no agents configured")

        # Check timeouts
        if preset.global_timeout_seconds and preset.global_timeout_seconds < 60:
            issues.append("Global timeout should be at least 60 seconds")

        for phase_name, phase_config in preset.phases.items():
            if phase_config.timeout_seconds and phase_config.timeout_seconds < 30:
                issues.append(f"Phase {phase_name.value} timeout should be at least 30 seconds")

        return issues
