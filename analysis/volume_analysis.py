"""
Volume Analysis

Advanced volume analysis for better trade validation.
- Volume Spike detection
- Relative Volume (RVOL)
- Volume Confirmation for trends
- Breakout validation (strong vs fake breakouts)
"""

from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class VolumeAnalysis:
    volume_ratio: float
    is_spike: bool
    spike_strength: str  # "NONE", "WEAK", "MODERATE", "STRONG"
    relative_volume: float
    trend_confirmation: str  # "BULLISH", "BEARISH", "NEUTRAL"
    breakout_quality: str  # "NONE", "WEAK", "MODERATE", "STRONG"
    unusual_volume: bool


def analyze_volume(
    df: pd.DataFrame,
    lookback: int = 20,
    spike_threshold: float = 1.5,
) -> VolumeAnalysis:
    """Analyze volume characteristics of the most recent candle."""
    if len(df) < lookback + 1:
        return VolumeAnalysis(
            volume_ratio=1.0, is_spike=False, spike_strength="NONE",
            relative_volume=1.0, trend_confirmation="NEUTRAL",
            breakout_quality="NONE", unusual_volume=False,
        )

    latest = df.iloc[-1]
    recent = df.tail(lookback)

    current_volume = float(latest["volume"])
    avg_volume = float(recent["volume"].mean())
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

    # Volume spike detection
    is_spike = volume_ratio >= spike_threshold
    if volume_ratio >= 3.0:
        spike_strength = "STRONG"
    elif volume_ratio >= 2.0:
        spike_strength = "MODERATE"
    elif volume_ratio >= spike_threshold:
        spike_strength = "WEAK"
    else:
        spike_strength = "NONE"

    # Relative Volume (compared to 50-period average)
    if len(df) >= 50:
        avg_vol_50 = float(df.tail(50)["volume"].mean())
        relative_volume = current_volume / avg_vol_50 if avg_vol_50 > 0 else 1.0
    else:
        relative_volume = volume_ratio

    # Volume trend confirmation
    # Check if volume is expanding in the direction of price
    close = float(latest["close"])
    open_p = float(latest["open"])
    price_up = close > open_p

    vol_ma_short = float(recent.tail(5)["volume"].mean())
    vol_ma_long = float(recent["volume"].mean())

    if price_up and vol_ma_short > vol_ma_long * 1.1:
        trend_confirmation = "BULLISH"
    elif not price_up and vol_ma_short > vol_ma_long * 1.1:
        trend_confirmation = "BEARISH"
    else:
        trend_confirmation = "NEUTRAL"

    # Breakout quality assessment
    breakout_quality = "NONE"
    if len(df) >= lookback + 5:
        # Check if price is near recent high/low
        recent_high = float(recent["high"].max())
        recent_low = float(recent["low"].min())
        range_size = recent_high - recent_low

        if range_size > 0:
            price_position = (close - recent_low) / range_size

            if price_position > 0.8 and volume_ratio >= 1.2:
                if volume_ratio >= 2.0:
                    breakout_quality = "STRONG"
                else:
                    breakout_quality = "MODERATE"
            elif price_position > 0.8 and volume_ratio < 1.0:
                breakout_quality = "WEAK"

            elif price_position < 0.2 and volume_ratio >= 1.2:
                if volume_ratio >= 2.0:
                    breakout_quality = "STRONG"
                else:
                    breakout_quality = "MODERATE"
            elif price_position < 0.2 and volume_ratio < 1.0:
                breakout_quality = "WEAK"

    unusual_volume = relative_volume >= 2.0

    return VolumeAnalysis(
        volume_ratio=round(volume_ratio, 2),
        is_spike=is_spike,
        spike_strength=spike_strength,
        relative_volume=round(relative_volume, 2),
        trend_confirmation=trend_confirmation,
        breakout_quality=breakout_quality,
        unusual_volume=unusual_volume,
    )
