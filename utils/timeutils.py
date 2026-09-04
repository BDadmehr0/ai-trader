"""
Canonical timestamps for OHLCV frames.

Every frame in the app carries a timezone-aware ``timestamp`` column, but the
sources do not agree on the *resolution*:

* ccxt/exchange  → epoch **milliseconds**
* disk cache     → epoch **seconds** (JSON friendly)
* CSV            → ms or s depending on how big the numbers are
* demo generator → whatever pandas infers from the ISO strings (µs)

Pandas keeps that resolution on the column, and since pandas 3 merging two
frames whose keys are ``datetime64[ms, UTC]`` and ``datetime64[s, UTC]`` is a
hard error instead of a silent cast::

    MergeError: incompatible merge keys [0] ... must be the same type

That bites the backtest/optimizer as soon as two timeframes come from different
paths — e.g. one candle frame served from the cache and another fetched fresh,
or an exchange frame next to a demo fallback.

So: the data layer normalises every frame it hands out to one dtype
(``datetime64[ms, UTC]`` — the unit ccxt speaks, and fine enough for 1-minute
bars) and the merge helpers normalise defensively as well.
"""

import warnings

import pandas as pd

TIMESTAMP_COLUMN = "timestamp"

#: The one dtype every OHLCV frame uses after normalisation.
TIMESTAMP_DTYPE = "datetime64[ms, UTC]"


def is_canonical(values) -> bool:
    """True when a column already uses :data:`TIMESTAMP_DTYPE`."""
    dtype = getattr(values, "dtype", None)
    return dtype is not None and str(dtype) == TIMESTAMP_DTYPE


def _parse(values) -> pd.Series:
    """``pd.to_datetime`` without the "could not infer format" noise on messy CSVs."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(values, utc=True, errors="coerce")


def to_utc_ms(values) -> pd.Series:
    """Any timestamp-like column → :class:`pandas.Series` of ``datetime64[ms, UTC]``."""
    stamps = _parse(values)
    if not isinstance(stamps.dtype, pd.DatetimeTZDtype):          # naive input
        stamps = stamps.dt.tz_localize("UTC")
    if is_canonical(stamps):
        return stamps
    try:
        return stamps.astype(TIMESTAMP_DTYPE)
    except (OverflowError, pd.errors.OutOfBoundsDatetime):
        # Absurd values (a year-3000 stamp in nanoseconds, a stray huge int…):
        # round-trip through text so one bad row becomes NaT instead of
        # taking the whole run down.
        return _parse(stamps.astype(str)).astype(TIMESTAMP_DTYPE)


def normalize_timestamps(frame, column: str = TIMESTAMP_COLUMN, inplace: bool = False):
    """
    Return ``frame`` with its timestamp column in the canonical dtype.

    Missing frames / columns pass through untouched so this can be used
    defensively anywhere. ``inplace=True`` mutates (and returns) the frame.
    """
    if frame is None or column not in getattr(frame, "columns", []):
        return frame
    if is_canonical(frame[column]):
        return frame
    target = frame if inplace else frame.copy()
    target[column] = to_utc_ms(target[column])
    return target
