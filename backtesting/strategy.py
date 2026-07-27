from dataclasses import dataclass


@dataclass
class MarketSignal:

    direction: str

    score: int

    confidence: float

    regime: str

    reason: list


def trend_score(row):

    score = 0

    reasons = []

    if row["close"] > row["ema20"]:

        score += 1

        reasons.append(
            "Price above EMA20"
        )

    else:

        score -= 1

        reasons.append(
            "Price below EMA20"
        )

    if row["ema20"] > row["ema50"]:

        score += 1

        reasons.append(
            "EMA20 above EMA50"
        )

    else:

        score -= 1

        reasons.append(
            "EMA20 below EMA50"
        )

    if row["ema50"] > row["ema200"]:

        score += 1

        reasons.append(
            "EMA50 above EMA200"
        )

    else:

        score -= 1

        reasons.append(
            "EMA50 below EMA200"
        )

    if row["macd"] > row["macd_signal"]:

        score += 1

        reasons.append(
            "MACD bullish"
        )

    else:

        score -= 1

        reasons.append(
            "MACD bearish"
        )

    if row["rsi"] > 50:

        score += 1

        reasons.append(
            "RSI above 50"
        )

    else:

        score -= 1

        reasons.append(
            "RSI below 50"
        )

    return score, reasons


def get_market_regime(row):

    score, reasons = trend_score(row)

    if score >= 3:

        regime = "BULLISH"

    elif score <= -3:

        regime = "BEARISH"

    else:

        regime = "NEUTRAL"

    return {
        "regime": regime,
        "score": score,
        "reasons": reasons,
    }


def generate_mtf_signal(
    row_4h,
    row_1h,
    row_15m,
):

    regime_data = get_market_regime(
        row_4h
    )

    score_4h = (
        regime_data["score"]
    )

    score_1h, reasons_1h = (
        trend_score(row_1h)
    )

    score_15m, reasons_15m = (
        trend_score(row_15m)
    )

    final_score = 0

    reasons = []

    # -------------------------
    # 4H Main Trend
    # -------------------------

    if score_4h >= 3:

        final_score += 3

        reasons.append(
            "4H bullish regime"
        )

    elif score_4h <= -3:

        final_score -= 3

        reasons.append(
            "4H bearish regime"
        )

    # -------------------------
    # 1H Setup
    # -------------------------

    if score_1h >= 3:

        final_score += 2

        reasons.append(
            "1H confirms bullish setup"
        )

    elif score_1h <= -3:

        final_score -= 2

        reasons.append(
            "1H confirms bearish setup"
        )

    # -------------------------
    # 15M Entry
    # -------------------------

    if score_15m >= 3:

        final_score += 1

        reasons.append(
            "15M bullish entry"
        )

    elif score_15m <= -3:

        final_score -= 1

        reasons.append(
            "15M bearish entry"
        )

    # -------------------------
    # Direction
    # -------------------------

    if final_score >= 5:

        direction = "LONG"

    elif final_score <= -5:

        direction = "SHORT"

    else:

        direction = "WAIT"

    confidence = (
        abs(final_score)
        / 6
        * 100
    )

    return MarketSignal(
        direction=direction,
        score=final_score,
        confidence=confidence,
        regime=regime_data["regime"],
        reason=reasons,
    )