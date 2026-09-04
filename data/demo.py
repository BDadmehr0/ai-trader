"""
Offline / demo market data.

When there is no internet connection (or the exchange API is unreachable)
the trader falls back to a locally generated, realistic-looking synthetic
dataset. This keeps the CLI and the web panel fully functional for
demonstration and testing purposes.

The generated candles are clearly labelled as DEMO data so nobody mistakes
them for real market prices.

Each symbol gets its own deterministic series (based on its name) so that
switching between coins in the web panel produces visibly different data
even when offline. The three timeframes are derived from a single 15-minute
base series, so the 15m / 1h / 4h views stay consistent with each other.
"""

import math
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"

# How many candles we want for every cached timeframe.
_CANDLES = 2000

# 15-minute candles needed to resample down to _CANDLES 4h candles.
_BASE_CANDLES = _CANDLES * 16

# (timeframe, minutes_per_candle)
_TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}

# Roughly realistic starting prices for the most popular coins, so demo
# candles land in a believable range instead of all looking like BTC.
_BASE_PRICES = {
    "BTC": 96000.0,
    "ETH": 3400.0,
    "BNB": 590.0,
    "SOL": 150.0,
    "XRP": 2.20,
    "ADA": 0.70,
    "DOGE": 0.16,
    "DOT": 6.0,
    "LTC": 95.0,
    "LINK": 13.0,
    "AVAX": 27.0,
    "MATIC": 0.50,
    "TRX": 0.16,
    "SHIB": 0.00002,
    "UNI": 8.0,
    "ATOM": 5.0,
    "XLM": 0.28,
    "ETC": 20.0,
    "FIL": 3.5,
    "NEAR": 3.0,
    "APT": 6.0,
    "SUI": 1.0,
    "ARB": 0.55,
    "OP": 1.1,
    "PEPE": 0.00001,
    "TON": 3.5,
    "AAVE": 150.0,
    "CRV": 0.30,
    "INJ": 15.0,
    "SEI": 0.25,
    "WLD": 1.4,
    "MEME": 0.02,
}


def _split_symbol(symbol):
    """Normalize ``symbol`` into a (base, quote) pair.

    Accepts forms like ``"BTC/USDT"``, ``"BTC"``, ``"BTC-USDT"`` or
    ``"btc_usdt"`` and always returns uppercase parts. When only a base is
    given, ``USDT`` is assumed as the quote currency.
    """
    raw = str(symbol or "BTC/USDT").upper().replace("-", "/").replace("_", "/")
    parts = [part.strip() for part in raw.split("/") if part.strip()]

    if not parts:
        return "BTC", "USDT"

    base = parts[0]
    quote = parts[-1] if len(parts) > 1 else "USDT"
    return base, quote


def _symbol_slug(symbol):
    """Filesystem-safe cache key, e.g. ``"BTC-USDT"``."""
    base, quote = _split_symbol(symbol)
    return f"{base}-{quote}"


def _seed(slug):
    """Deterministic per-symbol RNG seed."""
    return zlib.crc32(slug.encode("utf-8"))


def _base_price(base):
    """Pick a believable starting price for a coin (or derive one)."""
    if base in _BASE_PRICES:
        return _BASE_PRICES[base]

    r = (zlib.crc32(base.encode("utf-8")) % 10000) / 10000.0
    lo, hi = math.log(0.1), math.log(5000.0)
    return round(math.exp(lo + r * (hi - lo)), 8)


