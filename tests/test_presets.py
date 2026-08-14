"""Tests for Swarm Presets module"""
import pytest
import tempfile
from pathlib import Path

from vibe_trading.coordinator.presets import (
    SwarmPreset,
    PresetLoader,
    PipelineOrchestrator,
    PipelinePhase,
    PresetMode,
    PhaseConfig,
    AgentConfig,
    BUILTIN_PRESETS,
    LIGHTWEIGHT_PRESET,
    FULL_PRESET,
    RISK_ONLY_PRESET,
    ANALYSIS_ONLY_PRESET,
)


class TestSwarmPreset:
    """Test SwarmPreset model"""

    def test_create_preset(self):
        """Test creating a preset"""
        preset = SwarmPreset(
            name="test_preset",
            description="Test preset",
            mode=PresetMode.LIGHTWEIGHT,
            phases={
                PipelinePhase.ANALYZING: PhaseConfig(enabled=True),
                PipelinePhase.PLANNING: PhaseConfig(enabled=True),
            },
        )

        assert preset.name == "test_preset"
        assert preset.mode == PresetMode.LIGHTWEIGHT
        assert len(preset.get_enabled_phases()) == 2

    def test_preset_validation_no_phases(self):
        """Test preset validation with no enabled phases"""
        with pytest.raises(Exception):
            SwarmPreset(
                name="invalid",
                description="Invalid preset",
                mode=PresetMode.FULL,
                phases={
                    PipelinePhase.ANALYZING: PhaseConfig(enabled=False),
                    PipelinePhase.PLANNING: PhaseConfig(enabled=False),
                },
            )

    def test_get_enabled_phases_order(self):
        """Test that enabled phases are returned in correct order"""
        preset = SwarmPreset(
            name="order_test",
            description="Test phase order",
            mode=PresetMode.FULL,
            phases={
                PipelinePhase.PLANNING: PhaseConfig(enabled=True),
                PipelinePhase.ANALYZING: PhaseConfig(enabled=True),
                PipelinePhase.ASSESSING_RISK: PhaseConfig(enabled=True),
            },
        )

        enabled = preset.get_enabled_phases()
        assert enabled == [
            PipelinePhase.ANALYZING,
            PipelinePhase.ASSESSING_RISK,
            PipelinePhase.PLANNING,
        ]


class TestBuiltinPresets:
    """Test built-in presets"""

    def test_builtin_presets_exist(self):
        """Test that all built-in presets exist"""
        assert "lightweight" in BUILTIN_PRESETS
        assert "full" in BUILTIN_PRESETS
        assert "risk_only" in BUILTIN_PRESETS
        assert "analysis_only" in BUILTIN_PRESETS

    def test_lightweight_preset(self):
        """Test lightweight preset configuration"""
        preset = LIGHTWEIGHT_PRESET
        assert preset.mode == PresetMode.LIGHTWEIGHT
        assert preset.phases[PipelinePhase.ANALYZING].enabled
        assert not preset.phases[PipelinePhase.DEBATING].enabled
        assert preset.phases[PipelinePhase.ASSESSING_RISK].enabled
        assert preset.phases[PipelinePhase.PLANNING].enabled

    def test_full_preset(self):
        """Test full preset configuration"""
        preset = FULL_PRESET
        assert preset.mode == PresetMode.FULL
        for phase in PipelinePhase:
            assert preset.phases[phase].enabled

    def test_risk_only_preset(self):
        """Test risk-only preset configuration"""
        preset = RISK_ONLY_PRESET
        assert preset.mode == PresetMode.RISK_ONLY
        assert not preset.phases[PipelinePhase.ANALYZING].enabled
        assert not preset.phases[PipelinePhase.DEBATING].enabled
        assert preset.phases[PipelinePhase.ASSESSING_RISK].enabled
        assert preset.phases[PipelinePhase.PLANNING].enabled

    def test_analysis_only_preset(self):
        """Test analysis-only preset configuration"""
        preset = ANALYSIS_ONLY_PRESET
        assert preset.mode == PresetMode.ANALYSIS_ONLY
        assert preset.phases[PipelinePhase.ANALYZING].enabled
        assert not preset.phases[PipelinePhase.DEBATING].enabled
        assert not preset.phases[PipelinePhase.ASSESSING_RISK].enabled
        assert not preset.phases[PipelinePhase.PLANNING].enabled


class TestPresetLoader:
    """Test PresetLoader"""

    def test_load_builtin_presets(self):
        """Test loading built-in presets"""
        loader = PresetLoader()
        presets = loader.load_builtin_presets()

        assert len(presets) == 4
        assert "lightweight" in presets
        assert "full" in presets

    def test_load_preset_from_file(self):
        """Test loading preset from YAML file"""
        loader = PresetLoader()

        # Create a temporary YAML file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""
name: test_custom
description: Custom test preset
mode: lightweight
phases:
  analyzing:
    enabled: true
    agents:
      technical:
        enabled: true
  planning:
    enabled: true
    agents:
      trader:
        enabled: true
