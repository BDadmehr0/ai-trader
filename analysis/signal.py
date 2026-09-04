"""
Multi-timeframe signal pipeline.

`analyze_timeframe` turns one indicator frame into a rich snapshot (trend,
strength, structure, momentum, volume, volatility, extra indicators).
`generate_signal` combines the three snapshots through the scoring engine and
returns the *proposal* — the quality gates in analysis/gates.py then decide
whether the proposal is actually tradable.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from analysis.market_structure import analyze_market_structure
from analysis.momentum_analysis import analyze_momentum
from analysis.scoring import AnalysisScores, calculate_scores
from analysis.volatility_analysis import analyze_volatility
from analysis.volume_analysis import analyze_volume
from config.store import get_settings

logger = logging.getLogger(__name__)


def _num(frame, column, default: float = 0.0) -> float:
    try:
        value = float(frame[column])
    except (KeyError, TypeError, ValueError):
        return default
    return value if value == value else default  # NaN guard


def analyze_timeframe(df, timeframe, settings=None) -> Optional[Dict[str, Any]]:
    """Analyze a single indicator frame; None when there is not enough data."""
    if df is None or len(df) < 30:
        return None

    settings = settings or get_settings()
    frame = df.dropna().reset_index(drop=True)
    if len(frame) < 30:
        return None

    latest = frame.iloc[-1]
    price = _num(latest, "close")

    # ---- trend score ------------------------------------------------
    score = 0
    score += 1 if price > _num(latest, "ema_fast") else -1
    score += 1 if _num(latest, "ema_fast") > _num(latest, "ema_mid") else -1
    score += 1 if _num(latest, "ema_mid") > _num(latest, "ema_slow") else -1
    score += 1 if _num(latest, "macd") > _num(latest, "macd_signal") else -1
    score += 1 if _num(latest, "rsi") > 50 else -1

    supertrend_dir = _num(latest, "supertrend_dir", 0.0)
    if supertrend_dir:
        score += 1 if supertrend_dir > 0 else -1

    adx = _num(latest, "adx", 0.0)
    if adx and adx < float(settings.adx_trend_min):
        score = int(round(score * 0.6))       # chop filters trend conviction

    trend = "NEUTRAL"
    if score >= 3:
        trend = "BULLISH"
    elif score <= -3:
        trend = "BEARISH"

    # ---- strength ---------------------------------------------------
    change_pct = 0.0
    look = min(len(frame) - 1, max(5, int(settings.atr_period)))
    if len(frame) > look:
        base = _num(frame.iloc[-1 - look], "close") or price
        change_pct = (price / base - 1.0) * 100.0
    if abs(change_pct) > 5:
        strength = "STRONG"
    elif abs(change_pct) > 2:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    # ---- sub-analyses ------------------------------------------------
    structure = analyze_market_structure(frame, lookback=60)
    volume_analysis = analyze_volume(frame)
    volatility = analyze_volatility(frame)
    momentum = analyze_momentum(frame)

    return {
        "timeframe": timeframe,
        "trend": trend,
        "trend_strength": strength,
        "score": score,
        "change_pct": round(change_pct, 2),
        "price": price,
        "rsi": _num(latest, "rsi", 50.0),
        "rsi_stoch_k": _num(latest, "rsi_stoch_k", 50.0),
        "ema_fast": _num(latest, "ema_fast"),
        "ema_mid": _num(latest, "ema_mid"),
        "ema_slow": _num(latest, "ema_slow"),
        "ema20": _num(latest, "ema_fast"),
        "ema50": _num(latest, "ema_mid"),
        "ema200": _num(latest, "ema_slow"),
        "ema_fast_slope": _num(latest, "ema_fast_slope"),
        "macd": _num(latest, "macd"),
        "macd_signal": _num(latest, "macd_signal"),
        "macd_histogram": _num(latest, "macd_histogram"),
        "macd_hist_pct": _num(latest, "macd_hist_pct"),
        "volume_ratio": _num(latest, "volume_ratio", 1.0),
        "vol_zscore": _num(latest, "vol_zscore"),
        "obv_slope": _num(latest, "obv_slope"),
        "mfi": _num(latest, "mfi", 50.0),
        "cci": _num(latest, "cci"),
        "atr": _num(latest, "atr"),
        "atr_pct": _num(latest, "atr_pct"),
        "atr_ratio": _num(latest, "atr_ratio", 1.0),
        "adx": adx,
        "plus_di": _num(latest, "plus_di"),
        "minus_di": _num(latest, "minus_di"),
        "bb_pct_b": _num(latest, "bb_pct_b", 0.5),
        "bb_bandwidth": _num(latest, "bb_bandwidth"),
        "bb_squeeze": bool(latest.get("bb_squeeze", False)) if hasattr(latest, "get") else False,
        "vwap": _num(latest, "vwap"),
        "vwap_dist_pct": _num(latest, "vwap_dist_pct"),
        "supertrend": _num(latest, "supertrend"),
        "supertrend_dir": supertrend_dir,
        "overextension_pct": ((price / _num(latest, "ema_fast") - 1.0) * 100.0
                               if _num(latest, "ema_fast") else 0.0),
        "volatility_regime": getattr(volatility, "regime", "NORMAL"),
        "structure_trend": getattr(structure, "trend", "NEUTRAL"),
        "market_structure": structure,
        "volume_analysis": volume_analysis,
        "momentum": momentum,
        "volatility": volatility,
        "candles": int(len(frame)),
    }


def analyze_frames(frames: Dict[str, Any], settings=None) -> Dict[str, Dict[str, Any]]:
    """{label: indicator frame} → {label: analysis}."""
    settings = settings or get_settings()
    return {label: analysis for label, analysis in
            ((label, analyze_timeframe(df, label, settings)) for label, df in frames.items())
            if analysis is not None}


def alignment_counts(analyses: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    bull = sum(1 for a in analyses.values() if a.get("trend") == "BULLISH")
    bear = sum(1 for a in analyses.values() if a.get("trend") == "BEARISH")
    return {"BULLISH": bull, "BEARISH": bear, "NEUTRAL": len(analyses) - bull - bear,
            "total": len(analyses)}


def primary_label(analyses: Dict[str, Dict[str, Any]], settings=None) -> Optional[str]:
    """The higher timeframe drives the regime."""
    settings = settings or get_settings()
    for label in (settings.tf_high.upper(), settings.tf_mid.upper(), settings.tf_base.upper()):
        if label in analyses:
            return label
    return next(iter(analyses), None)


def generate_signal(analyses: Dict[str, Dict[str, Any]], settings=None, *, levels=None,
                    price: float = 0.0, news=None, derivatives=None, cross_asset=None,
                    threshold_bonus: float = 0.0) -> Tuple[str, int, Any]:
    """Combine the timeframes into a directional proposal."""
    settings = settings or get_settings()

    if not analyses or len(analyses) < 2:
        return "WAIT", 0, None

    high = settings.tf_high.upper()
    fallback = primary_label(analyses, settings)
    lead = analyses.get(high) or analyses.get(fallback or "") or list(analyses.values())[0]

    scores: AnalysisScores = calculate_scores(
        trend=lead.get("trend", "NEUTRAL"),
        trend_strength=lead.get("trend_strength", "WEAK"),
        momentum_analysis=lead.get("momentum"),
        volume_analysis=lead.get("volume_analysis"),
        ms_analysis=lead.get("market_structure"),
        timeframes_analysis=analyses,
        vol_analysis=lead.get("volatility"),
        levels=levels,
        price=price or lead.get("price", 0.0),
        news=news,
        derivatives=derivatives,
        cross_asset=cross_asset,
        trend_extra={
            "adx": lead.get("adx"),
            "adx_trend_min": settings.adx_trend_min,
            "supertrend_dir": lead.get("supertrend_dir"),
        },
        settings=settings,
        threshold_bonus=threshold_bonus,
    )

    return scores.signal, scores.confidence, scores


def list_analyses(analyses: Dict[str, Dict[str, Any]], settings=None) -> List[str]:
    """Stable, most-informed-first ordering of timeframe labels."""
    settings = settings or get_settings()
    order = [settings.tf_high.upper(), settings.tf_mid.upper(), settings.tf_base.upper()]
    return [label for label in order if label in analyses]
