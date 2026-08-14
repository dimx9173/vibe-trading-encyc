"""
P4.1 OKX 實盤單元測試
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
    Position,
    PositionSide,
    TradingMode,
    create_executor,
)


class TestBrokerConnector:
    """測試 Broker Connector 抽象層"""

    def test_broker_type_enum(self):
        """測試 BrokerType 枚舉"""
        assert BrokerType.BINANCE == "binance"
        assert BrokerType.OKX == "okx"
        assert BrokerType.PAPER == "paper"

    def test_broker_config(self):
        """測試 BrokerConfig 數據類"""
        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            testnet=True,
            dry_run=False,
        )
        assert config.broker_type == BrokerType.OKX
        assert config.api_key == "test_key"
        assert config.api_secret == "test_secret"
        assert config.passphrase == "test_passphrase"
        assert config.testnet is True
        assert config.dry_run is False


class TestBrokerRouter:
    """測試 Broker Router"""

    def test_register_and_get_connector(self):
        """測試註冊和獲取 connector"""
        router = BrokerRouter(default_broker=BrokerType.BINANCE)
        
        mock_connector = MagicMock(spec=BrokerConnector)
        router.register_connector(BrokerType.BINANCE, mock_connector)
        
        connector = router.get_connector(BrokerType.BINANCE)
        assert connector == mock_connector

    def test_get_default_connector(self):
        """測試獲取默認 connector"""
        router = BrokerRouter(default_broker=BrokerType.OKX)
        
        mock_connector = MagicMock(spec=BrokerConnector)
        router.register_connector(BrokerType.OKX, mock_connector)
        
        connector = router.get_connector()
        assert connector == mock_connector

    def test_get_unregistered_connector_raises_error(self):
        """測試獲取未註冊的 connector 拋出錯誤"""
        router = BrokerRouter()
        
        with pytest.raises(ValueError, match="not registered"):
            router.get_connector(BrokerType.BINANCE)

    @pytest.mark.asyncio
    async def test_route_place_order(self):
        """測試路由下單"""
        router = BrokerRouter(default_broker=BrokerType.OKX)
        
        mock_connector = AsyncMock(spec=BrokerConnector)
        mock_result = OrderResult(
            order_id="test_123",
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
        mock_connector.place_order.return_value = mock_result
        router.register_connector(BrokerType.OKX, mock_connector)
        
        result = await router.place_order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
        )
        
        assert result.order_id == "test_123"
        mock_connector.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all(self):
        """測試關閉所有 connector"""
        router = BrokerRouter()
        
        mock_connector1 = AsyncMock(spec=BrokerConnector)
        mock_connector2 = AsyncMock(spec=BrokerConnector)
        
        router.register_connector(BrokerType.BINANCE, mock_connector1)
        router.register_connector(BrokerType.OKX, mock_connector2)
        
        await router.close_all()
        
        mock_connector1.close.assert_called_once()
        mock_connector2.close.assert_called_once()


class TestOkxOrderExecutor:
    """測試 OKX Order Executor"""

    def test_create_executor(self):
        """測試創建 OkxOrderExecutor"""
        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            testnet=True,
            dry_run=True,
        )
        executor = OkxOrderExecutor(config)
        assert executor._dry_run is True

    @pytest.mark.asyncio
    async def test_dry_run_place_order(self):
        """測試 dry-run 模式下單"""
        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            testnet=True,
            dry_run=True,
        )
        executor = OkxOrderExecutor(config)
        
        result = await executor.place_order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            price=50000.0,
        )
        
        assert result.order_id.startswith("okx_dryrun_")
        assert result.status == "FILLED"
        assert result.is_paper is False

    @pytest.mark.asyncio
    async def test_dry_run_cancel_order(self):
        """測試 dry-run 模式取消訂單"""
        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            testnet=True,
            dry_run=True,
        )
        executor = OkxOrderExecutor(config)
        
        result = await executor.cancel_order("BTC-USDT", "test_order_id")
        assert result is True

    @pytest.mark.asyncio
    async def test_convert_order_type(self):
        """測試訂單類型轉換"""
        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            testnet=True,
            dry_run=True,
        )
        executor = OkxOrderExecutor(config)
        
        assert executor._convert_order_type(OrderType.LIMIT) == "limit"
        assert executor._convert_order_type(OrderType.MARKET) == "market"
        assert executor._convert_order_type(OrderType.STOP_LIMIT) == "limit"
        assert executor._convert_order_type(OrderType.STOP_MARKET) == "market"

    @pytest.mark.asyncio
    async def test_convert_side(self):
        """測試買賣方向轉換"""
        config = BrokerConfig(
            broker_type=BrokerType.OKX,
            api_key="test_key",
            api_secret="test_secret",
            passphrase="test_passphrase",
            testnet=True,
            dry_run=True,
        )
        executor = OkxOrderExecutor(config)
        
        assert executor._convert_side(OrderSide.BUY) == "buy"
        assert executor._convert_side(OrderSide.SELL) == "sell"


class TestCreateExecutor:
    """測試 create_executor 工廠函數"""

    def test_create_paper_executor(self):
        """測試創建 paper executor"""
        executor = create_executor(mode=TradingMode.PAPER)
        assert executor is not None

    def test_create_okx_live_executor_with_missing_credentials(self):
        """測試創建 OKX live executor 缺少憑證"""
        with pytest.raises(ValueError, match="OKX_API_KEY"):
            create_executor(mode=TradingMode.OKX_LIVE)

    def test_create_okx_testnet_executor_with_missing_credentials(self):
        """測試創建 OKX testnet executor 缺少憑證"""
        with pytest.raises(ValueError, match="OKX_API_KEY"):
            create_executor(mode=TradingMode.OKX_TESTNET)

    @patch("vibe_trading.execution.order_executor.get_settings")
    def test_create_okx_live_executor_with_credentials(self, mock_get_settings):
        """測試創建 OKX live executor 有憑證"""
        mock_settings = MagicMock()
        mock_settings.okx_api_key = "test_key"
        mock_settings.okx_api_secret = "test_secret"
        mock_settings.okx_passphrase = "test_passphrase"
        mock_get_settings.return_value = mock_settings
        
        executor = create_executor(
            mode=TradingMode.OKX_LIVE,
            dry_run=True,
        )
        assert executor is not None
        assert isinstance(executor, OkxOrderExecutor)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
