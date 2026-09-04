"""
User-provided CSV candles.

Lets the whole pipeline (analysis, signals, backtest, optimizer) run on your own
data instead of an exchange feed — which is what "analyse according to my data"
actually requires. Accepted shape (column names are sniffed case-insensitively,
many common spellings supported):

    timestamp|time|date, open, high, low, close, volume[, quote_volume]

If the file has no timestamps, an evenly spaced UTC index is synthesised from
`csv_timeframe`, so any backtest on exported history still lines up.
"""

import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

CANDIDATES = {
    "timestamp": ("timestamp", "time", "date", "datetime", "open_time", "ts", "Date/Time", "Gunclosed Time"),
    "open": ("open", "o", "Open", "open_price"),
    "high": ("high", "h", "High", "high_price"),
    "low": ("low", "l", "Low", "low_price"),
    "close": ("close", "c", "Close", "last", "Price", "price"),
    "volume": ("volume", "vol", "v", "Quantity", "Base volume", "base_volume", "ticks_volume"),
    "quote_volume": ("quote_volume", "Quote volume", "qv", "quoteassetvolume", "trading_volume"),
}

TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w")

_CACHE: Dict[str, Tuple[float, pd.DataFrame]] = {}


# =====================================================================
# helpers
# =====================================================================

def timeframe_minutes(timeframe: str) -> int:
    text = str(timeframe or "").strip().lower()
    match = re.match(r"^(\d+)\s*([mhdw])", text)
    if not match:
        raise ValueError(f"unsupported timeframe: {timeframe!r}")
    count, unit = int(match.group(1)), match.group(2)
    return count * {"m": 1, "h": 60, "d": 1440, "w": 10080}[unit]


def resample_rule(timeframe: str) -> str:
    return f"{timeframe_minutes(timeframe)}min"


