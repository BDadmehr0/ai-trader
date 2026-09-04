"""
Settings — public entry point.

The runtime store (config/store.py) is the real thing; this module keeps the
historical ``from config.settings import RSI_PERIOD`` style working while also
exposing ``get_settings()`` for code that must react to changes made in the web
settings page without a restart.

Legacy note: ``from config.settings import X`` binds the value *at import
time*. Analysis code therefore reads ``get_settings()`` inside functions.
"""

from config.definition import DEFAULTS, GROUPS, ITEMS, OPTIMIZABLE, ui_groups  # noqa: F401
from config.store import (  # noqa: F401
    STORE,
    Settings,
    export_settings,
    get_settings,
    override_settings,
    reload_settings,
    reset_settings,
    resolve_path,
    save_settings,
    schema_payload,
    settings_file,
    validate,
)

# Legacy name (UPPER_CASE) -> settings key
_LEGACY = {
    "SYMBOL": "symbol",
    "QUOTE": "quote",
    "EXCHANGE_ID": "exchange_id",
    "SUPPORTED_COINS": "supported_coins",
    "TIMEFRAMES": "__timeframes__",
    "CANDLE_LIMIT": "candle_limit",
    "CHART_CANDLE_LIMIT": "chart_candle_limit",
    "EMA_FAST": "ema_fast",
    "EMA_MID": "ema_mid",
    "EMA_SLOW": "ema_slow",
    "RSI_PERIOD": "rsi_period",
    "RSI_OVERBOUGHT": "rsi_overbought",
    "RSI_OVERSOLD": "rsi_oversold",
    "MACD_FAST": "macd_fast",
    "MACD_SLOW": "macd_slow",
    "MACD_SIGNAL": "macd_signal",
    "ATR_PERIOD": "atr_period",
    "VOLUME_MA_PERIOD": "volume_ma_period",
    "INITIAL_BALANCE": "initial_balance",
    "RISK_PER_TRADE": "risk_per_trade",
    "MAX_OPEN_POSITIONS": "max_open_positions",
    "COOLDOWN_CANDLES": "cooldown_candles",
    "ATR_STOP_MULTIPLIER": "atr_stop_multiplier",
    "ATR_TP_MULTIPLIER": "atr_tp_multiplier",
    "ENABLE_BREAK_EVEN": "enable_break_even",
    "BREAK_EVEN_R": "break_even_r",
    "BREAK_EVEN_OFFSET": "break_even_offset",
    "ENABLE_TRAILING_STOP": "enable_trailing_stop",
    "TRAILING_ATR_MULTIPLIER": "trailing_atr_multiplier",
    "LEVERAGE": "leverage",
    "TAKER_FEE": "taker_fee",
    "SLIPPAGE": "slippage",
    "FUNDING_RATE": "funding_rate",
    "FUNDING_INTERVAL_HOURS": "funding_interval_hours",
    "MAINTENANCE_MARGIN": "maintenance_margin",
    "PULLBACK_DISTANCE": "pullback_distance",
    "MIN_VOLUME_RATIO": "min_volume_ratio",
    "MAX_HOLDING_CANDLES": "max_holding_candles",
}


def _legacy_value(name: str):
    key = _LEGACY[name]
    settings = get_settings()
    if key == "__timeframes__":
        # Old callers iterate TIMEFRAMES.items() -> {"15M": "15m", ...}
        return {tf.upper(): tf for tf in settings.timeframe_list()}
    return settings.get(key)


def __getattr__(name: str):
    if name in _LEGACY:
        return _legacy_value(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(list(globals()) + list(_LEGACY)))
