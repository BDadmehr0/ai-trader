from config.settings import (
    PULLBACK_DISTANCE,
    MIN_VOLUME_RATIO,
)


def get_4h_regime(row):

    bullish = (

        row["close_4h"]
        > row["ema200_4h"]

        and

        row["ema20_4h"]
        > row["ema50_4h"]

        and

        row["ema50_4h"]
        > row["ema200_4h"]

        and

        row["macd_4h"]
        > row["macd_signal_4h"]

    )

    bearish = (

        row["close_4h"]
        < row["ema200_4h"]

        and

        row["ema20_4h"]
        < row["ema50_4h"]

        and

        row["ema50_4h"]
        < row["ema200_4h"]

        and

        row["macd_4h"]
        < row["macd_signal_4h"]

    )

    if bullish:

        return "BULLISH"

    if bearish:

        return "BEARISH"

    return "NEUTRAL"


def is_long_pullback(row):

    trend = (

        row["ema20_1h"]
        > row["ema50_1h"]

        and

        row["ema50_1h"]
        > row["ema200_1h"]

    )

    distance = (

        abs(
            row["close_1h"]
            - row["ema20_1h"]
        )

        /

        row["close_1h"]

    )

    price_near_ema = (

        distance
        <= PULLBACK_DISTANCE

    )

    rsi_ok = (

        40
        <= row["rsi_1h"]
        <= 60

    )

    return (

        trend

        and

        price_near_ema

        and

        rsi_ok

    )


def is_short_pullback(row):

    trend = (

        row["ema20_1h"]
        < row["ema50_1h"]

        and

        row["ema50_1h"]
        < row["ema200_1h"]

    )

    distance = (

        abs(
            row["close_1h"]
            - row["ema20_1h"]
        )

        /

        row["close_1h"]

    )

    price_near_ema = (

        distance
        <= PULLBACK_DISTANCE

    )

    rsi_ok = (

        40
        <= row["rsi_1h"]
        <= 60

    )

    return (

        trend

        and

        price_near_ema

        and

        rsi_ok

    )


def long_entry_trigger(
    previous,
    current,
):

    macd_cross = (

        previous["macd"]
        <= previous[
            "macd_signal"
        ]

        and

        current["macd"]
        >

        current[
            "macd_signal"
        ]

    )

    rsi_confirm = (

        current["rsi"]
        > 50

    )

    volume_confirm = (

        current[
            "volume_ratio"
        ]

        >= MIN_VOLUME_RATIO

    )

    return (

        macd_cross

        and

        rsi_confirm

        and

        volume_confirm

    )


def short_entry_trigger(
    previous,
    current,
):

    macd_cross = (

        previous["macd"]
        >= previous[
            "macd_signal"
        ]

        and

        current["macd"]
        <

        current[
            "macd_signal"
        ]

    )

    rsi_confirm = (

        current["rsi"]
        < 50

    )

    volume_confirm = (

        current[
            "volume_ratio"
        ]

        >= MIN_VOLUME_RATIO

    )

    return (

        macd_cross

        and

        rsi_confirm

        and

        volume_confirm

    )


def generate_signal(
    previous,
    current,
):

    regime = get_4h_regime(
        current
    )

    if regime == "BULLISH":

        if not is_long_pullback(
            current
        ):

            return "WAIT"

        if long_entry_trigger(
            previous,
            current,
        ):

            return "LONG"

    if regime == "BEARISH":

        if not is_short_pullback(
            current
        ):

            return "WAIT"

        if short_entry_trigger(
            previous,
            current,
        ):

            return "SHORT"

    return "WAIT"