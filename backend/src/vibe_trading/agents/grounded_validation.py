"""
Grounded Analyst Validation

Validates that analyst outputs contain grounded references to prevent hallucination.
Checks for price levels, timestamps, and data sources in analyst reports.
"""
import re
from typing import List, Tuple


def validate_grounded_output(report: str, analyst_type: str) -> Tuple[bool, List[str]]:
    """
    Validate that an analyst report contains grounded references.
    
    Args:
        report: The analyst's output text
        analyst_type: Type of analyst ("news" or "sentiment")
    
    Returns:
        Tuple of (is_valid, list_of_violations)
        - is_valid: True if report contains sufficient grounding
        - violations: List of specific issues found
    """
    violations = []
    
    # Check for price references (e.g., $42,000, 42000, $42k)
    # More specific pattern: requires at least 4 digits or $ prefix
    price_pattern = r'(?:\$\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:k)?)|(?:\d{4,}(?:,\d{3})*(?:\.\d+)?(?:k)?)'
    price_matches = re.findall(price_pattern, report)
    
    # Check for timestamps (e.g., 2024-01-15, 14:30 UTC, 2024-01-15 14:30)
    timestamp_patterns = [
        r'\d{4}-\d{2}-\d{2}',  # Date: 2024-01-15
        r'\d{1,2}:\d{2}(?::\d{2})?',  # Time: 14:30 or 14:30:00
        r'UTC|GMT|EST|PST|CST',  # Timezone
    ]
    timestamp_matches = []
    for pattern in timestamp_patterns:
        timestamp_matches.extend(re.findall(pattern, report, re.IGNORECASE))
    
    # Check for data source references
    source_patterns = [
        r'Binance',
        r'CoinGecko',
        r'CoinMarketCap',
        r'OKX',
        r'Bybit',
        r'根据.*数据',
        r'数据显示',
        r'统计',
    ]
    source_matches = []
    for pattern in source_patterns:
        source_matches.extend(re.findall(pattern, report, re.IGNORECASE))
    
    # Validation rules
    has_price = len(price_matches) > 0
    has_timestamp = len(timestamp_matches) > 0
    has_source = len(source_matches) > 0
    
    # For news analyst: need at least 2 prices and 1 timestamp
    if analyst_type == "news":
        if len(price_matches) < 2:
            violations.append("缺少足够的价格引用 (需要至少 2 个)")
        if len(timestamp_matches) < 1:
            violations.append("缺少时间戳引用 (需要至少 1 个)")
        if not has_source:
            violations.append("缺少数据来源引用")
    
    # For sentiment analyst: need at least 1 price and 1 source
    elif analyst_type == "sentiment":
        if len(price_matches) < 1:
            violations.append("缺少价格引用 (需要至少 1 个)")
        if not has_source:
            violations.append("缺少数据来源引用")
    
    # Overall validation
    is_valid = len(violations) == 0
    
    return is_valid, violations


def extract_grounded_references(report: str) -> dict:
    """
    Extract all grounded references from a report.
    
    Returns:
        Dictionary with extracted references:
        - prices: List of price references found
        - timestamps: List of timestamp references found
        - sources: List of data source references found
    """
    # Extract prices
    price_pattern = r'\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:k)?'
    prices = re.findall(price_pattern, report)
    
    # Extract timestamps
    timestamp_patterns = [
        r'\d{4}-\d{2}-\d{2}',
        r'\d{1,2}:\d{2}(?::\d{2})?',
        r'UTC|GMT|EST|PST|CST',
    ]
    timestamps = []
    for pattern in timestamp_patterns:
        timestamps.extend(re.findall(pattern, report, re.IGNORECASE))
    
    # Extract sources
    source_patterns = [
        r'Binance',
        r'CoinGecko',
        r'CoinMarketCap',
        r'OKX',
        r'Bybit',
        r'根据.*?数据',
        r'数据显示',
        r'统计',
    ]
    sources = []
    for pattern in source_patterns:
        sources.extend(re.findall(pattern, report, re.IGNORECASE))
    
    return {
        "prices": prices,
        "timestamps": timestamps,
        "sources": sources,
    }
