"""Built-in swarm presets"""
from .models import AgentConfig, PhaseConfig, PipelinePhase, PresetMode, SwarmPreset


# Lightweight preset: Skip debate, direct analysis→risk→plan
LIGHTWEIGHT_PRESET = SwarmPreset(
    name="lightweight",
    description="快速決策模式：跳過辯論階段，直接分析→風險評估→計劃",
    mode=PresetMode.LIGHTWEIGHT,
    phases={
        PipelinePhase.ANALYZING: PhaseConfig(
            enabled=True,
            agents={
                "technical": AgentConfig(enabled=True, parallel=True),
                "fundamental": AgentConfig(enabled=False),
                "news": AgentConfig(enabled=False),
                "sentiment": AgentConfig(enabled=True, parallel=True),
            },
        ),
        PipelinePhase.DEBATING: PhaseConfig(enabled=False),
        PipelinePhase.ASSESSING_RISK: PhaseConfig(
            enabled=True,
            agents={
                "conservative": AgentConfig(enabled=True),
            },
        ),
        PipelinePhase.PLANNING: PhaseConfig(
            enabled=True,
            agents={
                "trader": AgentConfig(enabled=True),
                "portfolio_manager": AgentConfig(enabled=True),
            },
        ),
    },
    global_timeout_seconds=300,
)


# Full preset: All 4 phases with all agents
FULL_PRESET = SwarmPreset(
    name="full",
    description="完整決策模式：所有 4 個階段，所有分析師參與",
    mode=PresetMode.FULL,
    phases={
        PipelinePhase.ANALYZING: PhaseConfig(
            enabled=True,
            agents={
                "technical": AgentConfig(enabled=True, parallel=True),
                "fundamental": AgentConfig(enabled=True, parallel=True),
                "news": AgentConfig(enabled=True, parallel=True),
                "sentiment": AgentConfig(enabled=True, parallel=True),
            },
            timeout_seconds=120,
        ),
        PipelinePhase.DEBATING: PhaseConfig(
            enabled=True,
            agents={
                "bull_researcher": AgentConfig(enabled=True),
                "bear_researcher": AgentConfig(enabled=True),
                "research_manager": AgentConfig(enabled=True),
            },
            timeout_seconds=180,
        ),
        PipelinePhase.ASSESSING_RISK: PhaseConfig(
            enabled=True,
            agents={
                "aggressive": AgentConfig(enabled=True, parallel=True),
                "neutral": AgentConfig(enabled=True, parallel=True),
                "conservative": AgentConfig(enabled=True, parallel=True),
            },
            timeout_seconds=90,
        ),
        PipelinePhase.PLANNING: PhaseConfig(
            enabled=True,
            agents={
                "trader": AgentConfig(enabled=True),
                "portfolio_manager": AgentConfig(enabled=True),
            },
            timeout_seconds=120,
        ),
    },
    global_timeout_seconds=600,
)


# Risk-only preset: Skip analysis/debate, only risk assessment
RISK_ONLY_PRESET = SwarmPreset(
    name="risk_only",
    description="風險評審模式：跳過分析和辯論，僅進行風險評估和計劃",
    mode=PresetMode.RISK_ONLY,
    phases={
        PipelinePhase.ANALYZING: PhaseConfig(enabled=False),
        PipelinePhase.DEBATING: PhaseConfig(enabled=False),
        PipelinePhase.ASSESSING_RISK: PhaseConfig(
            enabled=True,
            agents={
                "aggressive": AgentConfig(enabled=True, parallel=True),
                "neutral": AgentConfig(enabled=True, parallel=True),
                "conservative": AgentConfig(enabled=True, parallel=True),
            },
        ),
        PipelinePhase.PLANNING: PhaseConfig(
            enabled=True,
            agents={
                "trader": AgentConfig(enabled=True),
                "portfolio_manager": AgentConfig(enabled=True),
            },
        ),
    },
    global_timeout_seconds=300,
)


# Analysis-only preset: Only analyst phase
ANALYSIS_ONLY_PRESET = SwarmPreset(
    name="analysis_only",
    description="僅分析模式：只執行分析師階段，不進行後續決策",
    mode=PresetMode.ANALYSIS_ONLY,
    phases={
        PipelinePhase.ANALYZING: PhaseConfig(
            enabled=True,
            agents={
                "technical": AgentConfig(enabled=True, parallel=True),
                "fundamental": AgentConfig(enabled=True, parallel=True),
                "news": AgentConfig(enabled=True, parallel=True),
                "sentiment": AgentConfig(enabled=True, parallel=True),
            },
        ),
        PipelinePhase.DEBATING: PhaseConfig(enabled=False),
        PipelinePhase.ASSESSING_RISK: PhaseConfig(enabled=False),
        PipelinePhase.PLANNING: PhaseConfig(enabled=False),
    },
    global_timeout_seconds=180,
)


# Registry of all built-in presets
BUILTIN_PRESETS = {
    "lightweight": LIGHTWEIGHT_PRESET,
    "full": FULL_PRESET,
    "risk_only": RISK_ONLY_PRESET,
    "analysis_only": ANALYSIS_ONLY_PRESET,
}
