"""
Indicator engine.

Everything is period/parameter driven from the settings store, so changing a
value in the web UI (or a backtest optimizer trial) immediately changes the
analysis — no code edit, no restart.

Produced columns
---------------
trend        ema_fast / ema_mid / ema_slow (+ ema20/50/200 aliases),
             ema_fast_slope, vwap, vwap_dist_pct, supertrend, supertrend_dir
momentum     rsi, rsi_stoch_k, rsi_stoch_d, macd, macd_signal, macd_histogram,
             cci, roc
strength     adx, plus_di, minus_di, di_spread
volatility   atr, atr_pct, bb_upper/mid/lower, bb_pct_b, bb_bandwidth, bb_squeeze,
             dc_upper, dc_lower
volume       volume, volume_ma, volume_ratio, vol_zscore, obv, obv_slope, mfi

All columns are float and NaN-safe (early rows), so downstream code can use
`df.iloc[-1]` after a dropna().
"""

import numpy as np
import pandas as pd
from typing import Any, Dict, List

from config.store import get_settings


# =====================================================================
# small helpers
# =====================================================================

def _ema(series, span):
    return series.ewm(span=max(1, int(span)), adjust=False).mean()


def _rma(series, period):
    """Wilder's smoothing (used by ATR / ADX / MFI)."""
    return series.ewm(alpha=1.0 / max(1, int(period)), min_periods=1, adjust=False).mean()


def _true_range(df):
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def _rolling_std(series, period):
    return series.rolling(max(2, int(period)), min_periods=1).std(ddof=0)


# =====================================================================
# main entry
# =====================================================================

