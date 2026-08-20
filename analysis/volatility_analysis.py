"""
Volatility Analysis

Market volatility assessment for:
- Dynamic Stop Loss adjustment
- Take Profit adjustment
- Market regime detection (trending vs ranging)
- Avoiding trades in unsuitable conditions
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class VolatilityAnalysis:
    atr_value: float
    atr_percent: float
    regime: str  # "LOW", "NORMAL", "HIGH", "EXTREME"
    is_trending: bool
    normalized_atr: float
    contraction_expansion: str  # "CONTRACTING", "NEUTRAL", "EXPANDING"


def analyze_volatility(df: pd.DataFrame, atr_period: int = 14) -> VolatilityAnalysis:
    """Analyze current volatility conditions."""
    if len(df) < atr_period * 3:
        return VolatilityAnalysis(
            atr_value=0.0, atr_percent=0.0, regime="NORMAL",
            is_trending=False, normalized_atr=1.0,
            contraction_expansion="NEUTRAL",
        )

    latest = df.iloc[-1]
    atr = float(latest.get("atr", 0))
    close = float(latest["close"])

    atr_percent = (atr / close * 100) if close > 0 else 0

    # Regime classification based on ATR percent
    if atr_percent < 0.5:
        regime = "LOW"
    elif atr_percent < 1.5:
        regime = "NORMAL"
    elif atr_percent < 3.0:
        regime = "HIGH"
    else:
        regime = "EXTREME"

    # Normalized ATR (compare to recent ATR history)
    atr_series = df["atr"].dropna().values
    if len(atr_series) >= atr_period * 2:
        recent_atr = atr_series[-atr_period:]
        older_atr = atr_series[-(atr_period * 2):-atr_period]
        avg_recent_atr = float(np.mean(recent_atr))
        avg_older_atr = float(np.mean(older_atr))

        if avg_older_atr > 0:
            normalized_atr = avg_recent_atr / avg_older_atr
        else:
            normalized_atr = 1.0

        if normalized_atr < 0.8:
            contraction_expansion = "CONTRACTING"
        elif normalized_atr > 1.2:
            contraction_expansion = "EXPANDING"
        else:
            contraction_expansion = "NEUTRAL"
    else:
        normalized_atr = 1.0
        contraction_expansion = "NEUTRAL"

    # Detect trending vs ranging using ADX-like approach (simplified)
    if len(df) >= 20:
        close_values = df["close"].values[-20:]
        price_direction = abs(close_values[-1] - close_values[0]) / close_values[0]
        avg_range = np.mean([abs(df["high"].values[-i] - df["low"].values[-i]) for i in range(1, 21)])
        avg_price = np.mean(close_values)
        normalized_range = avg_range / avg_price if avg_price > 0 else 0

        is_trending = price_direction > normalized_range * 1.5
    else:
        is_trending = False

    return VolatilityAnalysis(
        atr_value=round(atr, 2),
        atr_percent=round(atr_percent, 3),
        regime=regime,
        is_trending=is_trending,
        normalized_atr=round(normalized_atr, 2),
        contraction_expansion=contraction_expansion,
    )
