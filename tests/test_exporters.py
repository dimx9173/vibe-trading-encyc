"""Tests for strategy exporters"""
import pytest
from vibe_trading.exporters import (
    ExportConfig,
    PineScriptExporter,
    MQL5Exporter,
    export_strategy,
)


@pytest.fixture
def sample_plan():
    """Sample trading plan for testing"""
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "leverage": 10,
        "max_loss_pct": 2.0,
        "entry_orders": [
            {"price": 50000.0, "pct": 50, "note": "First entry"},
            {"price": 49500.0, "pct": 50, "note": "Second entry"},
        ],
        "stop_loss_orders": [
            {"trigger_price": 48000.0, "note": "Stop loss"},
        ],
        "take_profit_orders": [
            {"price": 55000.0, "pct": 100, "note": "Take profit"},
        ],
    }


class TestPineScriptExporter:
    """Test Pine Script exporter"""

    def test_export_basic(self, sample_plan):
        """Test basic Pine Script export"""
        exporter = PineScriptExporter()
        result = exporter.export(sample_plan)

        assert "//@version=5" in result
        assert "strategy(" in result
        assert "BTCUSDT" in result or "50000" in result
        assert "input.float" in result

    def test_export_with_config(self, sample_plan):
        """Test export with custom config"""
        config = ExportConfig(
            strategy_name="TestStrategy",
            author="Test Author",
            version="2.0.0",
        )
        exporter = PineScriptExporter(config)
        result = exporter.export(sample_plan)

        assert "TestStrategy" in result
        assert "Test Author" in result

    def test_export_long_direction(self, sample_plan):
        """Test LONG direction export"""
        exporter = PineScriptExporter()
        result = exporter.export(sample_plan)

        assert "strategy.long" in result
        assert "long_condition" in result

    def test_export_short_direction(self):
        """Test SHORT direction export"""
        plan = {
            "symbol": "ETHUSDT",
            "direction": "SHORT",
            "leverage": 5,
            "max_loss_pct": 1.5,
            "entry_orders": [{"price": 3000.0, "pct": 100}],
            "stop_loss_orders": [{"trigger_price": 3100.0}],
            "take_profit_orders": [{"price": 2800.0}],
        }
        exporter = PineScriptExporter()
        result = exporter.export(plan)

        assert "strategy.short" in result
        assert "short_condition" in result

    def test_export_entry_orders(self, sample_plan):
        """Test entry orders export"""
        exporter = PineScriptExporter()
        result = exporter.export(sample_plan)

        assert "entry_price_1" in result
        assert "entry_price_2" in result
        assert "50000" in result
        assert "49500" in result

    def test_export_stop_loss(self, sample_plan):
        """Test stop loss export"""
        exporter = PineScriptExporter()
        result = exporter.export(sample_plan)

        assert "sl_price_1" in result
        assert "48000" in result
        assert "strategy.exit" in result

    def test_export_take_profit(self, sample_plan):
        """Test take profit export"""
        exporter = PineScriptExporter()
        result = exporter.export(sample_plan)

        assert "tp_price_1" in result
        assert "55000" in result


class TestMQL5Exporter:
    """Test MQL5 exporter"""

    def test_export_basic(self, sample_plan):
        """Test basic MQL5 export"""
        exporter = MQL5Exporter()
        result = exporter.export(sample_plan)

        assert "#property copyright" in result
        assert "#property version" in result
        assert "#include <Trade\\Trade.mqh>" in result
        assert "int OnInit()" in result
        assert "void OnTick()" in result

    def test_export_with_config(self, sample_plan):
        """Test export with custom config"""
        config = ExportConfig(
            strategy_name="MT5Strategy",
            author="MT5 Author",
            version="3.0.0",
        )
        exporter = MQL5Exporter(config)
        result = exporter.export(sample_plan)

        assert "MT5Strategy.mq5" in result
        assert "MT5 Author" in result
        assert "3.0.0" in result

    def test_export_inputs(self, sample_plan):
        """Test input parameters export"""
        exporter = MQL5Exporter()
        result = exporter.export(sample_plan)

        assert "input int Leverage" in result
        assert "input double RiskPercent" in result
        assert "input double EntryPrice1" in result
        assert "input double SLPrice1" in result
        assert "input double TPPrice1" in result

    def test_export_lot_size_calculation(self, sample_plan):
        """Test lot size calculation function"""
        exporter = MQL5Exporter()
        result = exporter.export(sample_plan)

        assert "CalculateLotSize" in result
        assert "AccountInfoDouble" in result
        assert "SymbolInfoDouble" in result

    def test_export_position_management(self, sample_plan):
        """Test position management function"""
        exporter = MQL5Exporter()
        result = exporter.export(sample_plan)

        assert "ManagePosition" in result
        assert "PositionSelect" in result
        assert "trade.PositionModify" in result

    def test_export_long_direction(self, sample_plan):
        """Test LONG direction export"""
        exporter = MQL5Exporter()
        result = exporter.export(sample_plan)

        assert "trade.Buy" in result
        assert "Vibe Trading Long" in result

    def test_export_short_direction(self):
        """Test SHORT direction export"""
        plan = {
            "symbol": "ETHUSDT",
            "direction": "SHORT",
            "leverage": 5,
            "max_loss_pct": 1.5,
            "entry_orders": [{"price": 3000.0}],
            "stop_loss_orders": [{"trigger_price": 3100.0}],
            "take_profit_orders": [{"price": 2800.0}],
        }
        exporter = MQL5Exporter()
        result = exporter.export(plan)

        assert "trade.Sell" in result
        assert "Vibe Trading Short" in result


class TestExportStrategy:
    """Test export_strategy function"""

    def test_export_pine(self, sample_plan):
        """Test exporting to Pine Script"""
        result = export_strategy(sample_plan, "pine")
        assert "//@version=5" in result

    def test_export_mql5(self, sample_plan):
        """Test exporting to MQL5"""
        result = export_strategy(sample_plan, "mql5")
        assert "#property copyright" in result

    def test_export_case_insensitive(self, sample_plan):
        """Test case insensitive format"""
        result1 = export_strategy(sample_plan, "PINE")
        result2 = export_strategy(sample_plan, "pine")
        assert result1 == result2

    def test_export_unsupported_format(self, sample_plan):
        """Test unsupported format raises error"""
        with pytest.raises(ValueError, match="Unsupported export format"):
            export_strategy(sample_plan, "unsupported")

    def test_export_with_config(self, sample_plan):
        """Test export with custom config"""
        config = ExportConfig(strategy_name="CustomStrategy")
        result = export_strategy(sample_plan, "pine", config)
        assert "CustomStrategy" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
