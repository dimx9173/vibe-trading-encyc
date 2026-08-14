"""
Multi-Exchange Liquidation Aggregator

Aggregates liquidation data from multiple exchanges with:
- Timestamp alignment (1-second windows)
- Volume-weighted averaging
- Outlier filtering (median ±10%)
"""
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from collections import defaultdict
from .base import LiquidationPlugin, LiquidationData


class MultiExchangeAggregator(LiquidationPlugin):
    """Multi-exchange liquidation aggregator"""
    
    def __init__(self, sources: List[LiquidationPlugin]):
        self.sources = sources
    
    async def fetch(self, symbol: str, **kwargs) -> Optional[List[LiquidationData]]:
        """Aggregate liquidation data from multiple sources"""
        # Fetch from all sources in parallel
        tasks = [source.fetch(symbol, **kwargs) for source in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results
        successful = [
            r for r in results 
            if isinstance(r, list) and r is not None
        ]
        
        if not successful:
            return None
        
        # Flatten all data points
        all_points = []
        for result in successful:
            all_points.extend(result)
        
        if not all_points:
            return None
        
        # Align timestamps (1-second windows)
        aligned = self._align_timestamps(all_points)
        
        # Apply outlier filtering
        filtered = self._filter_outliers(aligned)
        
        return filtered
    
    def _align_timestamps(self, data_points: List[LiquidationData]) -> List[LiquidationData]:
        """Align timestamps to 1-second windows"""
        # Group by 1-second windows
        groups = defaultdict(list)
        for point in data_points:
            # Round to nearest second
            key = point.timestamp.replace(microsecond=0)
            groups[key].append(point)
        
        # Aggregate each group
        aligned = []
        for timestamp, group in groups.items():
            if len(group) == 1:
                aligned.append(group[0])
            else:
                # Volume-weighted average
                total_volume = sum(p.quantity for p in group)
                if total_volume > 0:
                    avg_price = sum(p.price * p.quantity for p in group) / total_volume
                    total_quantity = sum(p.quantity for p in group)
                    
                    aggregated = LiquidationData(
                        symbol=group[0].symbol,
                        side=group[0].side,
                        price=avg_price,
                        quantity=total_quantity,
                        usd_value=avg_price * total_quantity,
                        exchange="Aggregated",
                        timestamp=timestamp
                    )
                    aligned.append(aggregated)
        
        return aligned
    
    def _filter_outliers(self, data_points: List[LiquidationData]) -> List[LiquidationData]:
        """Filter outliers using median ±10%"""
        if len(data_points) < 3:
            return data_points
        
        # Calculate median price
        prices = sorted([p.price for p in data_points])
        median = prices[len(prices) // 2]
        
        # Filter outliers
        filtered = [
            p for p in data_points
            if abs(p.price - median) / median < 0.10
        ]
        
        return filtered
    
    @property
    def is_available(self) -> bool:
        return any(source.is_available for source in self.sources)
