"""Strategy exporters - Convert TradingPlan to Pine Script and MQL5"""
from __future__ import annotations

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ExportConfig:
    """Configuration for strategy export"""
    strategy_name: str = "VibeTradingStrategy"
    author: str = "Vibe Trading"
    version: str = "1.0.0"
    include_comments: bool = True
    risk_per_trade: float = 1.0  # percentage


class PineScriptExporter:
    """Export TradingPlan to Pine Script v5 for TradingView"""

    def __init__(self, config: Optional[ExportConfig] = None):
        self.config = config or ExportConfig()

    def export(self, plan: Dict) -> str:
        """Export trading plan to Pine Script"""
        lines = [
            "//@version=5",
            f"// Author: {self.config.author}",
            f"// Version: {self.config.version}",
            f'strategy("{self.config.strategy_name}", overlay=true, ',
            "         default_qty_type=strategy.percent_of_equity, ",
            "         default_qty_value=100, ",
            "         commission_type=strategy.commission.percent, ",
            "         commission_value=0.1)",
            "",
        ]

        # Inputs
        lines.extend(self._generate_inputs(plan))
        lines.append("")

        # Strategy logic
        lines.extend(self._generate_strategy_logic(plan))
        lines.append("")

        # Plotting
        lines.extend(self._generate_plotting(plan))

        return "\n".join(lines)

    def _generate_inputs(self, plan: Dict) -> List[str]:
        """Generate Pine Script input declarations"""
        lines = [
            "// === Input Parameters ===",
            f"leverage = input.int({plan.get('leverage', 1)}, title=\"Leverage\", minval=1, maxval=125)",
            f"risk_pct = input.float({plan.get('max_loss_pct', 2.0)}, title=\"Risk %\", minval=0.1, maxval=100.0) / 100",
            "",
        ]

        # Entry orders
        entry_orders = plan.get('entry_orders', [])
        if entry_orders:
            lines.append("// Entry Orders")
            for i, order in enumerate(entry_orders, 1):
                price = order.get('price', 0)
                pct = order.get('pct', 100)
                lines.append(f"entry_price_{i} = input.float({price}, title=\"Entry {i} Price\")")
                lines.append(f"entry_pct_{i} = input.float({pct}, title=\"Entry {i} %\")")

        # Stop loss
        sl_orders = plan.get('stop_loss_orders', [])
        if sl_orders:
            lines.append("")
            lines.append("// Stop Loss")
            for i, sl in enumerate(sl_orders, 1):
                price = sl.get('trigger_price', 0)
                lines.append(f"sl_price_{i} = input.float({price}, title=\"SL {i} Price\")")

        # Take profit
        tp_orders = plan.get('take_profit_orders', [])
        if tp_orders:
            lines.append("")
            lines.append("// Take Profit")
            for i, tp in enumerate(tp_orders, 1):
                price = tp.get('price', 0)
                lines.append(f"tp_price_{i} = input.float({price}, title=\"TP {i} Price\")")

        return lines

    def _generate_strategy_logic(self, plan: Dict) -> List[str]:
        """Generate Pine Script strategy logic"""
        direction = plan.get('direction', 'LONG')
        lines = [
            "// === Strategy Logic ===",
            f"// Direction: {direction}",
            "",
            "// Entry conditions (placeholder - customize based on your strategy)",
            "long_condition = ta.crossover(ta.sma(close, 14), ta.sma(close, 28))",
            "short_condition = ta.crossunder(ta.sma(close, 14), ta.sma(close, 28))",
            "",
        ]

        if direction == 'LONG':
            lines.extend([
                "if long_condition",
                "    strategy.entry(\"Long\", strategy.long)",
                "",
            ])
        else:
            lines.extend([
                "if short_condition",
                "    strategy.entry(\"Short\", strategy.short)",
                "",
            ])

        # Exit conditions
        lines.extend([
            "// Exit conditions",
            "if strategy.position_size > 0",
        ])

        sl_orders = plan.get('stop_loss_orders', [])
        if sl_orders:
            sl_price = sl_orders[0].get('trigger_price', 0)
            lines.append(f"    strategy.exit(\"SL\", from_entry=\"Long\", stop={sl_price})")

        tp_orders = plan.get('take_profit_orders', [])
        if tp_orders:
            tp_price = tp_orders[0].get('price', 0)
            lines.append(f"    strategy.exit(\"TP\", from_entry=\"Long\", limit={tp_price})")

        lines.append("")

        return lines

    def _generate_plotting(self, plan: Dict) -> List[str]:
        """Generate Pine Script plotting code"""
        lines = [
            "// === Plotting ===",
            "plot(strategy.position_avg_price, title=\"Position Avg Price\", color=color.blue, linewidth=2)",
        ]

        sl_orders = plan.get('stop_loss_orders', [])
        if sl_orders:
            sl_price = sl_orders[0].get('trigger_price', 0)
            lines.append(f"plot({sl_price}, title=\"Stop Loss\", color=color.red, linewidth=2, style=plot.style_linebr)")

        tp_orders = plan.get('take_profit_orders', [])
        if tp_orders:
            tp_price = tp_orders[0].get('price', 0)
            lines.append(f"plot({tp_price}, title=\"Take Profit\", color=color.green, linewidth=2, style=plot.style_linebr)")

        return lines


