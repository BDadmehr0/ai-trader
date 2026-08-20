"""
Momentum Analysis

Advanced momentum analysis with:
- RSI state classification
- MACD state classification
- Divergence detection (regular & hidden)
- Momentum confirmation
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class MomentumAnalysis:
    rsi: float
    rsi_state: str
    macd_histogram: float
    macd_state: str
    macd_cross: str
    divergence: str
    momentum_direction: str
    strength: str


def _detect_divergence(prices, rsi_values, window=14):
    """Detect regular and hidden divergences between price and RSI."""
    n = len(prices)
    if n < window * 2:
        return "NONE"

    price_highs, price_lows, rsi_highs, rsi_lows = [], [], [], []
    half = window // 2

    for i in range(window, n - window):
        if all(prices[i] >= prices[i - j] for j in range(1, half + 1)) and \
           all(prices[i] >= prices[i + j] for j in range(1, half + 1)):
            price_highs.append((i, prices[i]))
            rsi_highs.append((i, rsi_values[i]))

        if all(prices[i] <= prices[i - j] for j in range(1, half + 1)) and \
           all(prices[i] <= prices[i + j] for j in range(1, half + 1)):
            price_lows.append((i, prices[i]))
            rsi_lows.append((i, rsi_values[i]))

    has_bullish_div = has_bearish_div = has_hidden_bullish = has_hidden_bearish = False

    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p1, p2 = price_highs[-2][1], price_highs[-1][1]
        r1, r2 = rsi_highs[-2][1], rsi_highs[-1][1]
        if p2 > p1 and r2 < r1: has_bearish_div = True
        if p2 < p1 and r2 > r1: has_hidden_bearish = True

    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p1, p2 = price_lows[-2][1], price_lows[-1][1]
        r1, r2 = rsi_lows[-2][1], rsi_lows[-1][1]
        if p2 < p1 and r2 > r1: has_bullish_div = True
        if p2 > p1 and r2 < r1: has_hidden_bullish = True

    if has_bullish_div: return "BULLISH_DIVERGENCE"
    if has_bearish_div: return "BEARISH_DIVERGENCE"
    if has_hidden_bullish: return "HIDDEN_BULLISH"
    if has_hidden_bearish: return "HIDDEN_BEARISH"
    return "NONE"


def analyze_momentum(df):
    """Analyze the momentum characteristics of the latest data."""
    if len(df) < 20:
        return MomentumAnalysis(rsi=50.0, rsi_state="NEUTRAL", macd_histogram=0.0, macd_state="NEUTRAL",
                                macd_cross="NONE", divergence="NONE", momentum_direction="FLAT", strength="WEAK")

    latest = df.iloc[-1]
    rsi = float(latest.get("rsi", 50))

    # RSI state
    if rsi >= 70: rsi_state = "OVERBOUGHT"
    elif rsi >= 60: rsi_state = "NEUTRAL_BULLISH"
    elif rsi >= 40: rsi_state = "NEUTRAL"
    elif rsi >= 30: rsi_state = "NEUTRAL_BEARISH"
    else: rsi_state = "OVERSOLD"

    # MACD state
    macd = float(latest.get("macd", 0))
    macd_signal = float(latest.get("macd_signal", 0))
    macd_hist = float(latest.get("macd_histogram", 0))
    macd_state = "BULLISH" if macd > macd_signal else "BEARISH"

    # MACD cross
    macd_cross = "NONE"
    if len(df) >= 2:
        prev_macd = float(df.iloc[-2].get("macd", 0))
        prev_signal = float(df.iloc[-2].get("macd_signal", 0))
        if prev_macd <= prev_signal and macd > macd_signal: macd_cross = "BULLISH_CROSS"
        elif prev_macd >= prev_signal and macd < macd_signal: macd_cross = "BEARISH_CROSS"

    # Divergence
    divergence_type = "NONE"
    if "rsi" in df.columns and len(df) >= 60:
        prices = df["close"].values[-60:]
        rsi_values = df["rsi"].values[-60:]
        divergence_type = _detect_divergence(prices, rsi_values)

    # Momentum direction
    momentum_dir = "FLAT"
    if len(df) >= 5:
        pchg = (float(df.iloc[-1]["close"]) - float(df.iloc[-5]["close"])) / float(df.iloc[-5]["close"])
        if pchg > 0.01: momentum_dir = "UP"
        elif pchg < -0.01: momentum_dir = "DOWN"

    # Overall strength
    bullish_signals = 0
    if rsi_state in ("NEUTRAL_BULLISH", "OVERSOLD"): bullish_signals += 1
    if macd_state == "BULLISH": bullish_signals += 1
    if macd_cross == "BULLISH_CROSS": bullish_signals += 2
    if divergence_type == "BULLISH_DIVERGENCE": bullish_signals += 3

    bearish_signals = 0
    if rsi_state in ("NEUTRAL_BEARISH", "OVERBOUGHT"): bearish_signals += 1
    if macd_state == "BEARISH": bearish_signals += 1
    if macd_cross == "BEARISH_CROSS": bearish_signals += 2
    if divergence_type == "BEARISH_DIVERGENCE": bearish_signals += 3

    diff = bullish_signals - bearish_signals
    if abs(diff) >= 3: strength = "STRONG"
    elif abs(diff) >= 1: strength = "MODERATE"
    else: strength = "WEAK"

    return MomentumAnalysis(rsi=round(rsi, 1), rsi_state=rsi_state, macd_histogram=round(macd_hist, 4),
                            macd_state=macd_state, macd_cross=macd_cross, divergence=divergence_type,
                            momentum_direction=momentum_dir, strength=strength)