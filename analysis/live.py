"""
Live signal engine with comprehensive analysis and explanations.
"""

from datetime import datetime, timezone

from analysis.indicators import add_indicators
from analysis.signal import analyze_timeframe, generate_signal
from analysis.levels import find_market_levels
from analysis.risk import create_trade_setup
from data.market_data import MarketData
from config.settings import SYMBOL, TIMEFRAMES, CANDLE_LIMIT


VERDICT = {"LONG": "BUY", "SHORT": "SELL", "WAIT": "HOLD", "NO_TRADE": "HOLD"}
TREND_FA = {"BULLISH": "صعودي", "BEARISH": "نزولي", "NEUTRAL": "خنثي"}
TREND_EN = {"BULLISH": "Bullish", "BEARISH": "Bearish", "NEUTRAL": "Neutral"}


def _generate_explanation(signal, confidence, scores, analyses, levels):
    """Generate structured explanation for why the signal was produced."""
    bullish_factors = []
    bearish_factors = []

    # Timeframe analysis
    for label in ["4H", "1H", "15M"]:
        a = analyses.get(label)
        if a is None:
            continue
        trend_en = a.get("trend", "NEUTRAL")
        if trend_en == "BULLISH":
            bullish_factors.append(f"{label} trend is Bullish")
        elif trend_en == "BEARISH":
            bearish_factors.append(f"{label} trend is Bearish")

        # RSI
        rsi = a.get("rsi", 50)
        if rsi >= 70:
            bearish_factors.append(f"{label} RSI is Overbought ({rsi:.0f})")
        elif rsi <= 30:
            bullish_factors.append(f"{label} RSI is Oversold ({rsi:.0f})")

        # Volume
        vol = a.get("volume_ratio", 1)
        if vol > 1.5:
            if trend_en == "BULLISH":
                bullish_factors.append(f"{label} Volume is Strong ({vol:.1f}x)")
            elif trend_en == "BEARISH":
                bearish_factors.append(f"{label} Volume is Strong ({vol:.1f}x)")

    # Market structure
    for label in ["4H", "1H"]:
        a = analyses.get(label)
        if a is None:
            continue
        ms = a.get("market_structure")
        if ms:
            if ms.hh_count > 0:
                bullish_factors.append(f"{label}: {ms.hh_count} Higher Highs")
            if ms.hl_count > 0:
                bullish_factors.append(f"{label}: {ms.hl_count} Higher Lows")
            if ms.ll_count > 0:
                bearish_factors.append(f"{label}: {ms.ll_count} Lower Lows")
            if ms.lh_count > 0:
                bearish_factors.append(f"{label}: {ms.lh_count} Lower Highs")
            if ms.strength in ("STRONG", "MODERATE"):
                factor = f"{label} structure is {ms.strength} {ms.trend}"
                if ms.trend == "BULLISH":
                    bullish_factors.append(factor)
                elif ms.trend == "BEARISH":
                    bearish_factors.append(factor)

    # Momentum
    mom = analyses.get("4H", {}).get("momentum")
    if mom:
        if mom.divergence == "BULLISH_DIVERGENCE":
            bullish_factors.append("Bullish Divergence detected on 4H")
        elif mom.divergence == "BEARISH_DIVERGENCE":
            bearish_factors.append("Bearish Divergence detected on 4H")
        if mom.macd_cross == "BULLISH_CROSS":
            bullish_factors.append("MACD Bullish Cross on 4H")
        elif mom.macd_cross == "BEARISH_CROSS":
            bearish_factors.append("MACD Bearish Cross on 4H")

    # Support/Resistance
    if levels:
        price = analyses.get("4H", {}).get("price", 0)
        if price > 0:
            r1 = levels.resistance_1
            s1 = levels.support_1
            if r1 and r1 > 0:
                dist_r = (r1 - price) / price * 100
                if 0 < dist_r < 1:
                    bearish_factors.append(f"Major Resistance nearby ({r1:,.0f}, {dist_r:.1f}% away)")
                elif 1 <= dist_r < 3:
                    bearish_factors.append(f"Resistance approaching ({r1:,.0f})")
            if s1 and s1 > 0:
                dist_s = (price - s1) / price * 100
                if 0 < dist_s < 1:
                    bullish_factors.append(f"Major Support nearby ({s1:,.0f}, {dist_s:.1f}% away)")
                elif 1 <= dist_s < 3:
                    bullish_factors.append(f"Support nearby ({s1:,.0f})")

    return bullish_factors, bearish_factors


def _factors_to_reasons(bullish, bearish):
    """Convert factor lists to plain reason strings."""
    reasons = []
    reasons.append(f"Signal: {bullish + bearish}")
    for f in bullish:
        reasons.append(f"Bullish: {f}")
    for f in bearish:
        reasons.append(f"Bearish: {f}")
    return reasons