class MQL5Exporter:
    """Export TradingPlan to MQL5 for MetaTrader 5"""

    def __init__(self, config: Optional[ExportConfig] = None):
        self.config = config or ExportConfig()

    def export(self, plan: Dict) -> str:
        """Export trading plan to MQL5"""
        lines = [
            "//+------------------------------------------------------------------+",
            f"//| {self.config.strategy_name}.mq5",
            f"//| {self.config.author}",
            f"//| Version {self.config.version}",
            "//+------------------------------------------------------------------+",
            f"#property copyright \"{self.config.author}\"",
            f"#property version   \"{self.config.version}\"",
            "#property strict",
            "",
            "#include <Trade\\Trade.mqh>",
            "",
        ]

        # Input parameters
        lines.extend(self._generate_inputs(plan))
        lines.append("")

        # Global variables
        lines.extend(self._generate_globals(plan))
        lines.append("")

        # OnInit
        lines.extend(self._generate_oninit())
        lines.append("")

        # OnTick
        lines.extend(self._generate_ontick(plan))
        lines.append("")

        # Helper functions
        lines.extend(self._generate_helpers(plan))

        return "\n".join(lines)

    def _generate_inputs(self, plan: Dict) -> List[str]:
        """Generate MQL5 input parameters"""
        lines = [
            "// === Input Parameters ===",
            f"input int Leverage = {plan.get('leverage', 1)};  // Leverage",
            f"input double RiskPercent = {plan.get('max_loss_pct', 2.0)};  // Risk %",
            "",
        ]

        # Entry orders
        entry_orders = plan.get('entry_orders', [])
        if entry_orders:
            lines.append("// Entry Orders")
            for i, order in enumerate(entry_orders, 1):
                price = order.get('price', 0)
                lines.append(f"input double EntryPrice{i} = {price};  // Entry {i} Price")

        # Stop loss
        sl_orders = plan.get('stop_loss_orders', [])
        if sl_orders:
            lines.append("")
            lines.append("// Stop Loss")
            for i, sl in enumerate(sl_orders, 1):
                price = sl.get('trigger_price', 0)
                lines.append(f"input double SLPrice{i} = {price};  // SL {i} Price")

        # Take profit
        tp_orders = plan.get('take_profit_orders', [])
        if tp_orders:
            lines.append("")
            lines.append("// Take Profit")
            for i, tp in enumerate(tp_orders, 1):
                price = tp.get('price', 0)
                lines.append(f"input double TPPrice{i} = {price};  // TP {i} Price")

        return lines

    def _generate_globals(self, plan: Dict) -> List[str]:
        """Generate MQL5 global variables"""
        return [
            "// === Global Variables ===",
            "CTrade trade;",
            "int ma_fast_handle;",
            "int ma_slow_handle;",
        ]

    def _generate_oninit(self) -> List[str]:
        """Generate MQL5 OnInit function"""
        return [
            "//+------------------------------------------------------------------+",
            "//| Expert initialization function                                   |",
            "//+------------------------------------------------------------------+",
            "int OnInit()",
            "{",
            "   // Initialize indicators",
            "   ma_fast_handle = iMA(_Symbol, PERIOD_CURRENT, 14, 0, MODE_SMA, PRICE_CLOSE);",
            "   ma_slow_handle = iMA(_Symbol, PERIOD_CURRENT, 28, 0, MODE_SMA, PRICE_CLOSE);",
            "",
            "   if(ma_fast_handle == INVALID_HANDLE || ma_slow_handle == INVALID_HANDLE)",
            "   {",
            "      Print(\"Error creating indicator handles\");",
            "      return(INIT_FAILED);",
            "   }",
            "",
            "   trade.SetExpertMagicNumber(123456);",
            "   trade.SetDeviationInPoints(10);",
            "",
            "   return(INIT_SUCCEEDED);",
            "}",
        ]

    def _generate_ontick(self, plan: Dict) -> List[str]:
        """Generate MQL5 OnTick function"""
        direction = plan.get('direction', 'LONG')

        lines = [
            "//+------------------------------------------------------------------+",
            "//| Expert tick function                                             |",
            "//+------------------------------------------------------------------+",
            "void OnTick()",
            "{",
            "   // Get indicator values",
            "   double ma_fast[], ma_slow[];",
            "   ArraySetAsSeries(ma_fast, true);",
            "   ArraySetAsSeries(ma_slow, true);",
            "",
            "   if(CopyBuffer(ma_fast_handle, 0, 0, 3, ma_fast) < 3) return;",
            "   if(CopyBuffer(ma_slow_handle, 0, 0, 3, ma_slow) < 3) return;",
            "",
            "   // Check for existing positions",
            "   if(PositionSelect(_Symbol))",
            "   {",
            "      // Manage existing position",
            "      ManagePosition();",
            "      return;",
            "   }",
            "",
        ]

        if direction == 'LONG':
            lines.extend([
                "   // Entry condition for LONG",
                "   if(ma_fast[1] > ma_slow[1] && ma_fast[2] <= ma_slow[2])",
                "   {",
                "      double lot_size = CalculateLotSize(RiskPercent);",
                "      trade.Buy(lot_size, _Symbol, 0, 0, 0, \"Vibe Trading Long\");",
                "   }",
                "",
            ])
        else:
            lines.extend([
                "   // Entry condition for SHORT",
                "   if(ma_fast[1] < ma_slow[1] && ma_fast[2] >= ma_slow[2])",
                "   {",
                "      double lot_size = CalculateLotSize(RiskPercent);",
                "      trade.Sell(lot_size, _Symbol, 0, 0, 0, \"Vibe Trading Short\");",
                "   }",
                "",
            ])

        lines.append("}")

        return lines

    def _generate_helpers(self, plan: Dict) -> List[str]:
        """Generate MQL5 helper functions"""
        lines = [
            "//+------------------------------------------------------------------+",
            "//| Calculate lot size based on risk                                 |",
            "//+------------------------------------------------------------------+",
            "double CalculateLotSize(double risk_percent)",
            "{",
            "   double balance = AccountInfoDouble(ACCOUNT_BALANCE);",
            "   double risk_amount = balance * risk_percent / 100.0;",
            "   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);",
            "   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);",
            "",
            "   if(tick_value == 0 || tick_size == 0) return 0.01;",
            "",
            "   double lot_size = risk_amount / (tick_value / tick_size);",
            "   lot_size = NormalizeDouble(lot_size, 2);",
            "",
            "   double min_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);",
            "   double max_lot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);",
            "",
            "   if(lot_size < min_lot) lot_size = min_lot;",
            "   if(lot_size > max_lot) lot_size = max_lot;",
            "",
            "   return lot_size;",
            "}",
            "",
            "//+------------------------------------------------------------------+",
            "//| Manage existing position                                         |",
            "//+------------------------------------------------------------------+",
            "void ManagePosition()",
            "{",
        ]

        sl_orders = plan.get('stop_loss_orders', [])
        if sl_orders:
            sl_price = sl_orders[0].get('trigger_price', 0)
            lines.append(f"   double sl_price = {sl_price};")

        tp_orders = plan.get('take_profit_orders', [])
        if tp_orders:
            tp_price = tp_orders[0].get('price', 0)
            lines.append(f"   double tp_price = {tp_price};")

        lines.extend([
            "",
            "   ulong ticket = PositionGetInteger(POSITION_TICKET);",
            "   if(ticket > 0)",
            "   {",
        ])

        if sl_orders:
            lines.append("      trade.PositionModify(ticket, sl_price, PositionGetDouble(POSITION_TP));")
        if tp_orders:
            lines.append("      trade.PositionModify(ticket, PositionGetDouble(POSITION_SL), tp_price);")

        lines.extend([
            "   }",
            "}",
        ])

        return lines


def export_strategy(plan: Dict, format: str, config: Optional[ExportConfig] = None) -> str:
    """Export trading plan to specified format"""
    if format.lower() == 'pine':
        exporter = PineScriptExporter(config)
    elif format.lower() == 'mql5':
        exporter = MQL5Exporter(config)
    else:
        raise ValueError(f"Unsupported export format: {format}. Supported: pine, mql5")

    return exporter.export(plan)
