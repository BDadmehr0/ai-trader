"""
Backtest strategy rules.

The same *ideas* the live pipeline uses (HTF regime → MTF pullback → LTF
trigger), expressed as vectorised-ready row checks so 1000+ candles can be
simulated in milliseconds. Every threshold comes from the settings store, so
what you tune in the UI is exactly what gets backtested — and what the
optimizer can search.
"""

from config.store import get_settings


def _f(row, key, default=0.0):
    try:
        value = float(row[key])
    except (KeyError, IndexError, TypeError, ValueError):
        return default
    return default if value != value else value


def _b(row, key, default=False):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    try:
        return bool(value) and value == value
    except Exception:  # noqa: BLE001
        return default


def get_high_tf_regime(row, settings=None) -> str:
    """BULLISH / BEARISH / NEUTRAL from the higher timeframe."""
    settings = settings or get_settings()

    close = _f(row, "close_high")
    ema_fast = _f(row, "ema_fast_high")
    ema_mid = _f(row, "ema_mid_high")
    ema_slow = _f(row, "ema_slow_high")
    macd = _f(row, "macd_high")
    macd_signal = _f(row, "macd_signal_high")
    supertrend_dir = _f(row, "supertrend_dir_high")
    adx = _f(row, "adx_high", 25.0)

    score = 0
    score += 1 if close > ema_slow else -1
    score += 1 if ema_fast > ema_mid else -1
    score += 1 if ema_mid > ema_slow else -1
    score += 1 if macd > macd_signal else -1
    if supertrend_dir:
        score += 1 if supertrend_dir > 0 else -1

    if adx < float(settings.adx_trend_min):
        return "NEUTRAL"

    if score >= 4:
        return "BULLISH"
    if score <= -4:
        return "BEARISH"
    return "NEUTRAL"


def _pullback(row, direction: int, settings) -> bool:
    """Price parked near the mid-timeframe EMA with RSI in the entry zone."""
    close = _f(row, "close_mid")
    ema_fast = _f(row, "ema_fast_mid")
    ema_mid = _f(row, "ema_mid_mid")
    ema_slow = _f(row, "ema_slow_mid")
    rsi = _f(row, "rsi_mid", 50.0)

    if direction > 0:
        trend = ema_fast > ema_mid and ema_mid > ema_slow
        lo, hi = float(settings.rsi_long_min), float(settings.rsi_long_max)
    else:
        trend = ema_fast < ema_mid and ema_mid < ema_slow
        lo, hi = float(settings.rsi_short_min), float(settings.rsi_short_max)

    if not trend:
        return False
    if close <= 0:
        return False

    distance = abs(close - ema_fast) / close
    if distance > float(settings.pullback_distance) * 4.0:      # never pulled back
        return False
    return lo <= rsi <= hi


def _trigger(previous, current, direction: int, settings) -> bool:
    """Base-timeframe entry trigger."""
    prev_macd = _f(previous, "macd")
    prev_signal = _f(previous, "macd_signal")
    macd = _f(current, "macd")
    signal = _f(current, "macd_signal")
    hist = _f(current, "macd_histogram")
    prev_hist = _f(previous, "macd_histogram")
    rsi = _f(current, "rsi", 50.0)
    volume_ratio = _f(current, "volume_ratio", 1.0)

    if settings.require_macd_cross:
        if direction > 0:
            crossed = (prev_macd <= prev_signal and macd > signal) or (prev_hist <= 0 < hist)
        else:
            crossed = (prev_macd >= prev_signal and macd < signal) or (prev_hist >= 0 > hist)
        if not crossed:
            return False

    if direction > 0 and rsi <= 50:
        return False
    if direction < 0 and rsi >= 50:
        return False

    if settings.require_volume_confirm and volume_ratio < float(settings.min_volume_ratio):
        return False

    supertrend_dir = _f(current, "supertrend_dir")
    if supertrend_dir and (1 if supertrend_dir > 0 else -1) != direction:
        return False

    # Volatility shock filter.
    atr_ratio = _f(current, "atr_ratio", 1.0)
    if atr_ratio > float(settings.max_atr_ratio):
        return False

    # Chasing filter.
    ema_fast = _f(current, "ema_fast")
    close = _f(current, "close")
    if ema_fast and close:
        extension = (close / ema_fast - 1.0) * 100.0 * direction
        if extension > float(settings.max_overextension_pct):
            return False

    return True


def generate_signal(previous, current, settings=None) -> str:
    """LONG / SHORT / WAIT for one base-timeframe candle."""
    settings = settings or get_settings()

    regime = get_high_tf_regime(current, settings)

    if regime == "BULLISH" and settings.allow_longs:
        if _pullback(current, 1, settings) and _trigger(previous, current, 1, settings):
            return "LONG"
    if regime == "BEARISH" and settings.allow_shorts:
        if _pullback(current, -1, settings) and _trigger(previous, current, -1, settings):
            return "SHORT"
    return "WAIT"


# ---------------------------------------------------------------------
# Backwards-compatible aliases used by older notebooks/scripts
# ---------------------------------------------------------------------

def get_4h_regime(row, settings=None) -> str:
    return get_high_tf_regime(row, settings)


def is_long_pullback(row, settings=None) -> bool:
    return _pullback(row, 1, settings or get_settings())


def is_short_pullback(row, settings=None) -> bool:
    return _pullback(row, -1, settings or get_settings())


def long_entry_trigger(previous, current, settings=None) -> bool:
    return _trigger(previous, current, 1, settings or get_settings())


def short_entry_trigger(previous, current, settings=None) -> bool:
    return _trigger(previous, current, -1, settings or get_settings())
