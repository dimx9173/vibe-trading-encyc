"""Pipeline orchestrator that executes phases based on preset configuration"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import PipelinePhase, SwarmPreset

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Execute trading pipeline phases based on preset configuration"""

    def __init__(self, preset: SwarmPreset):
        self.preset = preset
        self.phase_handlers: Dict[PipelinePhase, Any] = {}

    def register_phase_handler(self, phase: PipelinePhase, handler):
        """Register a handler function for a phase"""
        self.phase_handlers[phase] = handler

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the pipeline according to preset configuration"""
        start_time = datetime.now()
        results: Dict[str, Any] = {}

        enabled_phases = self.preset.get_enabled_phases()
        logger.info(f"Starting pipeline with preset '{self.preset.name}'")
        logger.info(f"Enabled phases: {[p.value for p in enabled_phases]}")

        try:
            for phase in enabled_phases:
                phase_config = self.preset.phases[phase]
                phase_start = datetime.now()

                logger.info(f"Executing phase: {phase.value}")

                # Check if phase handler is registered
                if phase not in self.phase_handlers:
                    logger.warning(f"No handler registered for phase {phase.value}, skipping")
                    continue

                handler = self.phase_handlers[phase]

                # Execute phase with timeout
                timeout = phase_config.timeout_seconds or self.preset.global_timeout_seconds

                try:
                    if timeout:
                        phase_result = await asyncio.wait_for(
                            handler(context, phase_config),
                            timeout=timeout
                        )
                    else:
                        phase_result = await handler(context, phase_config)

                    results[phase.value] = {
                        "status": "success",
                        "result": phase_result,
                        "duration": (datetime.now() - phase_start).total_seconds(),
                    }

                    # Update context with phase results for next phases
                    if isinstance(phase_result, dict):
                        context.update(phase_result)

                except asyncio.TimeoutError:
                    results[phase.value] = {
                        "status": "timeout",
                        "error": f"Phase {phase.value} exceeded timeout of {timeout}s",
                        "duration": (datetime.now() - phase_start).total_seconds(),
                    }
                    logger.error(f"Phase {phase.value} timed out after {timeout}s")
                    break

                except Exception as e:
                    results[phase.value] = {
                        "status": "error",
                        "error": str(e),
                        "duration": (datetime.now() - phase_start).total_seconds(),
                    }
                    logger.error(f"Phase {phase.value} failed: {e}")
                    break

        finally:
            total_duration = (datetime.now() - start_time).total_seconds()
            results["_metadata"] = {
                "preset": self.preset.name,
                "total_duration": total_duration,
                "completed_phases": len([r for r in results.values() if isinstance(r, dict) and r.get("status") == "success"]),
                "timestamp": datetime.now().isoformat(),
            }

        return results

    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Get summary of pipeline configuration"""
        enabled_phases = self.preset.get_enabled_phases()
        total_agents = sum(
            len([a for a in phase_config.agents.values() if a.enabled])
            for phase_config in self.preset.phases.values()
            if phase_config.enabled
        )

        return {
            "preset_name": self.preset.name,
            "mode": self.preset.mode.value,
            "enabled_phases": [p.value for p in enabled_phases],
            "total_agents": total_agents,
            "global_timeout": self.preset.global_timeout_seconds,
            "description": self.preset.description,
        }