def normalize_columns(frame: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Map whatever the user exported onto the canonical OHLCV names."""
    lookup = {re.sub(r"[^a-z0-9]", "", str(col).lower()): col for col in frame.columns}
    mapping: Dict[str, str] = {}
    renamed = {}

    for canonical, options in CANDIDATES.items():
        for option in options:
            key = re.sub(r"[^a-z0-9]", "", option.lower())
            source = lookup.get(key)
            if source is not None and canonical not in mapping:
                mapping[canonical] = source
                renamed[source] = canonical
                break

    frame = frame.rename(columns=renamed)
    missing = [col for col in ("open", "high", "low", "close") if col not in frame.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    return frame, mapping


def _parse_timestamps(frame: pd.DataFrame, timeframe: Optional[str]) -> pd.DataFrame:
    minutes = timeframe_minutes(timeframe) if timeframe else 15

    if "timestamp" in frame.columns:
        raw = frame["timestamp"]
        if pd.api.types.is_datetime64_any_dtype(raw):
            # already parsed (a second pass happens once the timeframe is known)
            frame["timestamp"] = (raw.dt.tz_convert("UTC") if raw.dt.tz is not None
                                  else raw.dt.tz_localize("UTC"))
        else:
            numeric = pd.to_numeric(raw, errors="coerce")
            if numeric.notna().all() and numeric.dropna().max() > 1e11:     # ms epoch
                frame["timestamp"] = pd.to_datetime(numeric, unit="ms", utc=True)
            elif numeric.notna().all() and numeric.dropna().max() > 1e8:    # s epoch
                frame["timestamp"] = pd.to_datetime(numeric, unit="s", utc=True)
            else:
                frame["timestamp"] = pd.to_datetime(raw, utc=True, errors="coerce", format="mixed")
        frame = frame.dropna(subset=["timestamp"])
    else:
        end = pd.Timestamp.now(tz="UTC").floor(f"{minutes}min") - pd.Timedelta(minutes=minutes)
        start = end - pd.Timedelta(minutes=minutes * (len(frame) - 1))
        frame["timestamp"] = pd.date_range(start=start, periods=len(frame), freq=f"{minutes}min", tz="UTC")

    return frame.sort_values("timestamp").reset_index(drop=True)


def guess_timeframe(frame: pd.DataFrame) -> Optional[str]:
    """Most likely bar spacing, from the gap between rows."""
    if len(frame) < 3 or "timestamp" not in frame:
        return None
    stamps = frame["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(stamps):
        numeric = pd.to_numeric(stamps, errors="coerce")
        if numeric.notna().all() and numeric.dropna().max() > 1e8:
            stamps = pd.to_datetime(numeric.where(numeric < 1e11, numeric / 1000.0), unit="s", utc=True)
        else:
            stamps = pd.to_datetime(stamps, utc=True, errors="coerce", format="mixed")
    deltas = stamps.diff().dropna()
    if deltas.empty:
        return None
    minutes = int(round(deltas.median().total_seconds() / 60.0))
    if minutes <= 0:
        return None
    best = min(TIMEFRAMES, key=lambda tf: abs(timeframe_minutes(tf) - minutes))
    return best if abs(timeframe_minutes(best) - minutes) <= max(1, minutes * 0.25) else None


# =====================================================================
# loading
# =====================================================================

def _numeric(frame: pd.DataFrame) -> pd.DataFrame:
    for column in ("open", "high", "low", "close", "volume", "quote_volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    keep = [c for c in ("timestamp", "open", "high", "low", "close", "volume", "quote_volume")
            if c in frame.columns]
    frame = frame[keep].copy()

    if len(frame):
        frame["high"] = frame[["high", "open", "close"]].max(axis=1)
        frame["low"] = frame[["low", "open", "close"]].min(axis=1)
    return frame.reset_index(drop=True)


def load_csv(path: str | Path, timeframe: Optional[str] = None, *, use_cache: bool = True
             ) -> pd.DataFrame:
    """Read a CSV into a canonical OHLCV frame at its native timeframe."""
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")

    key = str(path.resolve())
    mtime = path.stat().st_mtime
    if use_cache and key in _CACHE and _CACHE[key][0] == mtime:
        return _CACHE[key][1].copy()

    frame = pd.read_csv(path)
    frame, _mapping = normalize_columns(frame)
    # timestamps first: the spacing that identifies the timeframe is only
    # measurable once "2026-01-05 00:00" has become a datetime
    frame = _parse_timestamps(frame, None)
    native = timeframe or guess_timeframe(frame) or "15m"
    frame = _parse_timestamps(frame, native)
    frame = _numeric(frame)

    if len(frame) < 30:
        raise ValueError(f"only {len(frame)} usable rows in {path.name} — need at least 30 candles")

    frame.attrs["timeframe"] = native
    frame.attrs["source"] = path.name
    _CACHE[key] = (mtime, frame)
    return frame.copy()


def resample(frame: pd.DataFrame, target_timeframe: str, source_timeframe: Optional[str] = None
             ) -> pd.DataFrame:
    """Aggregate to a coarser timeframe (or return as-is when equal)."""
    source_minutes = timeframe_minutes(source_timeframe or frame.attrs.get("timeframe") or "15m")
    target_minutes = timeframe_minutes(target_timeframe)

    if target_minutes == source_minutes:
        return frame.copy()
    if target_minutes < source_minutes:
        raise ValueError(
            f"CSV granularity is {source_minutes}m; cannot produce {target_minutes}m candles. "
            f"Export a finer file or set the analysis timeframes to {source_minutes}m or coarser."
        )

    aggregated = (
        frame.set_index("timestamp")
        .resample(resample_rule(target_timeframe), label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    aggregated["volume"] = aggregated["volume"].fillna(0.0)
    aggregated.attrs["timeframe"] = target_timeframe
    aggregated.attrs["source"] = frame.attrs.get("source", "csv")
    return aggregated


def profile(path: str | Path, timeframe: Optional[str] = None) -> Dict[str, Any]:
    """Preview used by the settings page (row count, span, detected timeframe)."""
    info: Dict[str, Any] = {"path": str(path)}
    try:
        frame = load_csv(path, timeframe, use_cache=False)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        info.update({"ok": False, "error": str(exc)})
        return info

    native = frame.attrs.get("timeframe") or timeframe
    minutes = timeframe_minutes(native)
    span_days = (frame["timestamp"].iloc[-1] - frame["timestamp"].iloc[0]).total_seconds() / 86400.0

    info.update({
        "ok": True,
        "rows": int(len(frame)),
        "timeframe": native,
        "start": str(frame["timestamp"].iloc[0]),
        "end": str(frame["timestamp"].iloc[-1]),
        "span_days": round(span_days, 2),
        "columns": [c for c in frame.columns if c != "timestamp"],
        "first_close": float(frame["close"].iloc[0]),
        "last_close": float(frame["close"].iloc[-1]),
        "change_pct": round((frame["close"].iloc[-1] / frame["close"].iloc[0] - 1.0) * 100.0, 2)
        if frame["close"].iloc[0] else 0.0,
        "max_candles_per_tf": int(math.floor(span_days * 1440 / minutes)) if span_days else len(frame),
        "volume_present": bool((frame.get("volume", pd.Series([0.0])) > 0).any()),
    })
    return info


def list_csvs(folder: str | Path = "data/uploads") -> List[Dict[str, Any]]:
    """Files a user dropped in the uploads folder, newest first."""
    base = Path(folder)
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / folder
    if not base.exists():
        return []

    out = []
    for path in sorted(base.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        try:
            shown = str(path.relative_to(base.parent.parent))
        except ValueError:
            shown = str(path)
        out.append({
            "name": path.name,
            "path": shown,
            "size_kb": round(path.stat().st_size / 1024.0, 1),
            "modified": pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat(timespec="seconds"),
        })
    return out


def uploads_dir() -> Path:
    base = Path(__file__).resolve().parent / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base
