"""Support and resistance detection with cluster-based analysis.

Swing highs/lows are clustered into zones, each zone is scored by the number of
touches and by how much volume traded inside it. The two nearest zones on each
side of price are returned together with the last swing points, which the risk
module uses for structure-based stops and resistance-aware targets.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class MarketLevels:
    support_1: float
    support_2: float
    resistance_1: float
    resistance_2: float
    support_1_strength: str = "WEAK"          # WEAK | MODERATE | STRONG
    resistance_1_strength: str = "WEAK"
    last_swing_low: Optional[float] = None
    last_swing_high: Optional[float] = None
    zones: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "support_1": self.support_1,
            "support_2": self.support_2,
            "resistance_1": self.resistance_1,
            "resistance_2": self.resistance_2,
            "support_1_strength": self.support_1_strength,
            "resistance_1_strength": self.resistance_1_strength,
            "last_swing_low": self.last_swing_low,
            "last_swing_high": self.last_swing_high,
            "zones": self.zones,
            "note": self.note,
        }


def _cluster_prices(prices: List[Tuple[float, float]], threshold: float = 0.005) -> List[Tuple[float, float, int]]:
    """Cluster (price, volume) points; returns (price, volume_sum, touches)."""
    if not prices:
        return []

    ordered = sorted(prices, key=lambda item: item[0])
    clusters: List[Tuple[float, float, int]] = []
    values = [ordered[0][0]]
    volumes = [ordered[0][1]]

    for price, volume in ordered[1:]:
        if abs(price - values[-1]) / max(1e-12, values[-1]) <= threshold:
            values.append(price)
            volumes.append(volume)
        else:
            clusters.append((float(np.mean(values)), float(sum(volumes)), len(values)))
            values, volumes = [price], [volume]

    clusters.append((float(np.mean(values)), float(sum(volumes)), len(values)))
    return clusters


def _count_touches(df: pd.DataFrame, level: float, tolerance: float = 0.001) -> int:
    upper = level * (1 + tolerance)
    lower = level * (1 - tolerance)
    if upper <= lower:
        return 0

    hit = ((df["low"] >= lower) & (df["low"] <= upper)) | ((df["high"] >= lower) & (df["high"] <= upper))
    inside = (df["low"] <= level) & (df["high"] >= level)
    return int((hit | inside).sum())


def _strength(touches: int) -> str:
    if touches >= 5:
        return "STRONG"
    if touches >= 3:
        return "MODERATE"
    return "WEAK"


def find_market_levels(df, lookback=200, order=2) -> MarketLevels:
    """Find support/resistance zones by clustering recent swing points."""
    recent = df.tail(lookback).copy().reset_index(drop=True)
    if recent.empty:
        price = 0.0
        return MarketLevels(price, price, price, price, note="no data")

    current_price = float(recent["close"].iloc[-1])
    highs = recent["high"].to_numpy(dtype=float)
    lows = recent["low"].to_numpy(dtype=float)
    volumes = recent["volume"].to_numpy(dtype=float) if "volume" in recent else np.zeros(len(recent))

    swing_highs: List[Tuple[float, float]] = []
    swing_lows: List[Tuple[float, float]] = []
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None

    for i in range(order, len(recent) - order):
        window_high = highs[i - order:i + order + 1]
        window_low = lows[i - order:i + order + 1]
        if highs[i] >= window_high.max() and (highs[i] > highs[i + 1] or highs[i] > highs[i + 2]):
            swing_highs.append((float(highs[i]), float(volumes[i])))
            last_swing_high = float(highs[i])
        if lows[i] <= window_low.min() and (lows[i] < lows[i + 1] or lows[i] < lows[i + 2]):
            swing_lows.append((float(lows[i]), float(volumes[i])))
            last_swing_low = float(lows[i])

    resistances = [(p, v, c) for p, v, c in _cluster_prices(swing_highs) if p > current_price]
    supports = [(p, v, c) for p, v, c in _cluster_prices(swing_lows) if p < current_price]

    # Nearest first.
    resistances.sort(key=lambda item: item[0])
    supports.sort(key=lambda item: -item[0])

    # Merge both lists into one zone table for the chart.
    zones = []
    for price, volume, count in resistances[:4]:
        zones.append({"price": round(price, 6), "type": "RESISTANCE", "touches": count,
                      "volume": volume, "strength": _strength(count),
                      "distance_pct": round((price / current_price - 1.0) * 100.0, 2)})
    for price, volume, count in supports[:4]:
        zones.append({"price": round(price, 6), "type": "SUPPORT", "touches": count,
                      "volume": volume, "strength": _strength(count),
                      "distance_pct": round((price / current_price - 1.0) * 100.0, 2)})

    atr = float(recent["atr"].iloc[-1]) if "atr" in recent and not np.isnan(recent["atr"].iloc[-1]) else current_price * 0.01

    if resistances:
        r1_price, _, r1_touches = resistances[0]
        r1_strength = _strength(_count_touches(recent, r1_price) + r1_touches - 1)
        r2_price = resistances[1][0] if len(resistances) > 1 else r1_price + max(atr, current_price * 0.01)
    else:
        r1_price = current_price + max(atr, current_price * 0.01)
        r2_price = current_price + 2 * max(atr, current_price * 0.01)
        r1_strength = "WEAK"

    if supports:
        s1_price, _, s1_touches = supports[0]
        s1_strength = _strength(_count_touches(recent, s1_price) + s1_touches - 1)
        s2_price = supports[1][0] if len(supports) > 1 else s1_price - max(atr, current_price * 0.01)
    else:
        s1_price = current_price - max(atr, current_price * 0.01)
        s2_price = current_price - 2 * max(atr, current_price * 0.01)
        s1_strength = "WEAK"

    note = ""
    if not swing_highs and not swing_lows:
        note = "not enough swing points in this window"

    return MarketLevels(
        support_1=float(s1_price),
        support_2=float(s2_price),
        resistance_1=float(r1_price),
        resistance_2=float(r2_price),
        support_1_strength=s1_strength,
        resistance_1_strength=r1_strength,
        last_swing_low=last_swing_low if last_swing_low else float(recent["low"].tail(20).min()),
        last_swing_high=last_swing_high if last_swing_high else float(recent["high"].tail(20).max()),
        zones=sorted(zones, key=lambda z: -z["price"]),
        note=note,
    )


def nearest_zone_info(levels: Optional[MarketLevels], price: float) -> Dict[str, Any]:
    """Percent distance to the nearest zone on each side (always positive).

    Handy for "room to run" style readouts; the scoring layer computes its own
    signed proximity because it needs the direction of the bias.
    """
    if not levels or not price:
        return {}
    return {
        "resistance_distance_pct": (levels.resistance_1 / price - 1.0) * 100.0 if levels.resistance_1 else None,
        "support_distance_pct": (1.0 - levels.support_1 / price) * 100.0 if levels.support_1 else None,
        "resistance_strength": levels.resistance_1_strength,
        "support_strength": levels.support_1_strength,
    }
