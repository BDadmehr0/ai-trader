"""
Market Structure Analysis

Detects classical market structure patterns:
- Higher High (HH) / Higher Low (HL)
- Lower High (LH) / Lower Low (LL)
- Break of Structure (BoS)
"""

from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd


@dataclass
class SwingPoint:
    index: int
    price: float
    time: object
    type: str


@dataclass
class MarketStructure:
    trend: str
    hh_count: int
    hl_count: int
    lh_count: int
    ll_count: int
    last_swing_high: Optional[float]
    last_swing_low: Optional[float]
    last_breakout_direction: Optional[str]
    swing_points: List[SwingPoint] = field(default_factory=list)
    strength: str = "WEAK"


def find_swing_points(df: pd.DataFrame, order: int = 2) -> List[SwingPoint]:
    """Find swing highs and lows using local extrema method."""
    highs = df["high"].values
    lows = df["low"].values
    timestamps = df["timestamp"].values
    n = len(highs)
    swing_points: List[SwingPoint] = []

    for i in range(order, n - order):
        is_high = True
        for j in range(1, order + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_high = False
                break
        if is_high:
            swing_points.append(SwingPoint(index=i, price=float(highs[i]), time=timestamps[i], type="HIGH"))
            continue

        is_low = True
        for j in range(1, order + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_low = False
                break
        if is_low:
            swing_points.append(SwingPoint(index=i, price=float(lows[i]), time=timestamps[i], type="LOW"))

    return swing_points


def analyze_market_structure(df: pd.DataFrame, lookback: int = 100, order: int = 2) -> MarketStructure:
    """Analyze the most recent lookback candles for market structure."""
    recent = df.tail(lookback).copy().reset_index(drop=True)

    if len(recent) < order * 2 + 2:
        return MarketStructure(trend="NEUTRAL", hh_count=0, hl_count=0, lh_count=0, ll_count=0,
                                last_swing_high=None, last_swing_low=None, last_breakout_direction=None, strength="WEAK")

    swing_points = find_swing_points(recent, order)

    if len(swing_points) < 4:
        return MarketStructure(trend="NEUTRAL", hh_count=0, hl_count=0, lh_count=0, ll_count=0,
                                last_swing_high=None, last_swing_low=None, last_breakout_direction=None,
                                strength="WEAK", swing_points=swing_points)

    highs = [sp for sp in swing_points if sp.type == "HIGH"]
    lows = [sp for sp in swing_points if sp.type == "LOW"]

    hh_count = hl_count = lh_count = ll_count = 0

    for i in range(1, len(highs)):
        if highs[i].price > highs[i - 1].price:
            hh_count += 1
        elif highs[i].price < highs[i - 1].price:
            lh_count += 1

    for i in range(1, len(lows)):
        if lows[i].price > lows[i - 1].price:
            hl_count += 1
        elif lows[i].price < lows[i - 1].price:
            ll_count += 1

    bullish_score = hh_count + hl_count
    bearish_score = lh_count + ll_count

    if bullish_score > bearish_score and bullish_score >= 2:
        trend = "BULLISH"
    elif bearish_score > bullish_score and bearish_score >= 2:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    total_swings = len(highs) + len(lows)
    if total_swings >= 8 and abs(bullish_score - bearish_score) >= 3:
        strength = "STRONG"
    elif total_swings >= 5:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    last_breakout_dir = None
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1].price > highs[-2].price and lows[-1].price >= lows[-2].price:
            last_breakout_dir = "BULLISH"
        elif lows[-1].price < lows[-2].price and highs[-1].price <= highs[-2].price:
            last_breakout_dir = "BEARISH"

    return MarketStructure(trend=trend, hh_count=hh_count, hl_count=hl_count, lh_count=lh_count, ll_count=ll_count,
                            last_swing_high=highs[-1].price if highs else None,
                            last_swing_low=lows[-1].price if lows else None,
                            last_breakout_direction=last_breakout_dir,
                            swing_points=swing_points[-10:], strength=strength)