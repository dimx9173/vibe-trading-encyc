"""
Technical Indicator Engine

Calculates technical indicators from K-line data:
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Bollinger Bands
- Moving Averages (SMA, EMA)
- ATR (Average True Range)
- Volume indicators

All calculations work with both live and historical data.
"""
from typing import Dict, List
from ..base import Kline


class TechnicalAnalyzer:
    """Technical indicator calculator"""
    
    @staticmethod
    def calculate(klines: List[Kline]) -> Dict[str, float]:
        """Calculate all technical indicators"""
        if len(klines) < 30:
            return {}
        
        closes = [k.close for k in klines]
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]
        volumes = [k.volume for k in klines]
        
        return {
            "rsi_14": TechnicalAnalyzer._calculate_rsi(closes, 14),
            "macd": TechnicalAnalyzer._calculate_macd(closes),
            "macd_signal": TechnicalAnalyzer._calculate_macd_signal(closes),
            "bollinger_upper": TechnicalAnalyzer._calculate_bollinger_upper(closes),
            "bollinger_middle": TechnicalAnalyzer._calculate_bollinger_middle(closes),
            "bollinger_lower": TechnicalAnalyzer._calculate_bollinger_lower(closes),
            "sma_20": TechnicalAnalyzer._calculate_sma(closes, 20),
            "sma_50": TechnicalAnalyzer._calculate_sma(closes, 50),
            "ema_12": TechnicalAnalyzer._calculate_ema(closes, 12),
            "ema_26": TechnicalAnalyzer._calculate_ema(closes, 26),
            "atr_14": TechnicalAnalyzer._calculate_atr(highs, lows, closes, 14),
            "volume_sma_20": TechnicalAnalyzer._calculate_sma(volumes, 20),
        }
    
    @staticmethod
    def _calculate_sma(data: List[float], period: int) -> float:
        """Simple Moving Average"""
        if len(data) < period:
            return 0.0
        return sum(data[-period:]) / period
    
    @staticmethod
    def _calculate_ema(data: List[float], period: int) -> float:
        """Exponential Moving Average"""
        if len(data) < period:
            return 0.0
        
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    @staticmethod
    def _calculate_rsi(closes: List[float], period: int = 14) -> float:
        """Relative Strength Index"""
        if len(closes) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def _calculate_macd(closes: List[float]) -> float:
        """MACD Line"""
        if len(closes) < 26:
            return 0.0
        
        ema_12 = TechnicalAnalyzer._calculate_ema(closes, 12)
        ema_26 = TechnicalAnalyzer._calculate_ema(closes, 26)
        
        return ema_12 - ema_26
    
    @staticmethod
    def _calculate_macd_signal(closes: List[float]) -> float:
        """MACD Signal Line (simplified)"""
        if len(closes) < 35:
            return 0.0
        
        # Calculate MACD values
        macd_values = []
        for i in range(26, len(closes) + 1):
            ema_12 = TechnicalAnalyzer._calculate_ema(closes[:i], 12)
            ema_26 = TechnicalAnalyzer._calculate_ema(closes[:i], 26)
            macd_values.append(ema_12 - ema_26)
        
        if len(macd_values) < 9:
            return 0.0
        
        return TechnicalAnalyzer._calculate_ema(macd_values, 9)
    
    @staticmethod
    def _calculate_bollinger_middle(closes: List[float], period: int = 20) -> float:
        """Bollinger Band Middle (SMA)"""
        return TechnicalAnalyzer._calculate_sma(closes, period)
    
    @staticmethod
    def _calculate_bollinger_upper(closes: List[float], period: int = 20, std_dev: float = 2.0) -> float:
        """Bollinger Band Upper"""
        if len(closes) < period:
            return 0.0
        
        middle = TechnicalAnalyzer._calculate_sma(closes, period)
        variance = sum((x - middle) ** 2 for x in closes[-period:]) / period
        std = variance ** 0.5
        
        return middle + (std_dev * std)
    
    @staticmethod
    def _calculate_bollinger_lower(closes: List[float], period: int = 20, std_dev: float = 2.0) -> float:
        """Bollinger Band Lower"""
        if len(closes) < period:
            return 0.0
        
        middle = TechnicalAnalyzer._calculate_sma(closes, period)
        variance = sum((x - middle) ** 2 for x in closes[-period:]) / period
        std = variance ** 0.5
        
        return middle - (std_dev * std)
    
    @staticmethod
    def _calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Average True Range"""
        if len(highs) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return 0.0
        
        return sum(true_ranges[-period:]) / period
