
"""Support and Resistance detection with cluster-based analysis."""
from dataclasses import dataclass
import pandas as pd
import numpy as np
from typing import List, Tuple

@dataclass
class MarketLevels:
    support_1: float
    support_2: float
    resistance_1: float
    resistance_2: float
    support_1_strength: str = "WEAK"  # WEAK, MODERATE, STRONG
    resistance_1_strength: str = "WEAK"

def _cluster_prices(prices: List[float], threshold: float = 0.005) -> List[Tuple[float, int]]:
    """Cluster nearby price levels and count touches."""
    if not prices: return []
    sorted_p = sorted(prices)
    clusters = []
    current_cluster = [sorted_p[0]]
    for p in sorted_p[1:]:
        if abs(p - current_cluster[-1]) / current_cluster[-1] <= threshold:
            current_cluster.append(p)
        else:
            clusters.append((np.mean(current_cluster), len(current_cluster)))
            current_cluster = [p]
    clusters.append((np.mean(current_cluster), len(current_cluster)))
    return clusters

def _count_touches(df: pd.DataFrame, level: float, tolerance: float = 0.001) -> int:
    """Count how many times price touched a level."""
    upper = level * (1 + tolerance)
    lower = level * (1 - tolerance)
    touches = 0
    for row in df.itertuples():
        if lower <= row.low <= upper or lower <= row.high <= upper:
            touches += 1
        elif row.low <= level <= row.high:
            touches += 1
    return touches

def find_market_levels(df, lookback=200):
    """Find support and resistance levels using clustering."""
    recent = df.tail(lookback)
    current_price = float(recent['close'].iloc[-1])

    # Find local highs and lows for clustering
    highs = recent['high'].values
    lows = recent['low'].values
    
    swing_highs = []
    swing_lows = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append(float(highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append(float(lows[i]))

    # Cluster swing points
    res_clusters = _cluster_prices(swing_highs) if swing_highs else []
    sup_clusters = _cluster_prices(swing_lows) if swing_lows else []

    # Filter for resistance (above current price)
    resistances = [(p, c) for p, c in res_clusters if p > current_price]
    resistances.sort(key=lambda x: x[0])

    # Filter for support (below current price)
    supports = [(p, c) for p, c in sup_clusters if p < current_price]
    supports.sort(key=lambda x: x[0], reverse=True)

    # Count touches for strength
    r1_strength = "WEAK"
    s1_strength = "WEAK"

    if resistances:
        r1_price = resistances[0][0]
        touches = _count_touches(recent, r1_price)
        if touches >= 5: r1_strength = "STRONG"
        elif touches >= 3: r1_strength = "MODERATE"
        r2_price = resistances[1][0] if len(resistances) > 1 else r1_price * 1.02
    else:
        r1_price = current_price * 1.01
        r2_price = current_price * 1.02

    if supports:
        s1_price = supports[0][0]
        touches = _count_touches(recent, s1_price)
        if touches >= 5: s1_strength = "STRONG"
        elif touches >= 3: s1_strength = "MODERATE"
        s2_price = supports[1][0] if len(supports) > 1 else s1_price * 0.98
    else:
        s1_price = current_price * 0.99
        s2_price = current_price * 0.98

    return MarketLevels(support_1=s1_price, support_2=s2_price, resistance_1=r1_price, resistance_2=r2_price, support_1_strength=s1_strength, resistance_1_strength=r1_strength)