def add_indicators(df, settings=None):
    """Add every indicator column used by the analysis pipeline."""
    if df is None or len(df) == 0:
        return df

    s = settings or get_settings()
    df = df.copy().reset_index(drop=True)

    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise KeyError(f"OHLCV frame is missing the '{col}' column")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    # ---------------- trend: EMAs ----------------
    df["ema_fast"] = _ema(close, s.ema_fast)
    df["ema_mid"] = _ema(close, s.ema_mid)
    df["ema_slow"] = _ema(close, s.ema_slow)
    # Legacy aliases (kept so older code / charts keep working).
    df["ema20"] = df["ema_fast"]
    df["ema50"] = df["ema_mid"]
    df["ema200"] = df["ema_slow"]

    mid = max(2, int(s.ema_mid) // 2)
    df["ema_fast_slope"] = df["ema_fast"].pct_change(mid) * 100.0

    # ---------------- momentum: RSI ----------------
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / max(1, int(s.rsi_period)), min_periods=max(1, int(s.rsi_period)),
                        adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / max(1, int(s.rsi_period)), min_periods=max(1, int(s.rsi_period)),
                        adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    df["rsi"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    rsi_min = df["rsi"].rolling(max(2, int(s.stoch_rsi_period)), min_periods=1).min()
    rsi_max = df["rsi"].rolling(max(2, int(s.stoch_rsi_period)), min_periods=1).max()
    rsi_range = (rsi_max - rsi_min).replace(0.0, np.nan)
    stoch_rsi = ((df["rsi"] - rsi_min) / rsi_range * 100.0).fillna(50.0)
    df["rsi_stoch_k"] = stoch_rsi.rolling(3, min_periods=1).mean()
    df["rsi_stoch_d"] = df["rsi_stoch_k"].rolling(3, min_periods=1).mean()

    df["roc"] = close.pct_change(max(1, int(s.atr_period))) * 100.0

    # ---------------- momentum: MACD ----------------
    macd_fast = _ema(close, s.macd_fast)
    macd_slow = _ema(close, s.macd_slow)
    df["macd"] = macd_fast - macd_slow
    df["macd_signal"] = _ema(df["macd"], s.macd_signal)
    df["macd_histogram"] = df["macd"] - df["macd_signal"]
    # Normalised histogram: comparable across BTC and a $0.02 memecoin.
    df["macd_hist_pct"] = df["macd_histogram"] / close.replace(0.0, np.nan) * 100.0

    # ---------------- volatility: ATR ----------------
    tr = _true_range(df)
    df["tr"] = tr
    df["atr"] = _rma(tr, s.atr_period)
    df["atr_pct"] = df["atr"] / close.replace(0.0, np.nan) * 100.0
    atr_avg = df["atr_pct"].rolling(max(20, int(s.atr_period) * 3), min_periods=5).mean().replace(0.0, np.nan)
    df["atr_ratio"] = (df["atr_pct"] / atr_avg).fillna(1.0)

    # ---------------- trend strength: ADX / DMI ----------------
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    atr_s = _rma(tr, s.adx_period).replace(0.0, np.nan)
    df["plus_di"] = 100.0 * _rma(plus_dm, s.adx_period) / atr_s
    df["minus_di"] = 100.0 * _rma(minus_dm, s.adx_period) / atr_s
    di_sum = (df["plus_di"] + df["minus_di"]).replace(0.0, np.nan)
    di_div = (df["plus_di"] - df["minus_di"]).abs() / di_sum
    df["adx"] = 100.0 * _rma(di_div, s.adx_period)
    df["di_spread"] = df["plus_di"] - df["minus_di"]

    # ---------------- volatility: Bollinger ----------------
    bb_period = max(2, int(s.bb_period))
    df["bb_mid"] = close.rolling(bb_period, min_periods=1).mean()
    bb_std = _rolling_std(close, bb_period) * float(s.bb_std)
    df["bb_upper"] = df["bb_mid"] + bb_std
    df["bb_lower"] = df["bb_mid"] - bb_std
    bb_width = (df["bb_upper"] - df["bb_lower"]).replace(0.0, np.nan)
    df["bb_bandwidth"] = bb_width / df["bb_mid"].replace(0.0, np.nan) * 100.0
    df["bb_pct_b"] = ((close - df["bb_lower"]) / bb_width).clip(-0.5, 1.5).fillna(0.5)
    hist_width = df["bb_bandwidth"].rolling(120, min_periods=20)
    df["bb_squeeze"] = df["bb_bandwidth"] <= hist_width.quantile(0.2)

    # ---------------- channel: Donchian (structure stops/targets) ----------------
    donchian = max(10, bb_period)
    df["dc_upper"] = high.rolling(donchian, min_periods=1).max()
    df["dc_lower"] = low.rolling(donchian, min_periods=1).min()

    # ---------------- VWAP (session anchored) ----------------
    if s.vwap_session in ("daily", "weekly") and "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        anchor = ts.dt.floor("W") if s.vwap_session == "weekly" else ts.dt.floor("D")
        typical = (high + low + close) / 3.0
        pv = typical * volume
        grp = pv.groupby(anchor.values).cumsum() / volume.groupby(anchor.values).cumsum().replace(0.0, np.nan)
        df["vwap"] = grp.ffill()
    else:
        df["vwap"] = np.nan
    df["vwap_dist_pct"] = (close / df["vwap"].replace(0.0, np.nan) - 1.0) * 100.0

    # ---------------- SuperTrend ----------------
    st_line, st_dir = _supertrend(high, low, close, df["atr"], s.supertrend_period, s.supertrend_multiplier)
    df["supertrend"] = st_line
    df["supertrend_dir"] = st_dir

    # ---------------- volume ----------------
    vol_ma_period = max(2, int(s.volume_ma_period))
    df["volume_ma"] = volume.rolling(vol_ma_period, min_periods=1).mean()
    df["volume_ratio"] = volume / df["volume_ma"].replace(0.0, np.nan)
    vol_std = _rolling_std(volume, vol_ma_period).replace(0.0, np.nan)
    df["vol_zscore"] = (volume - df["volume_ma"]) / vol_std

    direction = np.sign(close.diff()).fillna(0.0)
    df["obv"] = (direction * volume).cumsum()
    obv_look = max(3, int(s.obv_slope_period))
    avg_vol = volume.rolling(obv_look, min_periods=1).mean().replace(0.0, np.nan)
    df["obv_slope"] = (df["obv"].diff(obv_look) / (avg_vol * obv_look)).clip(-3.0, 3.0)

    # ---------------- money flow: MFI / CCI ----------------
    mfi_period = max(2, int(s.mfi_period))
    typical = (high + low + close) / 3.0
    raw_flow = typical * volume
    flow_diff = raw_flow.diff()
    pos_flow = raw_flow.where(flow_diff > 0, 0.0).rolling(mfi_period, min_periods=1).sum()
    neg_flow = raw_flow.where(flow_diff < 0, 0.0).rolling(mfi_period, min_periods=1).sum()
    mfi_ratio = pos_flow / neg_flow.replace(0.0, np.nan)
    df["mfi"] = (100.0 - (100.0 / (1.0 + mfi_ratio))).fillna(50.0)

    cci_period = max(2, int(s.cci_period))
    tp_sma = typical.rolling(cci_period, min_periods=1).mean()
    mad = (typical - tp_sma).abs().rolling(cci_period, min_periods=1).mean().replace(0.0, np.nan)
    df["cci"] = (typical - tp_sma) / (0.015 * mad)

    return df


# =====================================================================
# SuperTrend
# =====================================================================

def _supertrend(high, low, close, atr, period, multiplier):
    """SuperTrend (Oliver vector): trend line + direction (+1 up / -1 down)."""
    period = max(1, int(period))
    multiplier = float(multiplier)

    mid = ((high + low) / 2.0)
    upper = (mid + multiplier * atr).to_numpy(dtype=float)
    lower = (mid - multiplier * atr).to_numpy(dtype=float)
    close_arr = close.to_numpy(dtype=float)

    n = len(close_arr)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = np.zeros(n, dtype=float)

    if n <= period:
        return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)

    # Seed the bands at the first bar where ATR is meaningful.
    final_upper[period] = upper[period]
    final_lower[period] = lower[period]
    st[period] = lower[period] if close_arr[period] > upper[period] else upper[period]
    direction[period] = 1.0 if st[period] == lower[period] else -1.0

    for i in range(period + 1, n):
        prev_u, prev_l = final_upper[i - 1], final_lower[i - 1]
        prev_close = close_arr[i - 1]

        final_upper[i] = upper[i] if (np.isnan(prev_u) or upper[i] < prev_u or prev_close > prev_u) else prev_u
        final_lower[i] = lower[i] if (np.isnan(prev_l) or lower[i] > prev_l or prev_close < prev_l) else prev_l

        prev_line = st[i - 1]
        if prev_line == prev_u:                     # last bar was in a downtrend
            direction[i] = 1.0 if close_arr[i] > final_upper[i] else -1.0
        else:                                       # last bar was in an uptrend
            direction[i] = -1.0 if close_arr[i] < final_lower[i] else 1.0

        st[i] = final_lower[i] if direction[i] > 0 else final_upper[i]

    return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)


