import pandas as pd

from ta.momentum import RSIIndicator
from ta.trend import (
    EMAIndicator,
    MACD,
)
from ta.volume import OnBalanceVolumeIndicator

from config.settings import (
    EMA_FAST,
    EMA_MID,
    EMA_SLOW,
    RSI_PERIOD,
    MACD_FAST,
    MACD_SLOW,
    MACD_SIGNAL,
    VOLUME_MA_PERIOD,
)


def add_indicators(
    df: pd.DataFrame,
) -> pd.DataFrame:

    df = df.copy()

    # =========================
    # EMA
    # =========================

    df["ema20"] = EMAIndicator(
        close=df["close"],
        window=EMA_FAST,
    ).ema_indicator()

    df["ema50"] = EMAIndicator(
        close=df["close"],
        window=EMA_MID,
    ).ema_indicator()

    df["ema200"] = EMAIndicator(
        close=df["close"],
        window=EMA_SLOW,
    ).ema_indicator()

    # =========================
    # RSI
    # =========================

    rsi = RSIIndicator(
        close=df["close"],
        window=RSI_PERIOD,
    )

    df["rsi"] = rsi.rsi()

    # =========================
    # MACD
    # =========================

    macd = MACD(
        close=df["close"],
        window_fast=MACD_FAST,
        window_slow=MACD_SLOW,
        window_sign=MACD_SIGNAL,
    )

    df["macd"] = macd.macd()

    df["macd_signal"] = (
        macd.macd_signal()
    )

    df["macd_histogram"] = (
        macd.macd_diff()
    )

    # =========================
    # Volume
    # =========================

    df["volume_ma"] = (
        df["volume"]
        .rolling(VOLUME_MA_PERIOD)
        .mean()
    )

    df["volume_ratio"] = (
        df["volume"]
        / df["volume_ma"]
    )

    # =========================
    # OBV
    # =========================

    obv = OnBalanceVolumeIndicator(
        close=df["close"],
        volume=df["volume"],
    )

    df["obv"] = obv.on_balance_volume()

    # Remove rows where indicators
    # are not calculated yet.

    df = df.dropna()

    return df