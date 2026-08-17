"""TDD regression test for Model validation bug.

Discovered during PHASE_6 DYNAMIC_COMPILE of deadlock fix (commit 2030dc6).
See DYNAMIC_COMPILE_RESULT #8432 observation.

Root cause
----------
Installed `pi_agent_core` (pip) `AgentLoopConfig` is a pydantic `BaseModel`
with strict `model: Model` field, where `Model = pi_agent_core.types.Model`
(3 fields: `api`, `provider`, `id`).

`pi_ai.llm.Model` (vendored at `src/pi_ai/llm.py`) is a `@dataclass` with
5 fields (`provider`, `id`, `api`, `api_key`, `base_url`) — a *different*
class despite the same name.

Previously `vibe_trading.agents.agent_factory.create_trading_agent()` passed
`pi_ai.llm.Model` into `AgentOptions(initial_state={"model": ...})`. When
`AgentLoopConfig` is then constructed inside `pi_agent_core.Agent`, pydantic
strict validation rejects the cross-class instance, and every analyst
phase fails with::

    pydantic_core.ValidationError: 1 validation error for AgentLoopConfig
    model: Input should be a valid dictionary or instance of Model
        [type=model_type, input_value=Model(provider='openai', ...rate.api.nvidia.com/v1'),
         input_type=Model]

Fix
---
Convert `pi_ai.llm.Model` → `pi_agent_core.types.Model` at the boundary
in `agent_factory.create_trading_agent()` before passing to `AgentOptions`.
The conversion preserves the identifier fields (`api`, `provider`, `id`).

Actual LLM streaming still uses `pi_ai.llm.Model` (with `api_key` +
`base_url`) via `ModelRouter.select_model()` — that path is independent
and unaffected by this fix.
"""

import pytest
import sys
from pathlib import Path
from types import SimpleNamespace

# The project-root `tests/conftest.py` does `sys.path.insert(0, backend/src)`,
# which shadows INSTALLED `pi_agent_core` (from site-packages) with the VENDORED
# `src/pi_agent_core` — and the vendored types.py does NOT have the `Model`
# class (it's an older version). VBT runtime uses INSTALLED pi_agent_core
# (site-packages comes before src/ in venv sys.path), so this test must mirror
# that: load installed pi_agent_core explicitly.
src_path = str(Path(__file__).parent.parent.parent / "src")
sys.path = [p for p in sys.path if p != src_path]
for _m in list(sys.modules.keys()):
    if _m.startswith('pi_agent_core'):
        del sys.modules[_m]

from pi_agent_core.types import Model as AgentLoopModel

# Restore vendored src/ for `pi_ai` + `vibe_trading` imports.
sys.path.insert(0, src_path)


def _fake_tool_context():
    return SimpleNamespace(symbol="BTCUSDT")


@pytest.fixture
def analyst_config():
    from vibe_trading.config.agent_config import AgentConfig, AgentRole
    return AgentConfig(
        name="Test Technical Analyst",
        role=AgentRole.TECHNICAL_ANALYST,
        temperature=0.5,
    )


@pytest.fixture
def fake_tool_context():
    return _fake_tool_context()


@pytest.mark.asyncio
async def test_T1_agent_state_model_is_agent_loop_model_type(
    analyst_config, fake_tool_context
):
    """T1: agent._state.model must be pi_agent_core.types.Model (not pi_ai.llm.Model)."""
    from vibe_trading.agents.agent_factory import create_trading_agent

    agent = await create_trading_agent(
        config=analyst_config,
        tool_context=fake_tool_context,
        enable_streaming=False,
    )

    assert isinstance(agent._state.model, AgentLoopModel), (
        f"Expected AgentLoopModel (pi_agent_core.types.Model), got "
        f"{type(agent._state.model).__module__}.{type(agent._state.model).__name__}"
    )
    # sanity: provider/id carried through
    assert agent._state.model.provider == "openai"
    # 模型由 llm.yaml use_llm 決定 (當前 mimo-v2.5); 斷言與配置一致
    from vibe_trading.config.llm_config import get_llm_config
    expected = get_llm_config().get_current_name()
    mcfg = get_llm_config().get_config(expected)
    assert agent._state.model.id == mcfg["model"]


@pytest.mark.asyncio
async def test_T2_create_trading_agent_does_not_raise_validation_error(
    analyst_config, fake_tool_context
):
    """T2: full create_trading_agent path must not raise pydantic.ValidationError.

    Before fix: agent init raises ``pydantic_core.ValidationError`` on
    ``AgentLoopConfig.model`` (the bug).
    After fix: agent init succeeds cleanly.
    """
    from vibe_trading.agents.agent_factory import create_trading_agent

    agent = await create_trading_agent(
        config=analyst_config,
        tool_context=fake_tool_context,
        enable_streaming=False,
    )
    assert agent is not None


@pytest.mark.asyncio
async def test_T3_conversion_preserves_all_5_analyst_roles(fake_tool_context):
    """T3: every analyst role gets a converted Model (regression guard)."""
    from vibe_trading.config.agent_config import AgentConfig, AgentRole
    from vibe_trading.agents.agent_factory import create_trading_agent

    roles = [
        AgentRole.TECHNICAL_ANALYST,
        AgentRole.FUNDAMENTAL_ANALYST,
        AgentRole.NEWS_ANALYST,
        AgentRole.SENTIMENT_ANALYST,
    ]
    for role in roles:
        config = AgentConfig(name=f"Test {role.value}", role=role, temperature=0.5)
        agent = await create_trading_agent(
            config=config, tool_context=fake_tool_context, enable_streaming=False
        )
        assert isinstance(agent._state.model, AgentLoopModel), (
            f"{role.value}: expected AgentLoopModel, got "
            f"{type(agent._state.model).__name__}"
        )