global_timeout_seconds: 300
""")
            temp_path = Path(f.name)

        try:
            preset = loader.load_preset_from_file(temp_path)
            assert preset.name == "test_custom"
            assert preset.mode == PresetMode.LIGHTWEIGHT
            assert len(preset.get_enabled_phases()) == 2
        finally:
            temp_path.unlink()

    def test_load_nonexistent_file(self):
        """Test loading non-existent file raises error"""
        loader = PresetLoader()
        with pytest.raises(FileNotFoundError):
            loader.load_preset_from_file(Path("/nonexistent/preset.yaml"))

    def test_save_preset(self):
        """Test saving preset to YAML file"""
        loader = PresetLoader()

        with tempfile.TemporaryDirectory() as tmpdir:
            preset = LIGHTWEIGHT_PRESET
            filepath = loader.save_preset(preset, Path(tmpdir) / "test.yaml")

            assert filepath.exists()

            # Load it back
            loaded = loader.load_preset_from_file(filepath)
            assert loaded.name == preset.name
            assert loaded.mode == preset.mode

    def test_validate_preset_valid(self):
        """Test validating a valid preset"""
        loader = PresetLoader()
        issues = loader.validate_preset(LIGHTWEIGHT_PRESET)
        assert len(issues) == 0

    def test_validate_preset_missing_agents(self):
        """Test validating preset with enabled phase but no agents"""
        loader = PresetLoader()

        preset = SwarmPreset(
            name="test",
            description="Test",
            mode=PresetMode.FULL,
            phases={
                PipelinePhase.ANALYZING: PhaseConfig(enabled=True, agents={}),
            },
        )

        issues = loader.validate_preset(preset)
        assert any("no agents configured" in issue for issue in issues)

    def test_validate_preset_short_timeout(self):
        """Test validating preset with too short timeout"""
        loader = PresetLoader()

        preset = SwarmPreset(
            name="test",
            description="Test",
            mode=PresetMode.FULL,
            phases={
                PipelinePhase.ANALYZING: PhaseConfig(
                    enabled=True,
                    agents={"technical": AgentConfig(enabled=True)},
                    timeout_seconds=10,
                ),
            },
            global_timeout_seconds=30,
        )

        issues = loader.validate_preset(preset)
        assert any("timeout" in issue.lower() for issue in issues)


class TestPipelineOrchestrator:
    """Test PipelineOrchestrator"""

    @pytest.mark.asyncio
    async def test_execute_pipeline(self):
        """Test executing a pipeline"""
        orchestrator = PipelineOrchestrator(LIGHTWEIGHT_PRESET)

        # Mock phase handlers
        async def mock_analyze(context, config):
            return {"analysis": "completed"}

        async def mock_risk(context, config):
            return {"risk_assessment": "completed"}

        async def mock_plan(context, config):
            return {"plan": "completed"}

        orchestrator.register_phase_handler(PipelinePhase.ANALYZING, mock_analyze)
        orchestrator.register_phase_handler(PipelinePhase.ASSESSING_RISK, mock_risk)
        orchestrator.register_phase_handler(PipelinePhase.PLANNING, mock_plan)

        results = await orchestrator.execute({})

        assert "analyzing" in results
        assert results["analyzing"]["status"] == "success"
        assert "assessing_risk" in results
        assert results["assessing_risk"]["status"] == "success"
        assert "planning" in results
        assert results["planning"]["status"] == "success"
        assert "_metadata" in results

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self):
        """Test pipeline execution with timeout"""
        import asyncio

        preset = SwarmPreset(
            name="timeout_test",
            description="Test timeout",
            mode=PresetMode.FULL,
            phases={
                PipelinePhase.ANALYZING: PhaseConfig(
                    enabled=True,
                    agents={"technical": AgentConfig(enabled=True)},
                    timeout_seconds=1,
                ),
            },
        )

        orchestrator = PipelineOrchestrator(preset)

        async def slow_handler(context, config):
            await asyncio.sleep(2)
            return {"result": "done"}

        orchestrator.register_phase_handler(PipelinePhase.ANALYZING, slow_handler)

        results = await orchestrator.execute({})

        assert "analyzing" in results
        assert results["analyzing"]["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_execute_with_error(self):
        """Test pipeline execution with error"""
        preset = SwarmPreset(
            name="error_test",
            description="Test error",
            mode=PresetMode.FULL,
            phases={
                PipelinePhase.ANALYZING: PhaseConfig(
                    enabled=True,
                    agents={"technical": AgentConfig(enabled=True)},
                ),
            },
        )

        orchestrator = PipelineOrchestrator(preset)

        async def failing_handler(context, config):
            raise ValueError("Test error")

        orchestrator.register_phase_handler(PipelinePhase.ANALYZING, failing_handler)

        results = await orchestrator.execute({})

        assert "analyzing" in results
        assert results["analyzing"]["status"] == "error"
        assert "Test error" in results["analyzing"]["error"]

    def test_get_pipeline_summary(self):
        """Test getting pipeline summary"""
        orchestrator = PipelineOrchestrator(FULL_PRESET)
        summary = orchestrator.get_pipeline_summary()

        assert summary["preset_name"] == "full"
        assert summary["mode"] == "full"
        assert len(summary["enabled_phases"]) == 4
        assert summary["total_agents"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
