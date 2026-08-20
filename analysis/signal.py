"""
Multi-Timeframe Signal Generator

Integrates market structure, momentum, volume, volatility, and scoring
into a comprehensive signal generation pipeline.
"""

import logging

from analysis.market_structure import analyze_market_structure
from analysis.momentum_analysis import analyze_momentum
from analysis.volume_analysis import analyze_volume
from analysis.volatility_analysis import analyze_volatility
from analysis.scoring import calculate_scores

logger = logging.getLogger(__name__)


def analyze_timeframe(df, timeframe):
    """Analyze a single timeframe and return all analysis data."""
    if df is None or len(df) < 30:
        return None

    df = df.dropna().reset_index(drop=True)
    if len(df) < 30:
        return None

    latest = df.iloc[-1]
    price = float(latest["close"])

    # Trend determination from indicators
    trend = "NEUTRAL"
    score = 0
    if price > float(latest["ema20"]): score += 1
    else: score -= 1
    if float(latest["ema20"]) > float(latest["ema50"]): score += 1
    else: score -= 1
    if float(latest["ema50"]) > float(latest["ema200"]): score += 1
    else: score -= 1
    if float(latest["macd"]) > float(latest["macd_signal"]): score += 1
    else: score -= 1
    if float(latest["rsi"]) > 50: score += 1
    else: score -= 1

    if score >= 3: trend = "BULLISH"
    elif score <= -3: trend = "BEARISH"

    # Determine strength
    price_change = 0
    if len(df) >= 10:
        price_change = (price - float(df.iloc[-10]["close"])) / float(df.iloc[-10]["close"]) * 100
    if abs(price_change) > 5: strength = "STRONG"
    elif abs(price_change) > 2: strength = "MODERATE"
    else: strength = "WEAK"

    # Run advanced analyses
    ms = analyze_market_structure(df, lookback=60)
    vol_analysis = analyze_volume(df)
    vol_regime = analyze_volatility(df)
    momentum = analyze_momentum(df)

    return {
        "timeframe": timeframe,
        "trend": trend,
        "trend_strength": strength,
        "score": score,
        "price": price,
        "rsi": float(latest["rsi"]),
        "ema20": float(latest["ema20"]),
        "ema50": float(latest["ema50"]),
        "ema200": float(latest["ema200"]),
        "macd": float(latest["macd"]),
        "macd_signal": float(latest["macd_signal"]),
        "macd_histogram": float(latest["macd_histogram"]),
        "volume_ratio": float(latest["volume_ratio"]),
        "atr": float(latest["atr"]),
        "market_structure": ms,
        "volume_analysis": vol_analysis,
        "momentum": momentum,
        "volatility": vol_regime,
    }


def generate_signal(analysis_15m, analysis_1h, analysis_4h):
    """Generate comprehensive signal from multi-timeframe analysis."""
    if any(a is None for a in [analysis_15m, analysis_1h, analysis_4h]):
        return "WAIT", 0, {}

    primary_trend = analysis_4h["trend"]
    primary_strength = analysis_4h["trend_strength"]

    timeframes_analysis = {
        "15M": analysis_15m,
        "1H": analysis_1h,
        "4H": analysis_4h,
    }

    scores = calculate_scores(
        trend=primary_trend,
        trend_strength=primary_strength,
        momentum_analysis=analysis_4h.get("momentum"),
        volume_analysis=analysis_4h.get("volume_analysis"),
        ms_analysis=analysis_4h.get("market_structure"),
        timeframes_analysis=timeframes_analysis,
        vol_analysis=analysis_4h.get("volatility"),
        levels=None,
        price=analysis_4h["price"],
    )

    return scores.signal, scores.confidence, scores