def build_signal_report(market, symbol=SYMBOL):
    """Fetch latest data and build the full signal report dict."""
    symbol = symbol or SYMBOL

    frames = {}
    analyses = {}

    for label, tf in TIMEFRAMES.items():
        df = market.get_ohlcv(symbol, tf, CANDLE_LIMIT)
        df = add_indicators(df)
        analyses[label] = analyze_timeframe(df, label)
        frames[label] = df

    a_15m = analyses.get("15M")
    a_1h = analyses.get("1H")
    a_4h = analyses.get("4H")

    signal, confidence, scores = generate_signal(a_15m, a_1h, a_4h)

    price = a_4h["price"] if a_4h else 0
    change_pct = 0.0

    # 24h change
    ticker = market.get_ticker(symbol)
    if ticker and ticker.get("change_pct") is not None:
        change_pct = float(ticker["change_pct"])

    # Levels
    levels = None
    if "1H" in frames and frames["1H"] is not None:
        levels = find_market_levels(frames["1H"])

    # Trade setup
    atr_val = a_4h["atr"] if a_4h and a_4h.get("atr") else price * 0.01
    s1 = levels.support_1 if levels else price * 0.99
    r1 = levels.resistance_1 if levels else price * 1.01
    setup = create_trade_setup(signal, price, atr_val, s1, r1, confidence)

    verdict = VERDICT.get(signal, "HOLD")

    # Generate explanations
    bullish_factors, bearish_factors = _generate_explanation(signal, confidence, scores, analyses, levels)

    explanation = _build_explanation(verdict, setup)
    reasons = _factors_to_reasons(bullish_factors, bearish_factors)
    all_factors = {"bullish": bullish_factors, "bearish": bearish_factors}

    return {
        "symbol": symbol,
        "signal": signal,
        "verdict": verdict,
        "confidence": confidence,
        "price": price,
        "change_24h_pct": change_pct,
        "reasons": reasons[:15],
        "factors": all_factors,
        "explanation": explanation,
        "timeframes": {
            label: _serialize_analysis(a) for label, a in analyses.items() if a
        },
        "levels": {
            "support_1": levels.support_1 if levels else price * 0.99,
            "support_2": levels.support_2 if levels else price * 0.98,
            "resistance_1": levels.resistance_1 if levels else price * 1.01,
            "resistance_2": levels.resistance_2 if levels else price * 1.02,
        },
        "scores": {
            "long_score": scores.long_score if hasattr(scores, 'long_score') else 0,
            "short_score": scores.short_score if hasattr(scores, 'short_score') else 0,
            "neutral_score": scores.neutral_score if hasattr(scores, 'neutral_score') else 0,
            "trend_score": scores.trend_score if hasattr(scores, 'trend_score') else 0,
            "momentum_score": scores.momentum_score if hasattr(scores, 'momentum_score') else 0,
            "volume_score": scores.volume_score if hasattr(scores, 'volume_score') else 0,
        } if hasattr(scores, 'long_score') else {},
        "setup": {
            "status": setup.status,
            "entry": setup.entry,
            "stop_loss": setup.stop_loss,
            "take_profit_1": setup.take_profit_1,
            "take_profit_2": setup.take_profit_2,
            "risk_reward_1": setup.risk_reward_1,
            "risk_reward_2": setup.risk_reward_2,
        },
        "live": market.is_live,
        "error": market.last_error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _serialize_analysis(analysis):
    if analysis is None:
        return {}
    return {
        "timeframe": analysis.get("timeframe"),
        "trend": analysis.get("trend", "NEUTRAL"),
        "trend_fa": TREND_FA.get(analysis.get("trend", ""), analysis.get("trend", "")),
        "trend_en": TREND_EN.get(analysis.get("trend", ""),),
        "score": analysis.get("score", 0),
        "price": analysis.get("price", 0),
        "rsi": analysis.get("rsi", 50),
        "ema20": analysis.get("ema20", 0),
        "ema50": analysis.get("ema50", 0),
        "ema200": analysis.get("ema200", 0),
        "macd": analysis.get("macd", 0),
        "macd_signal": analysis.get("macd_signal", 0),
        "macd_histogram": analysis.get("macd_histogram", 0),
        "volume_ratio": analysis.get("volume_ratio", 1),
        "atr": analysis.get("atr", 0),
    }


def _build_explanation(verdict, setup):
    if verdict == "BUY":
        return f"Buy (LONG) signal. Entry at {setup.entry:,.0f}, Stop Loss {setup.stop_s:,.0f}, Target {setup.take_profit_1:,.0f}."
    if verdict == "SELL":
        return f"Sell (SHORT) signal. Entry at {setup.entry:,.0f}, Stop Loss {setup.stop_loss:,.0f}, Target {setup.take_profit_1:,.0f}."
    return "Market conditions are unclear. Waiting for clearer signal."