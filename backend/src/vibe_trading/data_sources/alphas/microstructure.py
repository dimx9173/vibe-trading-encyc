"""
Microstructure Alpha Factors & Non-Linear Operators

Harvested and adapted from AlphaGPT symbolic operators & times.py:
- V_RET: Volume-Price Momentum / Covariance factor (filters fake breakouts)
- TS_ZSCORE: Rolling Z-score momentum divergence & exhaustion
- TS_DECAY_LINEAR: Linear time-decay moving average for rapid inflection detection
- VOLUME_EXHAUSTION: High-volume stagnation / exhaustion detector
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
import math


def calculate_v_ret(
    prices: List[float],
    volumes: List[float],
    window: int = 20,
) -> float:
    """
    Calculate Volume-Price Momentum (V_RET).
    Formula: delta_price * (volume / MA(volume, window))

    Returns:
        float: V_RET value. Positive and large means strong volume-supported upward move.
               Negative and large means strong volume-supported downward move.
    """
    if len(prices) < 2 or len(volumes) < window:
        return 0.0

    delta_price = prices[-1] - prices[-2]
    recent_vols = volumes[-window:]
    ma_vol = sum(recent_vols) / len(recent_vols)

    if ma_vol <= 1e-8:
        return 0.0

    vol_multiplier = volumes[-1] / ma_vol
    return delta_price * vol_multiplier


def calculate_ts_zscore(
    values: List[float],
    window: int = 20,
) -> float:
    """
    Calculate rolling Z-Score of the last element over `window`.
    Formula: (x_t - mean(x)) / (std(x) + 1e-8)
    """
    if len(values) < window or window < 2:
        return 0.0

    subset = values[-window:]
    mean = sum(subset) / len(subset)
    variance = sum((x - mean) ** 2 for x in subset) / (len(subset) - 1)
    std = math.sqrt(variance)

    if std <= 1e-8:
        return 0.0

    return (values[-1] - mean) / std


def calculate_ts_decay_linear(
    values: List[float],
    window: int = 20,
) -> float:
    """
    Calculate linear time-decay weighted moving average.
    Weights: w_i = i / sum(1..d), placing linearly higher weight on recent bars.
    """
    if not values:
        return 0.0

    actual_window = min(len(values), window)
    subset = values[-actual_window:]
    
    # weights sum: d * (d + 1) / 2
    weight_sum = actual_window * (actual_window + 1) / 2.0
    weighted_val = sum((idx + 1) * val for idx, val in enumerate(subset))
    return weighted_val / weight_sum


def detect_volume_exhaustion(
    prices: List[float],
    volumes: List[float],
    window: int = 20,
    volume_spike_threshold: float = 1.8,
    price_stagnation_pct: float = 0.003,
) -> Tuple[bool, str, float]:
    """
    Detect Volume Exhaustion / Stagnation (放量滯漲或放量滯跌).
    Trigger condition:
    1. Recent volume is >= volume_spike_threshold * MA(volume, window)
    2. Price change over the last 2 bars is small (<= price_stagnation_pct) or showing pinbar reversal

    Returns:
        Tuple[is_exhausted, reason, exhaustion_score]
    """
    if len(prices) < 3 or len(volumes) < window:
        return False, "Insufficient data", 0.0

    recent_vols = volumes[-window:]
    ma_vol = sum(recent_vols) / len(recent_vols)
    if ma_vol <= 1e-8:
        return False, "Zero volume baseline", 0.0

    current_vol_ratio = volumes[-1] / ma_vol
    price_move_pct = abs(prices[-1] - prices[-3]) / prices[-3]

    if current_vol_ratio >= volume_spike_threshold:
        if price_move_pct <= price_stagnation_pct:
            score = min(1.0, current_vol_ratio / 3.0)
            return True, f"Volume Spike ({current_vol_ratio:.1f}x) with Price Stagnation ({price_move_pct*100:.2f}%)", score
        
        # Check pinbar / reversal
        bar_body = abs(prices[-1] - prices[-2])
        if bar_body / prices[-2] <= (price_stagnation_pct / 2.0):
            score = min(1.0, current_vol_ratio / 2.5)
            return True, f"Volume Spike ({current_vol_ratio:.1f}x) with Reversal Pinbar", score

    return False, "Normal volume dynamic", 0.0


def check_fake_breakout(
    prices: List[float],
    volumes: List[float],
    bb_upper: Optional[float] = None,
    bb_lower: Optional[float] = None,
    window: int = 20,
) -> Tuple[bool, str, str]:
    """
    Check if a breakout beyond Bollinger Bands or local extremes is a Low-Volume Fake Breakout.
    Returns:
        Tuple[is_fake, direction, description]
    """
    if len(prices) < window or len(volumes) < window:
        return False, "NONE", "Insufficient data"

    recent_vols = volumes[-window:]
    ma_vol = sum(recent_vols) / len(recent_vols)
    if ma_vol <= 1e-8:
        return False, "NONE", "Zero volume"

    vol_ratio = volumes[-1] / ma_vol
    curr_price = prices[-1]

    # Upper breakout with weak volume (< 0.8x MA_vol)
    if bb_upper is not None and curr_price > bb_upper:
        if vol_ratio < 0.8:
            return True, "BULL_FAKE_BREAKOUT", f"Price broke upper band ({curr_price:.2f} > {bb_upper:.2f}) on LOW volume ({vol_ratio:.2f}x MA)"
    
    # Lower breakout with weak volume (< 0.8x MA_vol)
    if bb_lower is not None and curr_price < bb_lower:
        if vol_ratio < 0.8:
            return True, "BEAR_FAKE_BREAKOUT", f"Price broke lower band ({curr_price:.2f} < {bb_lower:.2f}) on LOW volume ({vol_ratio:.2f}x MA)"

    return False, "NONE", "Breakout confirmed by volume or within bands"


@dataclass
class MicrostructureSummary:
    """Summary of calculated microstructure factors"""
    v_ret: float
    v_ret_zscore: float
    price_zscore_20: float
    decay_linear_price: float
    volume_ratio: float
    is_exhausted: bool
    exhaustion_reason: str
    is_fake_breakout: bool
    fake_breakout_direction: str
    fake_breakout_desc: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "v_ret": round(self.v_ret, 4),
            "v_ret_zscore": round(self.v_ret_zscore, 2),
            "price_zscore_20": round(self.price_zscore_20, 2),
            "decay_linear_price": round(self.decay_linear_price, 2),
            "volume_ratio": round(self.volume_ratio, 2),
            "is_exhausted": self.is_exhausted,
            "exhaustion_reason": self.exhaustion_reason,
            "is_fake_breakout": self.is_fake_breakout,
            "fake_breakout_direction": self.fake_breakout_direction,
            "fake_breakout_desc": self.fake_breakout_desc,
        }


class MicrostructureAnalyzer:
    """
    Comprehensive Microstructure Factor Analyzer.
    """

    def analyze(
        self,
        prices: List[float],
        volumes: List[float],
        bb_upper: Optional[float] = None,
        bb_lower: Optional[float] = None,
        window: int = 20,
    ) -> MicrostructureSummary:
        """Run full microstructure analysis over price and volume arrays"""
        v_ret = calculate_v_ret(prices, volumes, window=window)
        
        # Calculate historical V_RET series for Z-Score
        v_ret_series = []
        if len(prices) >= window + 2:
            for i in range(window, len(prices) + 1):
                sub_p = prices[:i]
                sub_v = volumes[:i]
                v_ret_series.append(calculate_v_ret(sub_p, sub_v, window=min(20, len(sub_p)-1)))
        
        v_ret_zscore = calculate_ts_zscore(v_ret_series, window=min(20, len(v_ret_series))) if v_ret_series else 0.0
        price_zscore = calculate_ts_zscore(prices, window=window)
        decay_linear = calculate_ts_decay_linear(prices, window=window)
        
        recent_vols = volumes[-window:] if len(volumes) >= window else volumes
        ma_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1.0
        vol_ratio = (volumes[-1] / ma_vol) if ma_vol > 1e-8 and volumes else 1.0

        is_exh, exh_reason, _ = detect_volume_exhaustion(prices, volumes, window=window)
        is_fake, fake_dir, fake_desc = check_fake_breakout(prices, volumes, bb_upper, bb_lower, window=window)

        return MicrostructureSummary(
            v_ret=v_ret,
            v_ret_zscore=v_ret_zscore,
            price_zscore_20=price_zscore,
            decay_linear_price=decay_linear,
            volume_ratio=vol_ratio,
            is_exhausted=is_exh,
            exhaustion_reason=exh_reason,
            is_fake_breakout=is_fake,
            fake_breakout_direction=fake_dir,
            fake_breakout_desc=fake_desc,
        )
