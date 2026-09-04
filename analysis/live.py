"""
Live analysis engine.

One call → one complete, explainable report:

    candles → indicators → per-timeframe analysis → S/R levels
            → news + AI sentiment            (optional, cached)
            → derivatives + order book        (optional, cached)
            → BTC regime / correlation        (altcoins)
            → weighted scoring                → proposal
            → trade construction (stop/target/size)
            → quality gates                   → final BUY / SELL / HOLD
            → journal entry                   → later self-calibration

Every stage reports *why* it voted the way it did, and any stage that cannot
run (no internet, no local model, no futures access) marks itself unavailable
instead of voting neutral — the scoring weights renormalise around it.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from analysis.cross_asset import analyze_cross_asset
from analysis.derivatives import analyze_derivatives
from analysis.gates import evaluate_gates
from analysis.indicators import add_indicators
from analysis.levels import find_market_levels
from analysis.news import analyze_news
from analysis.risk import create_trade_setup
from analysis.signal import alignment_counts, analyze_frames, generate_signal
from config.store import get_settings
from config.settings import SYMBOL  # noqa: F401  (default symbol, legacy import path)

logger = logging.getLogger(__name__)

VERDICT = {"LONG": "BUY", "SHORT": "SELL", "WAIT": "HOLD", "NO_TRADE": "HOLD"}
TREND_FA = {"BULLISH": "صعودي", "BEARISH": "نزولي", "NEUTRAL": "خنثي"}
TREND_EN = {"BULLISH": "Bullish", "BEARISH": "Bearish", "NEUTRAL": "Neutral"}


# =====================================================================
# reasoning
# =====================================================================

def _generate_explanation(proposal, confidence, scores, analyses, levels, news, derivatives,
                          cross_asset, gates):
    """Plain-language bull / bear factor lists."""
    bullish, bearish = [], []

    for label, data in analyses.items():
        trend = data.get("trend", "NEUTRAL")
        if trend == "BULLISH":
            bullish.append(f"{label} trend is bullish (score {data.get('score', 0):+d}, ADX {data.get('adx', 0):.0f})")
        elif trend == "BEARISH":
            bearish.append(f"{label} trend is bearish (score {data.get('score', 0):+d}, ADX {data.get('adx', 0):.0f})")

        rsi = data.get("rsi", 50)
        if rsi >= 70:
            bearish.append(f"{label} RSI overbought ({rsi:.0f})")
        elif rsi <= 30:
            bullish.append(f"{label} RSI oversold ({rsi:.0f})")

        st = data.get("supertrend_dir") or 0
        if st > 0:
            bullish.append(f"{label} SuperTrend up")
        elif st < 0:
            bearish.append(f"{label} SuperTrend down")

        vwap_gap = data.get("vwap_dist_pct") or 0
        if abs(vwap_gap) >= 0.8:
            (bullish if vwap_gap > 0 else bearish).append(
                f"{label} price {vwap_gap:+.1f}% vs session VWAP")

        volume = data.get("volume_ratio", 1)
        if volume and volume > 1.5:
            (bullish if trend == "BULLISH" else bearish).append(
                f"{label} volume {volume:.1f}x average")

    for label in list(analyses)[:2]:
        structure = analyses[label].get("market_structure")
        if structure is None:
            continue
        for count, text, side in (
            (structure.hh_count, "higher highs", bullish),
            (structure.hl_count, "higher lows", bullish),
            (structure.ll_count, "lower lows", bearish),
            (structure.lh_count, "lower highs", bearish),
        ):
            if count:
                side.append(f"{label}: {count} {text}")
        if structure.last_breakout_direction:
            side = bullish if structure.last_breakout_direction == "BULLISH" else bearish
            side.append(f"{label}: break of structure to the {structure.last_breakout_direction.lower()}")

    lead = next(iter(analyses.values()), {})
    momentum = lead.get("momentum")
    if momentum is not None:
        if getattr(momentum, "divergence", "NONE") == "BULLISH_DIVERGENCE":
            bullish.append("bullish RSI divergence")
        elif getattr(momentum, "divergence", "NONE") == "BEARISH_DIVERGENCE":
            bearish.append("bearish RSI divergence")
        if getattr(momentum, "macd_cross", "NONE") == "BULLISH_CROSS":
            bullish.append("MACD bullish cross")
        elif getattr(momentum, "macd_cross", "NONE") == "BEARISH_CROSS":
            bearish.append("MACD bearish cross")

    if levels:
        price = lead.get("price", 0)
        if price:
            for name, value, distance_text, side in (
                ("resistance", levels.resistance_1, "above", bearish),
                ("support", levels.support_1, "below", bullish),
            ):
                if not value:
                    continue
                gap = abs(value - price) / price * 100.0
                if gap < 1.0:
                    side.append(f"major {name} only {gap:.1f}% {distance_text} ({value:,.6g}, {levels.support_1_strength if name == 'support' else levels.resistance_1_strength})")
                elif gap < 3.0:
                    side.append(f"{name} approaching ({value:,.6g}, {gap:.1f}% {distance_text})")

    if news is not None and news.available:
        if news.bias != "NEUTRAL":
            line = f"news flow {news.bias.lower()} ({news.sentiment:+.2f}, {news.item_count} items, {news.provider})"
            (bullish if news.bias == "BULLISH" else bearish).append(line)
        if news.fear_greed:
            (bullish if news.fear_greed["value"] >= 60 else bearish).append(
                f"Fear & Greed {news.fear_greed['value']:.0f} ({news.fear_greed['label']}, {news.fear_greed['trend'].lower()})")

    if derivatives is not None and derivatives.available:
        for factor in derivatives.factors[:4]:
            (bullish if _positive_note(factor) else bearish).append(f"positioning: {factor}")

    if cross_asset is not None and cross_asset.available:
        for factor in cross_asset.factors[:3]:
            (bullish if "bullish" in factor or "outperform" in factor else bearish).append(factor)

    if gates is not None:
        for warning in gates.warnings[:3]:
            bearish.append(f"caution: {warning}")

    return bullish, bearish


def _positive_note(factor: str) -> bool:
    lowered = factor.lower()
    positive = ("squeeze fuel", "bias up", "aggressive buying", "backed by new longs",
                "bid-heavy", "retail one-sided short", "neutral")
    return any(word in lowered for word in positive)


def _build_explanation(verdict, setup):
    if verdict == "BUY":
        return f"Buy (LONG) signal. Entry at {setup.entry:,.0f}, Stop Loss {setup.stop_loss:,.0f}, Target {setup.take_profit_1:,.0f}."
    if verdict == "SELL":
        return f"Sell (SHORT) signal. Entry at {setup.entry:,.0f}, Stop Loss {setup.stop_loss:,.0f}, Target {setup.take_profit_1:,.0f}."
    return "Market conditions are unclear. Waiting for clearer signal."


# =====================================================================
# report
# =====================================================================

def build_signal_report(market, symbol=None, *, settings=None, include_news=None,
                        include_derivatives=None, record_journal=None) -> Dict[str, Any]:
    settings = settings or get_settings()
    symbol = symbol or settings.symbol

    include_news = settings.news_enabled if include_news is None else bool(include_news)
    include_derivatives = (settings.derivatives_enabled or settings.micro_enabled) \
        if include_derivatives is None else bool(include_derivatives)
    record_journal = bool(settings.journal_enabled) if record_journal is None else bool(record_journal)

    labels = settings.timeframe_labels
    frames: Dict[str, Any] = {}
    fetch_errors = []

    for label, timeframe in zip(labels, settings.timeframe_list()):
        try:
            frames[label] = add_indicators(market.get_ohlcv(symbol, timeframe, settings.candle_limit), settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("candles failed for %s %s: %s", symbol, timeframe, exc)
            fetch_errors.append(f"{label}: {exc}")

    analyses = analyze_frames(frames, settings)
    if not analyses:
        return _empty_report(symbol, settings, market, "no usable candles", fetch_errors)

    base_label = labels[0] if labels[0] in analyses else next(iter(analyses))
    price = float(analyses[base_label].get("price") or 0.0)

    # ---- levels (from the mid timeframe) ----------------------------
    mid_label = labels[1] if labels[1] in frames else base_label
    levels = None
    if frames.get(mid_label) is not None:
        try:
            levels = find_market_levels(frames[mid_label], lookback=200)
        except Exception as exc:  # noqa: BLE001
            logger.debug("levels failed: %s", exc)

    # ---- sentiment / positioning / cross-asset ----------------------
    news = None
    if include_news:
        try:
            news = analyze_news(symbol, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("news analysis failed: %s", exc)
            news = None

    derivatives = None
    price_change = analyses[base_label].get("change_pct")
    if include_derivatives:
        try:
            derivatives = analyze_derivatives(symbol, settings, price_change_pct=price_change, market=market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("derivatives failed: %s", exc)
            derivatives = None

    cross_asset = None
    if settings.cross_asset_enabled and symbol.split("/")[0].upper() != "BTC":
        try:
            btc_frame = add_indicators(
                market.get_ohlcv(f"BTC/{settings.quote}", settings.cross_asset_timeframe, settings.candle_limit),
                settings,
            )
            cross_asset = analyze_cross_asset(symbol, frames.get(mid_label), btc_frame, settings)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cross-asset unavailable: %s", exc)

    # ---- scoring -----------------------------------------------------
    threshold_bonus = 0.0
    if news is not None and (news.veto or {}).get("threshold_bonus"):
        threshold_bonus = float(news.veto["threshold_bonus"])

    proposal, raw_confidence, scores = generate_signal(
        analyses, settings, levels=levels, price=price, news=news, derivatives=derivatives,
        cross_asset=cross_asset, threshold_bonus=threshold_bonus,
    )

    # ---- trade construction -----------------------------------------
    lead = analyses.get(labels[-1]) or analyses[base_label]
    atr_value = float(lead.get("atr") or price * 0.01)
    support = levels.support_1 if levels else price * 0.99
    resistance = levels.resistance_1 if levels else price * 1.01

    setup = create_trade_setup(
        proposal, price, atr_value, support, resistance, raw_confidence,
        settings=settings,
        swing_low=getattr(levels, "last_swing_low", None),
        swing_high=getattr(levels, "last_swing_high", None),
        levels=levels,
        volatility_regime=lead.get("volatility_regime"),
    )

    # ---- gates -------------------------------------------------------
    gates = evaluate_gates(
        settings=settings,
        proposal=proposal,
        confidence=raw_confidence,
        primary=lead,
        mid=analyses.get(mid_label),
        levels=levels,
        setup=setup,
        news=news,
        derivatives=derivatives,
        cross_asset=cross_asset,
        alignment=alignment_counts(analyses),
    )

    if proposal in ("LONG", "SHORT"):
        signal = gates.signal
    elif scores is None:
        # not enough usable candles to score anything (a short CSV, a timeframe
        # the data cannot fill): say so instead of inventing a verdict
        signal = "WAIT"
    else:
        signal = "NO_TRADE" if abs(scores.combined) < float(settings.neutral_threshold) else "WAIT"

    confidence = max(0, min(100, int(gates.confidence)))

    if scores is not None:
        scores.signal = signal
        scores.confidence = confidence

    verdict = VERDICT.get(signal, "HOLD")
    bullish, bearish = _generate_explanation(signal, confidence, scores, analyses, levels, news,
                                             derivatives, cross_asset, gates)

    ticker = None
    try:
        ticker = market.get_ticker(symbol)
    except Exception:  # noqa: BLE001
        ticker = None
    change_24h = float((ticker or {}).get("change_pct") or 0.0)

    report = {
        "symbol": symbol,
        "signal": signal,
        "proposal": proposal,
        "verdict": verdict,
        "confidence": int(confidence),
        "price": price,
        "change_24h_pct": change_24h,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "explanation": _build_explanation(verdict, setup),
        "reasons": [f"Bullish: {f}" for f in bullish[:8]] + [f"Bearish: {f}" for f in bearish[:8]],
        "factors": {"bullish": bullish[:8], "bearish": bearish[:8]},
        "timeframes": {label: _serialize_analysis(analyses[label]) for label in labels if label in analyses},
        "levels": (levels.to_dict() if levels else {}),
        "setup": setup.to_dict(),
        "scores": scores.to_dict() if scores else {},
        "gates": gates.to_dict(),
        "news": news.to_dict() if news else {"enabled": False, "available": False, "status": "DISABLED"},
        "derivatives": derivatives.to_dict() if derivatives else {"available": False, "status": "DISABLED"},
        "cross_asset": cross_asset.to_dict() if cross_asset else {"available": False, "status": "SKIPPED"},
        "data": {
            "source": getattr(market, "source", "exchange"),
            "live": bool(getattr(market, "is_live", False)),
            "error": getattr(market, "last_error", None),
            "fetch_errors": fetch_errors,
            "timeframes": settings.timeframe_list(),
            "candles": {label: int(len(frames[label])) for label in frames if frames[label] is not None},
        },
        "settings": {
            "entry_threshold": settings.entry_threshold,
            "min_confidence": settings.min_confidence,
            "stop_mode": settings.stop_mode,
            "target_mode": settings.target_mode,
            "weight_mode": settings.weight_mode,
            "news_provider": settings.news_provider,
            "risk_per_trade": settings.risk_per_trade,
            "timeframes": settings.timeframe_list(),
        },
        "chart": _chart_series(frames.get(base_label)),
    }

    if record_journal:
        try:
            from analysis.journal import record_signal

            record_signal(report, settings)
        except Exception as exc:  # noqa: BLE001
            logger.debug("journal skipped: %s", exc)

    return report


def _chart_series(frame) -> Dict[str, Any]:
    """Overlay series for the chart, computed on the same candles it draws."""
    from analysis.indicators import overlay_series

    return overlay_series(frame) if frame is not None and not frame.empty else {}


def _serialize_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not analysis:
        return {}
    keep = (
        "timeframe", "trend", "score", "price", "rsi", "rsi_stoch_k", "ema_fast", "ema_mid",
        "ema_slow", "ema20", "ema50", "ema200", "ema_fast_slope", "macd", "macd_signal",
        "macd_histogram", "macd_hist_pct", "volume_ratio", "vol_zscore", "obv_slope", "mfi",
        "cci", "atr", "atr_pct", "atr_ratio", "adx", "plus_di", "minus_di", "bb_pct_b",
        "bb_bandwidth", "vwap", "vwap_dist_pct", "supertrend_dir", "overextension_pct",
        "volatility_regime", "structure_trend", "change_pct", "candles",
    )
    out = {key: analysis.get(key) for key in keep}
    out["trend_fa"] = TREND_FA.get(analysis.get("trend", ""), analysis.get("trend", ""))
    out["trend_en"] = TREND_EN.get(analysis.get("trend", ""), analysis.get("trend", ""))
    out["trend_strength"] = analysis.get("trend_strength", "WEAK")
    out["bb_squeeze"] = bool(analysis.get("bb_squeeze", False))
    structure = analysis.get("market_structure")
    out["market_structure"] = {
        "trend": getattr(structure, "trend", "NEUTRAL"),
        "strength": getattr(structure, "strength", "WEAK"),
        "hh_count": getattr(structure, "hh_count", 0),
        "hl_count": getattr(structure, "hl_count", 0),
        "lh_count": getattr(structure, "lh_count", 0),
        "ll_count": getattr(structure, "ll_count", 0),
        "last_breakout_direction": getattr(structure, "last_breakout_direction", None),
    } if structure is not None else {}
    momentum = analysis.get("momentum")
    out["momentum"] = {
        "rsi_state": getattr(momentum, "rsi_state", "NEUTRAL"),
        "macd_state": getattr(momentum, "macd_state", "NEUTRAL"),
        "macd_cross": getattr(momentum, "macd_cross", "NONE"),
        "divergence": getattr(momentum, "divergence", "NONE"),
        "strength": getattr(momentum, "strength", "WEAK"),
    } if momentum is not None else {}
    volume = analysis.get("volume_analysis")
    out["volume_analysis"] = {
        "spike_strength": getattr(volume, "spike_strength", "NONE"),
        "trend_confirmation": getattr(volume, "trend_confirmation", "NEUTRAL"),
        "breakout_quality": getattr(volume, "breakout_quality", "NONE"),
        "relative_volume": getattr(volume, "relative_volume", 1.0),
    } if volume is not None else {}
    volatility = analysis.get("volatility")
    out["volatility"] = {
        "regime": getattr(volatility, "regime", "NORMAL"),
        "is_trending": getattr(volatility, "is_trending", False),
        "contraction_expansion": getattr(volatility, "contraction_expansion", "NEUTRAL"),
        "normalized_atr": getattr(volatility, "normalized_atr", 1.0),
    } if volatility is not None else {}
    return out


def _empty_report(symbol, settings, market, reason, fetch_errors=None) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "signal": "WAIT",
        "proposal": "WAIT",
        "verdict": "HOLD",
        "confidence": 0,
        "price": 0.0,
        "change_24h_pct": 0.0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "explanation": f"Analysis unavailable: {reason}",
        "reasons": [f"Error: {item}" for item in (fetch_errors or [reason])][:10],
        "factors": {"bullish": [], "bearish": []},
        "timeframes": {},
        "levels": {},
        "setup": create_trade_setup("WAIT", 0, 0, 0, 0, 0, settings=settings).to_dict(),
        "scores": {},
        "gates": {"gates": [], "blocked": False, "passed": 0, "total": 0},
        "news": {"enabled": False, "available": False, "status": "SKIPPED"},
        "derivatives": {"available": False, "status": "SKIPPED"},
        "cross_asset": {"available": False, "status": "SKIPPED"},
        "data": {
            "source": getattr(market, "source", "unknown"),
            "live": bool(getattr(market, "is_live", False)),
            "error": getattr(market, "last_error", None),
            "fetch_errors": fetch_errors or [reason],
        },
        "settings": {},
        "chart": {},
    }


def analyze_symbol(symbol: Optional[str] = None, *, include_news: Optional[bool] = None,
                   settings=None) -> Dict[str, Any]:
    """Convenience entry point for scripts / API: builds a MarketData itself."""
    from data.market_data import MarketData

    settings = settings or get_settings()
    return build_signal_report(MarketData(settings=settings), symbol or settings.symbol,
                               settings=settings, include_news=include_news)
