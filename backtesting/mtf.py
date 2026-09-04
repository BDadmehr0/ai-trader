"""
Multi-timeframe preparation.

The higher frames are aligned onto the base frame with `merge_asof(direction=
"backward")`, i.e. every base candle only ever sees HTF candles that had
*already closed* — that is what keeps a backtest honest (no lookahead).

Columns get generic `_mid` / `_high` suffixes so the strategy works whatever
timeframes the user configured (15m/1h/4h, 5m/30m/2h, ...).
"""

import pandas as pd

from utils.timeutils import normalize_timestamps


def _suffix(frame: pd.DataFrame, suffix: str, skip=("timestamp",)) -> pd.DataFrame:
    return frame.rename(
        columns={
            column: f"{column}_{suffix}"
            for column in frame.columns
            if column not in skip
        }
    )


def prepare_mtf_data(df_base, df_mid, df_high, drop_open_candle=True) -> pd.DataFrame:
    """Merge three indicator frames onto the base timeframe."""
    if df_base is None or df_mid is None or df_high is None:
        raise ValueError("prepare_mtf_data needs three frames (base, mid, higher)")

    base = df_base.copy()
    mid = df_mid.copy()
    high = df_high.copy()

    if drop_open_candle:
        # The newest candle of every frame is still forming — exclude it.
        base = base.iloc[:-1].copy()
        mid = mid.iloc[:-1].copy()
        high = high.iloc[:-1].copy()

    base = base.sort_values("timestamp").reset_index(drop=True)
    mid = _suffix(mid.sort_values("timestamp"), "mid")
    high = _suffix(high.sort_values("timestamp"), "high")

    # One dtype for all three keys: the frames can come from different paths
    # (cache = seconds, exchange = ms, demo = µs) and pandas 3 refuses to merge
    # datetime64 columns whose resolutions differ. See utils/timeutils.py.
    for frame in (base, mid, high):
        normalize_timestamps(frame, inplace=True)

    merged = pd.merge_asof(base, mid, on="timestamp", direction="backward")
    merged = pd.merge_asof(merged, high, on="timestamp", direction="backward")

    required = [column for column in merged.columns if column.endswith(("_mid", "_high"))]
    merged = merged.dropna(subset=required)

    return merged.reset_index(drop=True)


def mtf_summary(df: pd.DataFrame) -> dict:
    """Row counts used by the backtest report / UI."""
    return {
        "rows": int(len(df)),
        "start": str(df["timestamp"].iloc[0]) if len(df) else None,
        "end": str(df["timestamp"].iloc[-1]) if len(df) else None,
        "columns": int(df.shape[1]),
    }
