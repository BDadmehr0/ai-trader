from dataclasses import dataclass


@dataclass
class TimeframeAnalysis:

    timeframe: str

    trend: str

    score: int

    price: float

    rsi: float

    ema20: float

    ema50: float

    ema200: float

    macd: float

    macd_signal: float

    macd_histogram: float

    volume_ratio: float

    atr: float


def analyze_timeframe(
    df,
    timeframe: str,
) -> TimeframeAnalysis:

    latest = df.iloc[-1]

    score = 0

    price = float(
        latest["close"]
    )

    rsi = float(
        latest["rsi"]
    )

    ema20 = float(
        latest["ema20"]
    )

    ema50 = float(
        latest["ema50"]
    )

    ema200 = float(
        latest["ema200"]
    )

    macd = float(
        latest["macd"]
    )

    macd_signal = float(
        latest["macd_signal"]
    )

    macd_histogram = float(
        latest["macd_histogram"]
    )

    volume_ratio = float(
        latest["volume_ratio"]
    )

    atr = float(
        latest["atr"]
    )

    # Price > EMA20

    if price > ema20:
        score += 1
    else:
        score -= 1

    # EMA20 > EMA50

    if ema20 > ema50:
        score += 1
    else:
        score -= 1

    # EMA50 > EMA200

    if ema50 > ema200:
        score += 1
    else:
        score -= 1

    # MACD

    if macd > macd_signal:
        score += 1
    else:
        score -= 1

    # RSI

    if rsi > 50:
        score += 1
    else:
        score -= 1

    # Trend

    if score >= 3:

        trend = "BULLISH"

    elif score <= -3:

        trend = "BEARISH"

    else:

        trend = "NEUTRAL"

    return TimeframeAnalysis(
        timeframe=timeframe,
        trend=trend,
        score=score,
        price=price,
        rsi=rsi,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        macd=macd,
        macd_signal=macd_signal,
        macd_histogram=macd_histogram,
        volume_ratio=volume_ratio,
        atr=atr,
    )


def generate_signal(
    analysis_15m,
    analysis_1h,
    analysis_4h,
):

    score = 0

    # =========================
    # 4H
    # Main Market Direction
    # =========================

    if analysis_4h.trend == "BULLISH":

        score += 3

    elif analysis_4h.trend == "BEARISH":

        score -= 3

    # =========================
    # 1H
    # Setup Confirmation
    # =========================

    if analysis_1h.trend == "BULLISH":

        score += 2

    elif analysis_1h.trend == "BEARISH":

        score -= 2

    # =========================
    # 15M
    # Entry Direction
    # =========================

    if analysis_15m.trend == "BULLISH":

        score += 1

    elif analysis_15m.trend == "BEARISH":

        score -= 1

    # =========================
    # Final
    # =========================

    if score >= 5:

        signal = "LONG"

    elif score <= -5:

        signal = "SHORT"

    else:

        signal = "WAIT"

    # =========================
    # Confidence
    # =========================

    max_score = 6

    confidence = int(
        abs(score)
        / max_score
        * 100
    )

    return signal, confidence