# =====================================================================
# convenience wrappers
# =====================================================================

def latest(df):
    """Last fully-formed candle (drops the still-open candle + warmup NaNs)."""
    if df is None or len(df) == 0:
        return None
    cols = ["close", "rsi", "macd", "macd_signal", "atr", "ema_slow"]
    usable = [c for c in cols if c in df.columns]
    clean = df.dropna(subset=usable)
    if clean.empty:
        return None
    return clean.iloc[-1]


def add_indicators_frames(frames, settings=None):
    """{label: ohlcv} -> {label: indicator frame}."""
    return {label: add_indicators(df, settings) for label, df in frames.items()}


# =====================================================================
# chart series (overlays + markers)
# =====================================================================

def _epoch_seconds(frame):
    """Unit-agnostic epoch seconds (pandas may store s/ms/us/ns)."""
    return pd.to_datetime(frame["timestamp"]).values.astype("datetime64[s]").astype("int64").tolist()


def _points(frame, column, digits: int = 8):
    if column not in frame.columns:
        return []
    stamps = _epoch_seconds(frame)
    values = pd.to_numeric(frame[column], errors="coerce")
    out = []
    for stamp, value in zip(stamps, values):
        if value != value:      # NaN
            continue
        out.append({"time": int(stamp), "value": round(float(value), digits)})
    return out


