"""
Live signal engine.

Turns the latest market data for the default pair (BTC/USDT) into a single,
human-friendly decision: BUY, SELL or HOLD — backed by the advanced
multi-timeframe analysis that already exists in this project.

Everything is collected into one plain dict that the CLI and the web panel
can both render.
"""

from datetime import datetime, timezone

import pandas as pd

from analysis.indicators import add_indicators
from analysis.signal import analyze_timeframe, generate_signal
from analysis.levels import find_market_levels
from analysis.risk import create_trade_setup
from data.market_data import MarketData
from config.settings import SYMBOL, TIMEFRAMES, CANDLE_LIMIT

# Human friendly verdicts
VERDICT = {
    "LONG": "BUY",
    "SHORT": "SELL",
    "WAIT": "HOLD",
}

TREND_FA = {
    "BULLISH": "صعودی",
    "BEARISH": "نزولی",
    "NEUTRAL": "خنثی",
}

TREND_EN = {
    "BULLISH": "Bullish",
    "BEARISH": "Bearish",
    "NEUTRAL": "Neutral",
}


def _explain_tf(analysis):
    """Plain-language bullet points for a single timeframe."""
    points = []

    points.append(
        f"روند {analysis.timeframe}: {TREND_FA.get(analysis.trend, analysis.trend)}"
    )

    if analysis.price > analysis.ema20:
        points.append(
            f"قیمت بالاتر از میانگین ۲۰ ({analysis.ema20:,.0f}) است → قدرت صعود"
        )
    else:
        points.append(
            f"قیمت پایین‌تر از میانگین ۲۰ ({analysis.ema20:,.0f}) است → فشار نزولی"
        )

    rsi = analysis.rsi
    if rsi >= 70:
        points.append(
            f"RSI حدود {rsi:.0f} است → منطقه اشباع خرید (احتیاط)"
        )
    elif rsi <= 30:
        points.append(
            f"RSI حدود {rsi:.0f} است → منطقه اشباع فروش (فرصت خرید)"
        )
    else:
        points.append(f"RSI حدود {rsi:.0f} است → مومنتوم متعادل")

    if analysis.macd_histogram > 0:
        points.append("مومنتوم مکدی مثبت است (MACD بالای سیگنال)")
    else:
        points.append("مومنتوم مکدی منفی است (MACD زیر سیگنال)")

    points.append(
        f"حجم معاملات {analysis.volume_ratio:.2f} برابر میانگین"
    )

    return points


def build_signal_report(market, symbol=SYMBOL):
    """Fetch latest data and build the full signal report dict."""
    symbol = symbol or SYMBOL

    frames = {}
    analyses = {}

    # Fetch + indicator computation per timeframe.
    for label, tf in TIMEFRAMES.items():
        df = market.get_ohlcv(symbol, tf, CANDLE_LIMIT)
        df = add_indicators(df)
        df = df.dropna().reset_index(drop=True)
        frames[label] = df
        analyses[label] = analyze_timeframe(df, label)

    a_15m = analyses["15M"]
    a_1h = analyses["1H"]
    a_4h = analyses["4H"]

    signal, confidence = generate_signal(a_15m, a_1h, a_4h)

    # Current price from the highest timeframe (4H) latest close.
    price = a_4h.price

    # 24h change (best effort).
    change_pct = _compute_change(frames["1H"])
    ticker = market.get_ticker(symbol)
    if ticker and ticker.get("change_pct") is not None:
        change_pct = float(ticker["change_pct"])

    # Support / resistance from the 1H frame.
    levels = find_market_levels(frames["1H"])

    # Trade setup (entry / stop / targets).
    setup = create_trade_setup(
        signal,
        price,
        a_4h.atr if a_4h.atr else price * 0.01,
        levels.support_1,
        levels.resistance_1,
        confidence,
    )

    verdict = VERDICT.get(signal, "HOLD")

    reasons = []
    reasons.extend(_explain_tf(a_4h))
    reasons.extend(_explain_tf(a_1h))
    reasons.extend(_explain_tf(a_15m))

    explanation = _build_explanation(verdict, setup)

    return {
        "symbol": symbol,
        "signal": signal,  # LONG / SHORT / WAIT
        "verdict": verdict,  # BUY / SELL / HOLD
        "confidence": confidence,
        "price": price,
        "change_24h_pct": change_pct,
        "reasons": reasons,
        "explanation": explanation,
        "timeframes": {
            label: _serialize_analysis(analysis)
            for label, analysis in analyses.items()
        },
        "levels": {
            "support_1": levels.support_1,
            "support_2": levels.support_2,
            "resistance_1": levels.resistance_1,
            "resistance_2": levels.resistance_2,
        },
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


# ===========================================================
# Helpers
# ===========================================================

def _compute_change(df_1h):
    if len(df_1h) < 2:
        return 0.0
    last = float(df_1h["close"].iloc[-1])
    prev = float(df_1h["close"].iloc[-24]) if len(df_1h) >= 24 else float(
        df_1h["close"].iloc[0]
    )
    if prev == 0:
        return 0.0
    return (last / prev - 1.0) * 100.0


def _serialize_analysis(analysis):
    return {
        "timeframe": analysis.timeframe,
        "trend": analysis.trend,
        "trend_fa": TREND_FA.get(analysis.trend, analysis.trend),
        "trend_en": TREND_EN.get(analysis.trend, analysis.trend),
        "score": analysis.score,
        "price": analysis.price,
        "rsi": analysis.rsi,
        "ema20": analysis.ema20,
        "ema50": analysis.ema50,
        "ema200": analysis.ema200,
        "macd": analysis.macd,
        "macd_signal": analysis.macd_signal,
        "macd_histogram": analysis.macd_histogram,
        "volume_ratio": analysis.volume_ratio,
        "atr": analysis.atr,
    }


def _build_explanation(verdict, setup):
    if verdict == "BUY":
        return (
            f"خرید (LONG) پیشنهاد می‌شود. ورود در {setup.entry:,.0f}، "
            f"حد ضرر روی {setup.stop_loss:,.0f} و هدف اول {setup.take_profit_1:,.0f}."
        )
    if verdict == "SELL":
        return (
            f"فروش (SHORT) پیشنهاد می‌شود. ورود در {setup.entry:,.0f}، "
            f"حد ضرر روی {setup.stop_loss:,.0f} و هدف اول {setup.take_profit_1:,.0f}."
        )
    return (
        "شرایط مشخص نیست؛ فعلاً صبر کنید (HOLD). با هماهنگ شدن روند "
        "چارچوب‌های زمانی، سیگنال خرید یا فروش صادر خواهد شد."
    )
