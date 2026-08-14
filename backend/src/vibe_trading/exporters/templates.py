"""
Strategy Template System

Provides reusable templates for strategy export:
- Pre-defined strategy templates (trend following, mean reversion, breakout)
- Customizable parameters
- Multi-format export (Pine Script, MQL5)
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class StrategyType(str, Enum):
    """Pre-defined strategy types"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    CUSTOM = "custom"


@dataclass
class StrategyTemplate:
    """Strategy template with pre-configured parameters"""
    name: str
    type: StrategyType
    description: str
    indicators: List[str] = field(default_factory=list)
    entry_conditions: List[str] = field(default_factory=list)
    exit_conditions: List[str] = field(default_factory=list)
    risk_management: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "indicators": self.indicators,
            "entry_conditions": self.entry_conditions,
            "exit_conditions": self.exit_conditions,
            "risk_management": self.risk_management,
            "parameters": self.parameters,
        }


class StrategyTemplateLibrary:
    """Library of pre-defined strategy templates"""
    
    def __init__(self):
        self.templates: Dict[str, StrategyTemplate] = {}
        self._load_default_templates()
    
    def _load_default_templates(self):
        """Load built-in strategy templates"""
        
        # Trend Following Strategy
        self.templates["trend_following"] = StrategyTemplate(
            name="Trend Following",
            type=StrategyType.TREND_FOLLOWING,
            description="Follows major trends using moving averages and momentum indicators",
            indicators=["sma_20", "sma_50", "rsi_14", "macd"],
            entry_conditions=[
                "SMA_20 > SMA_50 (uptrend)",
                "RSI > 50 (momentum)",
                "MACD > 0 (bullish)"
            ],
            exit_conditions=[
                "SMA_20 < SMA_50 (downtrend)",
                "RSI < 30 (oversold reversal)"
            ],
            risk_management={
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
                "trailing_stop": True
            },
            parameters={
                "sma_fast": 20,
                "sma_slow": 50,
                "rsi_period": 14
            }
        )
        
        # Mean Reversion Strategy
        self.templates["mean_reversion"] = StrategyTemplate(
            name="Mean Reversion",
            type=StrategyType.MEAN_REVERSION,
            description="Trades price deviations from mean using Bollinger Bands and RSI",
            indicators=["bollinger_bands", "rsi_14", "sma_20"],
            entry_conditions=[
                "Price < Lower Bollinger Band",
                "RSI < 30 (oversold)"
            ],
            exit_conditions=[
                "Price > Middle Bollinger Band",
                "RSI > 70 (overbought)"
            ],
            risk_management={
                "stop_loss_pct": 1.5,
                "take_profit_pct": 3.0,
                "position_size_pct": 2.0
            },
            parameters={
                "bb_period": 20,
                "bb_std": 2.0,
                "rsi_period": 14
            }
        )
        
        # Breakout Strategy
        self.templates["breakout"] = StrategyTemplate(
            name="Breakout",
            type=StrategyType.BREAKOUT,
            description="Trades breakouts from consolidation with volume confirmation",
            indicators=["atr_14", "volume_sma_20", "price_channels"],
            entry_conditions=[
                "Price > Upper Channel",
                "Volume > 1.5x Average Volume",
                "ATR expanding"
            ],
            exit_conditions=[
                "Price < Lower Channel",
                "Volume drops below average"
            ],
            risk_management={
                "stop_loss_pct": 2.5,
                "take_profit_pct": 5.0,
                "breakout_buffer_pct": 0.5
            },
            parameters={
                "channel_period": 20,
                "volume_period": 20,
                "atr_period": 14
            }
        )
        
        # Momentum Strategy
        self.templates["momentum"] = StrategyTemplate(
            name="Momentum",
            type=StrategyType.MOMENTUM,
            description="Trades strong momentum with RSI and MACD confirmation",
            indicators=["rsi_14", "macd", "momentum_12_1"],
            entry_conditions=[
                "RSI > 60 (strong momentum)",
                "MACD > Signal line",
                "Momentum > 0"
            ],
            exit_conditions=[
                "RSI < 40 (momentum fading)",
                "MACD < Signal line"
            ],
            risk_management={
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
                "trailing_stop": True
            },
            parameters={
                "rsi_period": 14,
                "macd_fast": 12,
                "macd_slow": 26,
                "momentum_period": 12
            }
        )
    
    def get_template(self, name: str) -> Optional[StrategyTemplate]:
        """Get a template by name"""
        return self.templates.get(name)
    
    def get_all_templates(self) -> List[StrategyTemplate]:
        """Get all available templates"""
        return list(self.templates.values())
    
    def get_templates_by_type(self, strategy_type: StrategyType) -> List[StrategyTemplate]:
        """Get templates by strategy type"""
        return [t for t in self.templates.values() if t.type == strategy_type]
    
    def create_custom_template(
        self,
        name: str,
        description: str,
        indicators: List[str],
        entry_conditions: List[str],
        exit_conditions: List[str],
        risk_management: Dict[str, Any],
        parameters: Dict[str, Any]
    ) -> StrategyTemplate:
        """Create a custom strategy template"""
        template = StrategyTemplate(
            name=name,
            type=StrategyType.CUSTOM,
            description=description,
            indicators=indicators,
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            risk_management=risk_management,
            parameters=parameters
        )
        
        self.templates[name.lower().replace(" ", "_")] = template
        return template
    
    def export_template(self, template_name: str, format: str) -> str:
        """Export a template to specified format"""
        template = self.get_template(template_name)
        if not template:
            return f"Error: Template '{template_name}' not found"
        
        # Convert template to trading plan format
        plan = {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "indicators": template.indicators,
            "entry_conditions": template.entry_conditions,
            "exit_conditions": template.exit_conditions,
            "risk_management": template.risk_management,
            "parameters": template.parameters,
        }
        
        from .strategy_exporter import export_strategy, ExportConfig
        
        config = ExportConfig(
            strategy_name=template.name,
            author="Vibe Trading Template"
        )
        
        return export_strategy(plan, format, config)


# Global template library instance
_template_library: Optional[StrategyTemplateLibrary] = None


def get_template_library() -> StrategyTemplateLibrary:
    """Get global template library instance"""
    global _template_library
    if _template_library is None:
        _template_library = StrategyTemplateLibrary()
    return _template_library
