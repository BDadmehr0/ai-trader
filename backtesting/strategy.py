from dataclasses import dataclass


@dataclass
class Signal:

    direction: str

    score: int

    confidence: float


def calculate_signal(
    row,
) -> Signal:

    score = 0

    # =========================
    # Price vs EMA20
    # =========================

    if row["close"] > row["ema20"]:

        score += 1

    else:

        score -= 1

    # =========================
    # EMA20 vs EMA50
    # =========================

    if row["ema20"] > row["ema50"]:

        score += 1

    else:

        score -= 1

    # =========================
    # EMA50 vs EMA200
    # =========================

    if row["ema50"] > row["ema200"]:

        score += 1

    else:

        score -= 1

    # =========================
    # MACD
    # =========================

    if row["macd"] > row["macd_signal"]:

        score += 1

    else:

        score -= 1

    # =========================
    # RSI
    # =========================

    if row["rsi"] > 50:

        score += 1

    else:

        score -= 1

    # =========================
    # Volume Confirmation
    # =========================

    if row["volume_ratio"] > 1.0:

        if score > 0:

            score += 1

        elif score < 0:

            score -= 1

    # =========================
    # Direction
    # =========================

    if score >= 4:

        direction = "LONG"

    elif score <= -4:

        direction = "SHORT"

    else:

        direction = "WAIT"

    confidence = (
        abs(score)
        / 6
        * 100
    )

    return Signal(
        direction=direction,
        score=score,
        confidence=confidence,
    )