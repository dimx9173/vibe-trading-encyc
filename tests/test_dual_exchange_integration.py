"""
整合測試：OKX + Binance 雙交易所路由
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from vibe_trading.execution.broker_connector import BrokerConnector, BrokerConfig, BrokerType, BrokerRouter
from vibe_trading.execution.okx_executor import OkxOrderExecutor
from vibe_trading.execution.order_executor import (
    OrderResult,
    OrderSide,
    OrderType,
    PositionSide,
    TradingMode,
    create_executor,
)


class TestDualExchangeIntegration:
    """測試雙交易所整合"""

    @pytest.fixture
    def mock_binance_executor(self):
        """創建模擬 Binance 執行器"""
        executor = AsyncMock(spec=BrokerConnector)
        executor.place_order.return_value = OrderResult(
            order_id="binance_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
            filled_price=50000.0,
            filled_quantity=0.001,
            status="FILLED",
            timestamp=int(datetime.now().timestamp() * 1000),
            is_paper=False,
        )
        executor.get_balance.return_value = {"USDT": 10000.0, "BTC": 0.1}
        executor.get_positions.return_value = []
        return executor

    @pytest.fixture
    def mock_okx_executor(self):
        """創建模擬 OKX 執行器"""
        executor = AsyncMock(spec=BrokerConnector)
        executor.place_order.return_value = OrderResult(
            order_id="okx_456",
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
            filled_price=50000.0,
            filled_quantity=0.001,
            status="FILLED",
            timestamp=int(datetime.now().timestamp() * 1000),
            is_paper=False,
        )
        executor.get_balance.return_value = {"USDT": 8000.0, "BTC": 0.05}
        executor.get_positions.return_value = []
        return executor

    @pytest.fixture
    def dual_exchange_router(self, mock_binance_executor, mock_okx_executor):
        """創建雙交易所路由器"""
        router = BrokerRouter(default_broker=BrokerType.BINANCE)
        router.register_connector(BrokerType.BINANCE, mock_binance_executor)
        router.register_connector(BrokerType.OKX, mock_okx_executor)
        return router

    @pytest.mark.asyncio
    async def test_route_to_binance(self, dual_exchange_router, mock_binance_executor):
        """測試路由到 Binance"""
        result = await dual_exchange_router.place_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
            broker=BrokerType.BINANCE,
        )

        assert result.order_id == "binance_123"
        mock_binance_executor.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_to_okx(self, dual_exchange_router, mock_okx_executor):
        """測試路由到 OKX"""
        result = await dual_exchange_router.place_order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
            broker=BrokerType.OKX,
        )

        assert result.order_id == "okx_456"
        mock_okx_executor.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_to_binance(self, dual_exchange_router, mock_binance_executor):
        """測試默認路由到 Binance"""
        result = await dual_exchange_router.place_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
        )

        assert result.order_id == "binance_123"
        mock_binance_executor.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_balance_from_both_exchanges(self, dual_exchange_router, mock_binance_executor, mock_okx_executor):
        """測試從兩個交易所獲取餘額"""
        binance_balance = await dual_exchange_router.get_balance(BrokerType.BINANCE)
        okx_balance = await dual_exchange_router.get_balance(BrokerType.OKX)

        assert binance_balance["USDT"] == 10000.0
        assert okx_balance["USDT"] == 8000.0

        mock_binance_executor.get_balance.assert_called_once()
        mock_okx_executor.get_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_connections(self, dual_exchange_router, mock_binance_executor, mock_okx_executor):
        """測試關閉所有連接"""
        await dual_exchange_router.close_all()

        mock_binance_executor.close.assert_called_once()
        mock_okx_executor.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_switch_default_broker(self, dual_exchange_router, mock_okx_executor):
        """測試切換默認交易所"""
        dual_exchange_router.default_broker = BrokerType.OKX

        result = await dual_exchange_router.place_order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
        )

        assert result.order_id == "okx_456"
        mock_okx_executor.place_order.assert_called_once()


class TestCreateExecutorIntegration:
    """測試 create_executor 工廠函數整合"""

    @patch("vibe_trading.execution.order_executor.get_settings")
    def test_create_binance_executor(self, mock_get_settings):
        """測試創建 Binance 執行器"""
        mock_settings = MagicMock()
        mock_settings.binance_api_key = "test_key"
        mock_settings.binance_api_secret = "test_secret"
        mock_get_settings.return_value = mock_settings

        executor = create_executor(mode=TradingMode.LIVE, dry_run=True)
        assert executor is not None

    @patch("vibe_trading.execution.order_executor.get_settings")
    def test_create_okx_executor(self, mock_get_settings):
        """測試創建 OKX 執行器"""
        mock_settings = MagicMock()
        mock_settings.okx_api_key = "test_key"
        mock_settings.okx_api_secret = "test_secret"
        mock_settings.okx_passphrase = "test_passphrase"
        mock_get_settings.return_value = mock_settings

        executor = create_executor(mode=TradingMode.OKX_LIVE, dry_run=True)
        assert executor is not None
        assert isinstance(executor, OkxOrderExecutor)

    @patch("vibe_trading.execution.order_executor.get_settings")
    def test_create_paper_executor(self, mock_get_settings):
        """測試創建 Paper 執行器"""
        executor = create_executor(mode=TradingMode.PAPER)
        assert executor is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
