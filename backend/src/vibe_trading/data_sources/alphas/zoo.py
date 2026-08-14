"""
Alpha Zoo

Provides 23 pre-configured alpha factors across 4 categories:
- Momentum (6 factors)
- Volatility (6 factors)
- Volume (6 factors)
- Mean Reversion (5 factors)

All factors work with standardized K-line data.
"""
from typing import Dict, List
from ..base import Kline
from ..indicators.technical import TechnicalAnalyzer


class AlphaZoo:
    """Alpha factor calculator"""
    
    # Factor definitions
    MOMENTUM_FACTORS = [
        "momentum_12_1",
        "momentum_weighted",
        "rate_of_change",
        "price_distance",
        "trend_strength",
        "macd_histogram",
    ]
    
    VOLATILITY_FACTORS = [
        "realized_volatility",
        "volatility_ratio",
        "parkinson_volatility",
        "garman_klass_volatility",
        "atr",
        "volatility_skew",
    ]
    
    VOLUME_FACTORS = [
        "volume_ratio",
        "obv",
        "vwap",
        "volume_price_trend",
        "money_flow_index",
        "volume_volatility",
    ]
    
    MEAN_REVERSION_FACTORS = [
        "rsi_zscore",
        "bollinger_band_width",
        "price_to_ma",
        "stochastic_oscillator",
        "cci",
    ]
    
    ALL_FACTORS = (
        MOMENTUM_FACTORS + 
        VOLATILITY_FACTORS + 
        VOLUME_FACTORS + 
        MEAN_REVERSION_FACTORS
    )
    
    @staticmethod
    def calculate(klines: List[Kline]) -> Dict[str, float]:
        """Calculate all alpha factors"""
        if len(klines) < 50:
            return {}
        
        closes = [k.close for k in klines]
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]
        volumes = [k.volume for k in klines]
        
        # Calculate technical indicators first
        indicators = TechnicalAnalyzer.calculate(klines)
        
        factors = {}
        
        # Momentum factors
        factors["momentum_12_1"] = AlphaZoo._momentum_12_1(closes)
        factors["momentum_weighted"] = AlphaZoo._momentum_weighted(closes)
        factors["rate_of_change"] = AlphaZoo._rate_of_change(closes, 12)
        factors["price_distance"] = AlphaZoo._price_distance(closes)
        factors["trend_strength"] = AlphaZoo._trend_strength(closes)
        factors["macd_histogram"] = indicators.get("macd", 0) - indicators.get("macd_signal", 0)
        
        # Volatility factors
        factors["realized_volatility"] = AlphaZoo._realized_volatility(closes)
        factors["volatility_ratio"] = AlphaZoo._volatility_ratio(closes)
        factors["parkinson_volatility"] = AlphaZoo._parkinson_volatility(highs, lows)
        factors["garman_klass_volatility"] = AlphaZoo._garman_klass_volatility(highs, lows, closes)
        factors["atr"] = indicators.get("atr_14", 0)
        factors["volatility_skew"] = AlphaZoo._volatility_skew(closes)
        
        # Volume factors
        factors["volume_ratio"] = AlphaZoo._volume_ratio(volumes)
        factors["obv"] = AlphaZoo._obv(closes, volumes)
        factors["vwap"] = AlphaZoo._vwap(highs, lows, closes, volumes)
        factors["volume_price_trend"] = AlphaZoo._volume_price_trend(closes, volumes)
        factors["money_flow_index"] = AlphaZoo._money_flow_index(highs, lows, closes, volumes)
        factors["volume_volatility"] = AlphaZoo._volume_volatility(volumes)
        
        # Mean reversion factors
        factors["rsi_zscore"] = AlphaZoo._rsi_zscore(indicators.get("rsi_14", 50))
        factors["bollinger_band_width"] = AlphaZoo._bollinger_band_width(indicators)
        factors["price_to_ma"] = AlphaZoo._price_to_ma(closes, indicators.get("sma_20", 0))
        factors["stochastic_oscillator"] = AlphaZoo._stochastic_oscillator(highs, lows, closes)
        factors["cci"] = AlphaZoo._cci(highs, lows, closes)
        
        return factors
    
    # ========================================================================
    # Momentum Factors
    # ========================================================================
    
    @staticmethod
    def _momentum_12_1(closes: List[float]) -> float:
        """12-1 Momentum: (close - close[12]) / close[12] - (close - close[1]) / close[1]"""
        if len(closes) < 13:
            return 0.0
        
        momentum_12 = (closes[-1] - closes[-13]) / closes[-13]
        momentum_1 = (closes[-1] - closes[-2]) / closes[-2]
        
        return momentum_12 - momentum_1
    
    @staticmethod
    def _momentum_weighted(closes: List[float]) -> float:
        """Weighted Momentum: exponentially weighted momentum"""
        if len(closes) < 20:
            return 0.0
        
        weights = [0.1 ** i for i in range(20)]
        total_weight = sum(weights)
        
        weighted_sum = sum(w * (closes[-(i+1)] / closes[-(i+2)] - 1) 
                          for i, w in enumerate(weights[:19]))
        
        return weighted_sum / total_weight
    
    @staticmethod
    def _rate_of_change(closes: List[float], period: int = 12) -> float:
        """Rate of Change: (close - close[period]) / close[period]"""
        if len(closes) < period + 1:
            return 0.0
        
        return (closes[-1] - closes[-(period+1)]) / closes[-(period+1)]
    
    @staticmethod
    def _price_distance(closes: List[float]) -> float:
        """Price Distance: (close - min) / (max - min)"""
        if len(closes) < 20:
            return 0.5
        
        recent = closes[-20:]
        min_price = min(recent)
        max_price = max(recent)
        
        if max_price == min_price:
            return 0.5
        
        return (closes[-1] - min_price) / (max_price - min_price)
    
    @staticmethod
    def _trend_strength(closes: List[float]) -> float:
        """Trend Strength: R-squared of linear regression"""
        if len(closes) < 20:
            return 0.0
        
        n = 20
        recent = closes[-n:]
        x = list(range(n))
        
        x_mean = sum(x) / n
        y_mean = sum(recent) / n
        
        numerator = sum((x[i] - x_mean) * (recent[i] - y_mean) for i in range(n))
        denominator_x = sum((x[i] - x_mean) ** 2 for i in range(n))
        denominator_y = sum((recent[i] - y_mean) ** 2 for i in range(n))
        
        if denominator_x == 0 or denominator_y == 0:
            return 0.0
        
        correlation = numerator / (denominator_x * denominator_y) ** 0.5
        return correlation ** 2
    
    # ========================================================================
    # Volatility Factors
    # ========================================================================
    
    @staticmethod
    def _realized_volatility(closes: List[float], period: int = 20) -> float:
        """Realized Volatility: standard deviation of returns"""
        if len(closes) < period + 1:
            return 0.0
        
        returns = [(closes[-(i+1)] / closes[-(i+2)] - 1) for i in range(period)]
        mean_return = sum(returns) / period
        variance = sum((r - mean_return) ** 2 for r in returns) / period
        
        return variance ** 0.5
    
    @staticmethod
    def _volatility_ratio(closes: List[float]) -> float:
        """Volatility Ratio: recent volatility / long-term volatility"""
        if len(closes) < 50:
            return 1.0
        
        recent_vol = AlphaZoo._realized_volatility(closes[-20:], 19)
        long_vol = AlphaZoo._realized_volatility(closes, 49)
        
        if long_vol == 0:
            return 1.0
        
        return recent_vol / long_vol
    
    @staticmethod
    def _parkinson_volatility(highs: List[float], lows: List[float], period: int = 20) -> float:
        """Parkinson Volatility: based on high-low range"""
        if len(highs) < period:
            return 0.0
        
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        
        log_ranges = [(h / l) for h, l in zip(recent_highs, recent_lows)]
        log_returns = [r ** 2 for r in log_ranges]
        
        return (sum(log_returns) / (4 * period * 0.693)) ** 0.5
    
    @staticmethod
    def _garman_klass_volatility(highs: List[float], lows: List[float], closes: List[float], period: int = 20) -> float:
        """Garman-Klass Volatility: OHLC-based volatility"""
        if len(highs) < period:
            return 0.0
        
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        recent_closes = closes[-period:]
        
        log_hl = [(h / l) ** 2 for h, l in zip(recent_highs, recent_lows)]
        log_co = [(c / l) ** 2 for c, l in zip(recent_closes, recent_lows)]
        
        return (sum(log_hl) / (2 * period) - (2 * 0.693 - 1) * sum(log_co) / period) ** 0.5
    
    @staticmethod
    def _volatility_skew(closes: List[float], period: int = 20) -> float:
        """Volatility Skew: upside vs downside volatility"""
        if len(closes) < period + 1:
            return 0.0
        
        returns = [(closes[-(i+1)] / closes[-(i+2)] - 1) for i in range(period)]
        upside = [r for r in returns if r > 0]
        downside = [r for r in returns if r < 0]
        
        if not upside or not downside:
            return 0.0
        
        upside_vol = sum(r ** 2 for r in upside) / len(upside)
        downside_vol = sum(r ** 2 for r in downside) / len(downside)
        
        if downside_vol == 0:
            return 0.0
        
        return upside_vol / downside_vol
    
    # ========================================================================
    # Volume Factors
    # ========================================================================
    
    @staticmethod
    def _volume_ratio(volumes: List[float], period: int = 20) -> float:
        """Volume Ratio: recent volume / average volume"""
        if len(volumes) < period:
            return 1.0
        
        recent_vol = sum(volumes[-5:]) / 5
        avg_vol = sum(volumes[-period:]) / period
        
        if avg_vol == 0:
            return 1.0
        
        return recent_vol / avg_vol
    
    @staticmethod
    def _obv(closes: List[float], volumes: List[float]) -> float:
        """On Balance Volume (normalized)"""
        if len(closes) < 20:
            return 0.0
        
        obv = 0
        for i in range(1, min(20, len(closes))):
            if closes[-i] > closes[-(i+1)]:
                obv += volumes[-i]
            elif closes[-i] < closes[-(i+1)]:
                obv -= volumes[-i]
        
        total_volume = sum(volumes[-20:])
        if total_volume == 0:
            return 0.0
        
        return obv / total_volume
    
    @staticmethod
    def _vwap(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 20) -> float:
        """Volume Weighted Average Price (normalized)"""
        if len(closes) < period:
            return 1.0
        
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        recent_closes = closes[-period:]
        recent_volumes = volumes[-period:]
        
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(recent_highs, recent_lows, recent_closes)]
        
        numerator = sum(tp * v for tp, v in zip(typical_prices, recent_volumes))
        denominator = sum(recent_volumes)
        
        if denominator == 0:
            return 1.0
        
        vwap = numerator / denominator
        return closes[-1] / vwap
    
    @staticmethod
    def _volume_price_trend(closes: List[float], volumes: List[float]) -> float:
        """Volume Price Trend"""
        if len(closes) < 20:
            return 0.0
        
        vpt = 0
        for i in range(1, min(20, len(closes))):
            if closes[-(i+1)] != 0:
                vpt += volumes[-i] * (closes[-i] / closes[-(i+1)] - 1)
        
        total_volume = sum(volumes[-20:])
        if total_volume == 0:
            return 0.0
        
        return vpt / total_volume
    
    @staticmethod
    def _money_flow_index(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 14) -> float:
        """Money Flow Index (0-100)"""
        if len(closes) < period + 1:
            return 50.0
        
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs[-(period+1):], lows[-(period+1):], closes[-(period+1):])]
        
        positive_flow = 0
        negative_flow = 0
        
        for i in range(1, period + 1):
            if typical_prices[-i] > typical_prices[-(i+1)]:
                positive_flow += volumes[-i]
            else:
                negative_flow += volumes[-i]
        
        if negative_flow == 0:
            return 100.0
        
        money_ratio = positive_flow / negative_flow
        return 100 - (100 / (1 + money_ratio))
    
    @staticmethod
    def _volume_volatility(volumes: List[float], period: int = 20) -> float:
        """Volume Volatility: coefficient of variation"""
        if len(volumes) < period:
            return 0.0
        
        recent = volumes[-period:]
        mean_vol = sum(recent) / period
        
        if mean_vol == 0:
            return 0.0
        
        variance = sum((v - mean_vol) ** 2 for v in recent) / period
        std_vol = variance ** 0.5
        
        return std_vol / mean_vol
    
    # ========================================================================
    # Mean Reversion Factors
    # ========================================================================
    
    @staticmethod
    def _rsi_zscore(rsi: float) -> float:
        """RSI Z-Score: (RSI - 50) / 25"""
        return (rsi - 50) / 25
    
    @staticmethod
    def _bollinger_band_width(indicators: Dict[str, float]) -> float:
        """Bollinger Band Width: (upper - lower) / middle"""
        upper = indicators.get("bollinger_upper", 0)
        middle = indicators.get("bollinger_middle", 0)
        lower = indicators.get("bollinger_lower", 0)
        
        if middle == 0:
            return 0.0
        
        return (upper - lower) / middle
    
    @staticmethod
    def _price_to_ma(closes: List[float], sma: float) -> float:
        """Price to MA: (close - SMA) / SMA"""
        if sma == 0:
            return 0.0
        
        return (closes[-1] - sma) / sma
    
    @staticmethod
    def _stochastic_oscillator(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Stochastic Oscillator %K (0-100)"""
        if len(highs) < period:
            return 50.0
        
        recent_highs = highs[-period:]
        recent_lows = lows[-period:]
        
        highest = max(recent_highs)
        lowest = min(recent_lows)
        
        if highest == lowest:
            return 50.0
        
        return (closes[-1] - lowest) / (highest - lowest) * 100
    
    @staticmethod
    def _cci(highs: List[float], lows: List[float], closes: List[float], period: int = 20) -> float:
        """Commodity Channel Index"""
        if len(closes) < period:
            return 0.0
        
        typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs[-period:], lows[-period:], closes[-period:])]
        
        tp_mean = sum(typical_prices) / period
        mean_deviation = sum(abs(tp - tp_mean) for tp in typical_prices) / period
        
        if mean_deviation == 0:
            return 0.0
        
        return (typical_prices[-1] - tp_mean) / (0.015 * mean_deviation)