def overlay_series(frame, settings=None, max_points: int = 800) -> Dict[str, Any]:
    """Server-computed chart overlays (same math the analysis uses)."""
    if frame is None or frame.empty:
        return {}

    settings = settings or get_settings()
    if len(frame) > max_points:
        frame = frame.tail(max_points).reset_index(drop=True)

    data: Dict[str, Any] = {
        "emaFast": _points(frame, "ema_fast"),
        "emaMid": _points(frame, "ema_mid"),
        "emaSlow": _points(frame, "ema_slow"),
        "bbUpper": _points(frame, "bb_upper"),
        "bbMid": _points(frame, "bb_mid"),
        "bbLower": _points(frame, "bb_lower"),
        "vwap": _points(frame, "vwap") if settings.vwap_session != "none" else [],
        "rsi": _points(frame, "rsi", 2),
        "macd": _points(frame, "macd", 6),
        "macdSignal": _points(frame, "macd_signal", 6),
        "macdHist": _points(frame, "macd_histogram", 6),
        "adx": _points(frame, "adx", 2),
        "volume": _points(frame, "volume", 4),
    }

    # SuperTrend split by direction so the line is green above / red below.
    if "supertrend" in frame.columns:
        stamps = _epoch_seconds(frame)
        up, down = [], []
        for stamp, value, direction in zip(stamps,
                                          pd.to_numeric(frame["supertrend"], errors="coerce").tolist(),
                                          pd.to_numeric(frame.get("supertrend_dir"), errors="coerce").fillna(0).tolist()):
            if value != value:
                continue
            (up if direction > 0 else down).append({"time": int(stamp), "value": round(float(value), 8)})
        data["superTrendUp"], data["superTrendDown"] = up, down

    data["markers"] = _markers(frame)
    data["summary"] = _summary(frame, settings)
    return data


def _markers(frame) -> List[Dict[str, Any]]:
    """Flip / cross / squeeze events worth pointing at on the chart."""
    stamps = _epoch_seconds(frame)
    markers: List[Dict[str, Any]] = []

    def col(name):
        return pd.to_numeric(frame[name], errors="coerce").fillna(0).tolist() if name in frame.columns else None

    st_dir = col("supertrend_dir")
    if st_dir:
        for i in range(1, len(st_dir)):
            if st_dir[i] == st_dir[i - 1] or not st_dir[i]:
                continue
            high = float(frame["high"].iloc[i])
            if st_dir[i] > 0:
                markers.append({"time": int(stamps[i]), "position": "belowBar", "color": "#0ecb81",
                                "shape": "arrowUp", "text": "SuperTrend ↑"})
            else:
                markers.append({"time": int(stamps[i]), "position": "aboveBar", "color": "#f6465d",
                                "shape": "arrowDown", "text": "SuperTrend ↓"})
            _ = high

    hist = col("macd_histogram")
    if hist:
        for i in range(1, len(hist)):
            if hist[i - 1] <= 0 < hist[i]:
                markers.append({"time": int(stamps[i]), "position": "belowBar", "color": "#1e80ff",
                                "shape": "circle", "text": "MACD +"})
            elif hist[i - 1] >= 0 > hist[i]:
                markers.append({"time": int(stamps[i]), "position": "aboveBar", "color": "#f0b90b",
                                "shape": "circle", "text": "MACD −"})

    if "bb_squeeze" in frame.columns:
        squeeze = frame["bb_squeeze"].fillna(False).astype(bool).tolist()
        for i in range(1, len(squeeze)):
            if squeeze[i - 1] and not squeeze[i]:
                markers.append({"time": int(stamps[i]), "position": "inBar", "color": "#a26bff",
                                "shape": "square", "text": "squeeze release"})

    markers.sort(key=lambda marker: marker["time"])
    return markers[-60:]


def _summary(frame, settings) -> Dict[str, Any]:
    row = frame.dropna().iloc[-1] if len(frame.dropna()) else frame.iloc[-1]
    def num(key, default=0.0):
        try:
            value = float(row[key])
        except (KeyError, TypeError, ValueError):
            return default
        return default if value != value else round(value, 4)

    return {
        "rsi": num("rsi"),
        "adx": num("adx"),
        "atr": num("atr"),
        "atr_pct": num("atr_pct"),
        "atr_ratio": num("atr_ratio"),
        "volume_ratio": num("volume_ratio"),
        "mfi": num("mfi"),
        "cci": num("cci"),
        "bb_pct_b": num("bb_pct_b"),
        "vwap_dist_pct": num("vwap_dist_pct"),
        "supertrend_dir": num("supertrend_dir"),
        "ema_fast": num("ema_fast"),
        "ema_mid": num("ema_mid"),
        "ema_slow": num("ema_slow"),
    }
