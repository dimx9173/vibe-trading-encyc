"""Tests for ProviderFactory — Wave D117."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe_trading.data_sources.providers.factory import ProviderFactory


@pytest.fixture(autouse=True)
def _clean_instances():
    ProviderFactory._instances = {}
    yield
    ProviderFactory._instances = {}


class TestProviderFactory:
    @pytest.mark.asyncio
    async def test_create_provider(self):
        provider = MagicMock()
        provider.connect = AsyncMock()
        with patch("vibe_trading.data_sources.providers.factory.ProviderRegistry.get",
                   return_value=MagicMock(return_value=provider)), \
             patch("vibe_trading.data_sources.providers.factory.get_exchange_config",
                   return_value=MagicMock()):
            p = await ProviderFactory.create_provider("binance")
        assert p is provider
        provider.connect.assert_called_once()
        assert ProviderFactory.has_provider("binance")

    @pytest.mark.asyncio
    async def test_create_cached(self):
        provider = MagicMock()
        provider.connect = AsyncMock()
        with patch("vibe_trading.data_sources.providers.factory.ProviderRegistry.get",
                   return_value=MagicMock(return_value=provider)):
            a = await ProviderFactory.create_provider("okx")
            b = await ProviderFactory.create_provider("okx")
        assert a is b
        assert provider.connect.call_count == 1

    @pytest.mark.asyncio
    async def test_create_unknown_exchange(self):
        with patch("vibe_trading.data_sources.providers.factory.ProviderRegistry.get",
                   return_value=None):
            with pytest.raises(ValueError):
                await ProviderFactory.create_provider("nope")

    @pytest.mark.asyncio
    async def test_create_connect_fail_cached(self):
        provider = MagicMock()
        provider.connect = AsyncMock(side_effect=RuntimeError("down"))
        with patch("vibe_trading.data_sources.providers.factory.ProviderRegistry.get",
                   return_value=MagicMock(return_value=provider)):
            p = await ProviderFactory.create_provider("binance")  # 不 raise
        assert p is provider  # 即使連接失敗也快取

    @pytest.mark.asyncio
    async def test_get_provider_delegates(self):
        provider = MagicMock()
        provider.connect = AsyncMock()
        with patch.object(ProviderFactory, "create_provider",
                          new=AsyncMock(return_value=provider)):
            p = await ProviderFactory.get_provider("binance")
        assert p is provider

    @pytest.mark.asyncio
    async def test_close_provider(self):
        provider = MagicMock()
        provider.disconnect = AsyncMock()
        ProviderFactory._instances = {"binance": provider}
        await ProviderFactory.close_provider("binance")
        provider.disconnect.assert_called_once()
        assert not ProviderFactory.has_provider("binance")

    @pytest.mark.asyncio
    async def test_close_provider_missing(self):
        await ProviderFactory.close_provider("nope")  # 不 raise

    @pytest.mark.asyncio
    async def test_close_all(self):
        provider = MagicMock()
        provider.disconnect = AsyncMock()
        ProviderFactory._instances = {"binance": provider, "okx": provider}
        await ProviderFactory.close_all()
        assert provider.disconnect.call_count == 2
        assert ProviderFactory.list_active_providers() == []

    def test_list_active_providers(self):
        ProviderFactory._instances = {"binance": MagicMock()}
        assert ProviderFactory.list_active_providers() == ["binance"]

    def test_has_provider(self):
        assert ProviderFactory.has_provider("binance") is False
        ProviderFactory._instances = {"binance": MagicMock()}
        assert ProviderFactory.has_provider("binance") is True
