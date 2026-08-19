import pandas as pd

from config.settings import (
    EMA_FAST,
    EMA_MID,
    EMA_SLOW,
    RSI_PERIOD,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    ATR_PERIOD,
    VOLUME_MA_PERIOD,
)


def add_indicators(df):

    df = df.copy()

    # =========================
    # EMA
    # =========================

    df["ema20"] = (
        df["close"]
        .ewm(
            span=EMA_FAST,
            adjust=False,
        )
        .mean()
    )

    df["ema50"] = (
        df["close"]
        .ewm(
            span=EMA_MID,
            adjust=False,
        )
        .mean()
    )

    df["ema200"] = (
        df["close"]
        .ewm(
            span=EMA_SLOW,
            adjust=False,
        )
        .mean()
    )

    # =========================
    # RSI
    # =========================

    delta = df["close"].diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = (
        gain
        .ewm(
            alpha=1 / RSI_PERIOD,
            min_periods=RSI_PERIOD,
            adjust=False,
        )
        .mean()
    )

    avg_loss = (
        loss
        .ewm(
            alpha=1 / RSI_PERIOD,
            min_periods=RSI_PERIOD,
            adjust=False,
        )
        .mean()
    )

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            float("nan"),
        )
    )

    df["rsi"] = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    # =========================
    # MACD
    # =========================

    ema_fast = (
        df["close"]
        .ewm(
            span=MACD_FAST,
            adjust=False,
        )
        .mean()
    )

    ema_slow = (
        df["close"]
        .ewm(
            span=MACD_SLOW,
            adjust=False,
        )
        .mean()
    )

    df["macd"] = (
        ema_fast
        - ema_slow
    )

    df["macd_signal"] = (
        df["macd"]
        .ewm(
            span=MACD_SIGNAL,
            adjust=False,
        )
        .mean()
    )

    df["macd_histogram"] = (
        df["macd"]
        - df["macd_signal"]
    )

    # =========================
    # ATR
    # =========================

    previous_close = (
        df["close"].shift(1)
    )

    tr1 = (
        df["high"]
        - df["low"]
    )

    tr2 = (
        df["high"]
        - previous_close
    ).abs()

    tr3 = (
        df["low"]
        - previous_close
    ).abs()

    true_range = pd.concat(
        [
            tr1,
            tr2,
            tr3,
        ],
        axis=1,
    ).max(axis=1)

    df["atr"] = (
        true_range
        .ewm(
            alpha=1 / ATR_PERIOD,
            adjust=False,
        )
        .mean()
    )

    # =========================
    # Volume Ratio
    # =========================

    volume_ma = (
        df["volume"]
        .rolling(
            VOLUME_MA_PERIOD
        )
        .mean()
    )

    df["volume_ratio"] = (
        df["volume"]
        / volume_ma
    )

    return df