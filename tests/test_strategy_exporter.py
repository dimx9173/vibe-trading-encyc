"""
Tests for P3 Strategy Exporter and Templates

Tests for:
- Strategy templates
- Pine Script exporter
- MQL5 exporter
- Template library
"""
import pytest
from typing import Dict, Any

from vibe_trading.exporters.strategy_exporter import (
    PineScriptExporter, MQL5Exporter, ExportConfig, export_strategy
)
from vibe_trading.exporters.templates import (
    StrategyTemplateLibrary, StrategyType, get_template_library
)


# ============================================================================
# Template Tests
# ============================================================================

class TestStrategyTemplates:
    """Strategy template tests"""
    
    def test_get_template_library(self):
        """Test getting template library"""
        library = get_template_library()
        
        assert library is not None
        assert len(library.get_all_templates()) > 0
    
    def test_get_default_templates(self):
        """Test getting default templates"""
        library = get_template_library()
        
        # Should have 4 default templates
        templates = library.get_all_templates()
        
        assert len(templates) == 4
        
        # Check template names
        template_names = [t.name for t in templates]
        
        assert "Trend Following" in template_names
        assert "Mean Reversion" in template_names
        assert "Breakout" in template_names
        assert "Momentum" in template_names
    
    def test_get_template_by_name(self):
        """Test getting a specific template"""
        library = get_template_library()
        
        template = library.get_template("trend_following")
        
        assert template is not None
        assert template.name == "Trend Following"
        assert template.type == StrategyType.TREND_FOLLOWING
    
    def test_get_nonexistent_template(self):
        """Test getting a nonexistent template"""
        library = get_template_library()
        
        template = library.get_template("nonexistent")
        
        assert template is None
    
    def test_create_custom_template(self):
        """Test creating a custom template"""
        library = get_template_library()
        
        template = library.create_custom_template(
            name="Custom Strategy",
            description="A custom strategy",
            indicators=["rsi", "macd"],
            entry_conditions=["RSI < 30"],
            exit_conditions=["RSI > 70"],
            risk_management={"stop_loss_pct": 2.0},
            parameters={"rsi_period": 14}
        )
        
        assert template is not None
        assert template.name == "Custom Strategy"
        assert template.type == StrategyType.CUSTOM
        
        # Should be retrievable
        retrieved = library.get_template("custom_strategy")
        
        assert retrieved is not None
        assert retrieved.name == "Custom Strategy"
    
    def test_template_to_dict(self):
        """Test template serialization"""
        library = get_template_library()
        
        template = library.get_template("trend_following")
        
        data = template.to_dict()
        
        assert data["name"] == "Trend Following"
        assert data["type"] == "trend_following"
        assert "indicators" in data
        assert "entry_conditions" in data
        assert "exit_conditions" in data


# ============================================================================
# Pine Script Exporter Tests
# ============================================================================

class TestPineScriptExporter:
    """Pine Script exporter tests"""
    
    def test_export_basic_plan(self):
        """Test exporting a basic trading plan"""
        exporter = PineScriptExporter()
        
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": ["rsi_14", "macd"],
            "entry_conditions": ["RSI < 30", "MACD > 0"],
            "exit_conditions": ["RSI > 70"],
            "risk_management": {
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0
            },
            "parameters": {
                "rsi_period": 14
            }
        }
        
        result = exporter.export(plan)
        
        assert "//@version=5" in result
        assert "strategy(" in result
        assert "Strategy Logic" in result
    
    def test_export_with_config(self):
        """Test exporting with custom config"""
        config = ExportConfig(
            strategy_name="Test Strategy",
            author="Test Author",
            version="2.0.0"
        )
        
        exporter = PineScriptExporter(config)
        
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": [],
            "entry_conditions": [],
            "exit_conditions": [],
            "risk_management": {},
            "parameters": {}
        }
        
        result = exporter.export(plan)
        
        assert "Test Strategy" in result
        assert "Test Author" in result


# ============================================================================
# MQL5 Exporter Tests
# ============================================================================

class TestMQL5Exporter:
    """MQL5 exporter tests"""
    
    def test_export_basic_plan(self):
        """Test exporting a basic trading plan to MQL5"""
        exporter = MQL5Exporter()
        
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": ["rsi_14", "macd"],
            "entry_conditions": ["RSI < 30"],
            "exit_conditions": ["RSI > 70"],
            "risk_management": {
                "stop_loss_pct": 2.0
            },
            "parameters": {}
        }
        
        result = exporter.export(plan)
        
        assert "//+------------------------------------------------------------------+" in result
        assert "input" in result
        assert "OnInit" in result
        assert "OnTick" in result
    
    def test_export_with_config(self):
        """Test exporting with custom config"""
        config = ExportConfig(
            strategy_name="MQL5 Test",
            author="Test Author"
        )
        
        exporter = MQL5Exporter(config)
        
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": [],
            "entry_conditions": [],
            "exit_conditions": [],
            "risk_management": {},
            "parameters": {}
        }
        
        result = exporter.export(plan)
        
        assert "MQL5 Test" in result


# ============================================================================
# Export Strategy Function Tests
# ============================================================================

class TestExportStrategy:
    """Export strategy function tests"""
    
    def test_export_to_pine(self):
        """Test exporting to Pine Script format"""
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": [],
            "entry_conditions": [],
            "exit_conditions": [],
            "risk_management": {},
            "parameters": {}
        }
        
        result = export_strategy(plan, "pine")
        
        assert "//@version=5" in result
    
    def test_export_to_mql5(self):
        """Test exporting to MQL5 format"""
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": [],
            "entry_conditions": [],
            "exit_conditions": [],
            "risk_management": {},
            "parameters": {}
        }
        
        result = export_strategy(plan, "mql5")
        
        assert "OnInit" in result
    
    def test_export_unsupported_format(self):
        """Test exporting to unsupported format"""
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": [],
            "entry_conditions": [],
            "exit_conditions": [],
            "risk_management": {},
            "parameters": {}
        }
        
        with pytest.raises(ValueError):
            export_strategy(plan, "unsupported")


# ============================================================================
# Template Export Tests
# ============================================================================

class TestTemplateExport:
    """Template export tests"""
    
    def test_export_template_to_pine(self):
        """Test exporting a template to Pine Script"""
        library = get_template_library()
        
        result = library.export_template("trend_following", "pine")
        
        assert "//@version=5" in result
        assert "Trend Following" in result
    
    def test_export_template_to_mql5(self):
        """Test exporting a template to MQL5"""
        library = get_template_library()
        
        result = library.export_template("trend_following", "mql5")
        
        assert "OnInit" in result
        assert "Trend Following" in result
    
    def test_export_nonexistent_template(self):
        """Test exporting a nonexistent template"""
        library = get_template_library()
        
        result = library.export_template("nonexistent", "pine")
        
        assert "Error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
