from dataclasses import dataclass


@dataclass
class MarketLevels:

    support_1: float
    support_2: float

    resistance_1: float
    resistance_2: float


def find_market_levels(
    df,
    lookback=100,
) -> MarketLevels:

    recent = df.tail(
        lookback
    )

    current_price = float(
        recent["close"].iloc[-1]
    )

    # -------------------------
    # Local High / Low
    # -------------------------

    highs = (
        recent["high"]
        .sort_values()
        .tolist()
    )

    lows = (
        recent["low"]
        .sort_values()
        .tolist()
    )

    resistance_candidates = [
        value
        for value in highs
        if value > current_price
    ]

    support_candidates = [
        value
        for value in lows
        if value < current_price
    ]

    # -------------------------
    # Resistance
    # -------------------------

    resistance_candidates.sort()

    if len(resistance_candidates) >= 2:

        resistance_1 = (
            resistance_candidates[0]
        )

        resistance_2 = (
            resistance_candidates[1]
        )

    elif len(resistance_candidates) == 1:

        resistance_1 = (
            resistance_candidates[0]
        )

        resistance_2 = (
            resistance_1 * 1.02
        )

    else:

        resistance_1 = (
            current_price * 1.01
        )

        resistance_2 = (
            current_price * 1.02
        )

    # -------------------------
    # Support
    # -------------------------

    support_candidates.sort(
        reverse=True
    )

    if len(support_candidates) >= 2:

        support_1 = (
            support_candidates[0]
        )

        support_2 = (
            support_candidates[1]
        )

    elif len(support_candidates) == 1:

        support_1 = (
            support_candidates[0]
        )

        support_2 = (
            support_1 * 0.98
        )

    else:

        support_1 = (
            current_price * 0.99
        )

        support_2 = (
            current_price * 0.98
        )

    return MarketLevels(
        support_1=support_1,
        support_2=support_2,
        resistance_1=resistance_1,
        resistance_2=resistance_2,
    )