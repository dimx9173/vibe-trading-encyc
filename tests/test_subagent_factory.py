"""Tests for SubagentFactory (Wave D — coverage 85% plan)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.prime.subagent_factory import SubagentFactory


class TestConfig:
    def test_get_config(self):
        cfg = SubagentFactory.get_config("technical_analyst")
        assert cfg is not None
        assert cfg.agent_type == "analyst"
        assert cfg.enabled is True

    def test_get_config_missing(self):
        assert SubagentFactory.get_config("nope") is None

    def test_list_subagents(self):
        subs = SubagentFactory.list_subagents()
        assert "technical_analyst" in subs
        assert len(subs) > 10

    def test_list_enabled_only(self):
        enabled = SubagentFactory.list_subagents(enabled_only=True)
        assert all(
            SubagentFactory.get_config(s).enabled for s in enabled)

    def test_get_by_type(self):
        analysts = SubagentFactory.get_subagents_by_type("analyst")
        assert all(
            SubagentFactory.get_config(a).agent_type == "analyst"
            and SubagentFactory.get_config(a).enabled
            for a in analysts)

    def test_get_available(self):
        available = SubagentFactory.get_available_subagents()
        assert "technical_analyst" in available
        assert available["technical_analyst"] == "enabled"
        assert available["fundamental_analyst"] == "disabled"


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_subagent_unknown(self):
        factory = SubagentFactory()
        handle = await factory.create_subagent("nonexistent", MagicMock())
        assert handle is None

    @pytest.mark.asyncio
    async def test_create_all_subagents(self):
        factory = SubagentFactory()
        with patch.object(factory, "create_subagent", new=AsyncMock(return_value=None)):
            handles = await factory.create_all_subagents(MagicMock())
        assert isinstance(handles, list)

    @pytest.mark.asyncio
    async def test_create_agent_instance_unknown(self):
        factory = SubagentFactory()
        agent = await factory._create_agent_instance("nope", MagicMock())
        assert agent is None