def _generate_base(minutes, base_price, seed):
    """Build a single long 15-minute OHLCV series used for all timeframes."""
    rng = np.random.default_rng(seed)

    n = _BASE_CANDLES

    # A slow mean-reverting wave on top of a gentle drift, plus noise.
    # Per-candle magnitudes are scaled down so the multi-year 15m series
    # stays near the base price after resampling (noise scales with
    # sqrt(n), drift with n).
    t = np.arange(n)
    wave = np.sin(t / 300.0) * 0.06 + np.sin(t / 900.0) * 0.03
    noise = rng.normal(0.0, 0.0015, n)
    returns = 0.00003 / 16 + np.diff(np.concatenate([[0], wave])) * 0.02 + noise

    close = base_price * np.exp(np.cumsum(returns))
    close = np.maximum(close, 1e-12)

    open_ = np.empty(n)
    open_[0] = close[0] * (1 - 0.0005)
    open_[1:] = close[:-1]

    wicks = np.abs(rng.normal(0.0, 0.003, n))
    high = np.maximum(open_, close) * (1 + wicks)
    low = np.minimum(open_, close) * (1 - wicks)

    base_volume = 40.0 + 15.0 * (1 + np.sin(t / 120.0))
    volume = np.abs(rng.normal(base_volume, base_volume * 0.3, n))

    # End on the last fully-closed minute boundary.
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


def _resample_ohlcv(frame, rule):
    """Aggregate a finer frame into coarser OHLCV candles."""
    aggregated = (
        frame.resample(rule, on="timestamp")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )
    return aggregated


def _generate_frames(base_price, seed):
    """Generate consistent 15m / 1h / 4h frames for a symbol."""
    base = _generate_base(15, base_price, seed)

    return {
        "15m": base.tail(_CANDLES).reset_index(drop=True),
        "1h": _resample_ohlcv(base, "1h").tail(_CANDLES).reset_index(drop=True),
        "4h": _resample_ohlcv(base, "4h").tail(_CANDLES).reset_index(drop=True),
    }


def ensure_demo_data(symbol="BTC/USDT"):
    """
    Generate (if needed) and cache demo data for every timeframe.

    Returns a dict: timeframe -> path to cached CSV.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    slug = _symbol_slug(symbol)
    base = slug.split("-")[0]

    # Regenerate all files if any one of them is missing.
    paths = {
        timeframe: CACHE_DIR / f"{slug}_{timeframe}.csv"
        for timeframe in _TIMEFRAMES
    }

    if any(not path.exists() for path in paths.values()):
        frames = _generate_frames(_base_price(base), _seed(slug))
        for timeframe, path in paths.items():
            frames[timeframe].to_csv(path, index=False)

    return {timeframe: str(path) for timeframe, path in paths.items()}


def is_demo_data_available(symbol="BTC/USDT"):
    try:
        ensure_demo_data(symbol=symbol)
        return True
    except Exception:
        return False


def _timeframe_minutes(timeframe):
    from data.csv_source import timeframe_minutes

    return timeframe_minutes(timeframe)


def load_demo(timeframe, symbol="BTC/USDT"):
    """Load a demo frame for any timeframe / symbol pair.

    Coarser timeframes are resampled from the 15m base so the whole picture
    stays consistent; finer ones are generated directly. Anything we build is
    cached as CSV, so a symbol is generated once per run.
    """
    ensure_demo_data(symbol=symbol)

    slug = _symbol_slug(symbol)
    path = CACHE_DIR / f"{slug}_{timeframe}.csv"

    if not path.exists():
        minutes = _timeframe_minutes(timeframe)
        if minutes % 15 == 0 and minutes > 15:
            base = pd.read_csv(CACHE_DIR / f"{slug}_15m.csv")
            base["timestamp"] = pd.to_datetime(base["timestamp"], utc=True)
            from data.csv_source import resample

            frame = resample(base, timeframe, source_timeframe="15m")
        else:
            base_price = _base_price(slug.split("-")[0])
            frame = _generate_base(minutes, base_price, _seed(slug)).tail(_CANDLES).reset_index(drop=True)
            frame = frame[frame["timestamp"].dt.floor(f"{minutes}min") == frame["timestamp"]]

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame.to_csv(path, index=False)

    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def supported_timeframes(symbol="BTC/USDT", available=("1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")):
    """Every timeframe the demo generator can produce."""
    return tuple(available)
