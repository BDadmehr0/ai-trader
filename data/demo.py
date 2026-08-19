"""
Offline / demo market data.

When there is no internet connection (or the exchange API is unreachable)
the trader falls back to a locally generated, realistic-looking synthetic
dataset. This keeps the CLI and the web panel fully functional for
demonstration and testing purposes.

The generated candles are clearly labelled as DEMO data so nobody mistakes
them for real market prices.
"""

from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"

# How many candles we want for the longest timeframe.
_CANDLES = 2000

# (timeframe, minutes_per_candle)
_TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


def _generate_frame(timeframe, minutes, seed):
    """Build a realistic-looking synthetic OHLCV frame."""
    rng = np.random.default_rng(seed)

    n = _CANDLES

    # A slow mean-reverting wave on top of a gentle drift, plus noise.
    t = np.arange(n)
    wave = np.sin(t / 300.0) * 0.06 + np.sin(t / 900.0) * 0.03
    noise = rng.normal(0.0, 0.006, n)
    returns = 0.00003 + np.diff(np.concatenate([[0], wave])) * 0.02 + noise

    close = 96000.0 * np.exp(np.cumsum(returns))
    close = np.maximum(close, 1.0)

    open_ = np.empty(n)
    open_[0] = close[0] * (1 - 0.0005)
    open_[1:] = close[:-1]

    wicks = np.abs(rng.normal(0.0, 0.003, n))
    high = np.maximum(open_, close) * (1 + wicks)
    low = np.minimum(open_, close) * (1 - wicks)

    base_volume = 40.0 + 15.0 * (1 + np.sin(t / 120.0))
    volume = np.abs(rng.normal(base_volume, base_volume * 0.3, n))

    # Round-trip timestamps ending at the current (closed) minute boundary.
    end = pd.Timestamp.now(tz="UTC").floor(f"{minutes}min") - pd.Timedelta(
        minutes=minutes
    )
    start = end - pd.Timedelta(minutes=minutes * (n - 1))
    timestamps = pd.date_range(start=start, periods=n, freq=f"{minutes}min", tz="UTC")

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def ensure_demo_data():
    """
    Generate (if needed) and cache demo data for every timeframe.

    Returns a dict: timeframe -> path to cached CSV.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    paths = {}
    for idx, (timeframe, minutes) in enumerate(_TIMEFRAMES.items()):
        path = CACHE_DIR / f"BTC-USDT_{timeframe}.csv"
        if not path.exists():
            frame = _generate_frame(timeframe, minutes, seed=42 + idx * 17)
            frame.to_csv(path, index=False)
        paths[timeframe] = str(path)

    return paths


def is_demo_data_available():
    try:
        ensure_demo_data()
        return True
    except Exception:
        return False


def load_demo(timeframe):
    """Load a demo frame for a given timeframe."""
    ensure_demo_data()
    path = CACHE_DIR / f"BTC-USDT_{timeframe}.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df
