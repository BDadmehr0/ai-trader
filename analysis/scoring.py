"""
Comprehensive scoring system.

Every analysis module produces a number in [-100, +100]. Those numbers are
combined with user-configurable weights, and any component whose data is not
available (news offline, no derivatives feed, ...) gets weight 0 and the
remaining weights are renormalised — so a missing feed never silently votes
"neutral" and never silently kills the signal either.

The result carries a full `breakdown`, which is what the dashboard shows as
"Why this signal?" and what the signal journal stores so the weights can later
be self-calibrated from real outcomes.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from config.store import get_settings

LABELS = {
    "trend": "Trend / EMA structure",
    "momentum": "Momentum (RSI, MACD, divergence)",
    "volume": "Volume & breakout quality",
    "ms": "Market structure (HH/HL, BoS)",
    "tf": "Multi-timeframe alignment",
    "vol": "Volatility regime",
    "sr": "Support / resistance position",
    "news": "News & AI sentiment",
    "derivatives": "Derivatives positioning",
    "micro": "Order-book microstructure",
    "cross": "BTC regime & correlation",
}


@dataclass
class ScoreComponent:
    name: str
    label: str
    score: float
    base_weight: float
    weight: float = 0.0
    contribution: float = 0.0
    available: bool = True
    note: str = ""

    @property
    def direction(self) -> str:
        if self.score > 8:
            return "BULLISH"
        if self.score < -8:
            return "BEARISH"
        return "NEUTRAL"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction
        data["score"] = round(self.score, 1)
        data["contribution"] = round(self.contribution, 1)
        data["weight"] = round(self.weight, 2)
        return data


@dataclass
class AnalysisScores:
    combined: float = 0.0
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    market_structure_score: float = 0.0
    timeframe_alignment_score: float = 0.0
    volatility_score: float = 0.0
    support_resistance_score: float = 0.0
    news_score: float = 0.0
    derivatives_score: float = 0.0
    micro_score: float = 0.0
    cross_score: float = 0.0
    long_score: int = 50
    short_score: int = 50
    neutral_score: int = 0
    confidence: int = 0
    signal: str = "WAIT"
    proposal: str = "WAIT"
    agreement: float = 0.0
    components: List[ScoreComponent] = field(default_factory=list)
    weights_used: Dict[str, float] = field(default_factory=dict)
    missing: List[str] = field(default_factory=list)
    factors: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def breakdown(self) -> List[Dict[str, Any]]:
        return [component.to_dict() for component in self.components]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "combined": round(self.combined, 1),
            "long_score": self.long_score,
            "short_score": self.short_score,
            "neutral_score": self.neutral_score,
            "confidence": self.confidence,
            "signal": self.signal,
            "proposal": self.proposal,
            "agreement": round(self.agreement, 2),
            "trend_score": round(self.trend_score, 1),
            "momentum_score": round(self.momentum_score, 1),
            "volume_score": round(self.volume_score, 1),
            "market_structure_score": round(self.market_structure_score, 1),
            "timeframe_alignment_score": round(self.timeframe_alignment_score, 1),
            "volatility_score": round(self.volatility_score, 1),
            "support_resistance_score": round(self.support_resistance_score, 1),
            "news_score": round(self.news_score, 1),
            "derivatives_score": round(self.derivatives_score, 1),
            "micro_score": round(self.micro_score, 1),
            "cross_score": round(self.cross_score, 1),
            "breakdown": self.breakdown(),
            "weights": {k: round(v, 2) for k, v in self.weights_used.items()},
            "missing": self.missing,
            "notes": self.notes,
        }


# =====================================================================
# component scorers
# =====================================================================

def _score_trend(trend: str, strength: str, extra: Optional[Dict[str, Any]] = None) -> float:
    table = {
        ("BULLISH", "STRONG"): 100, ("BULLISH", "MODERATE"): 70, ("BULLISH", "WEAK"): 40,
        ("BEARISH", "STRONG"): -100, ("BEARISH", "MODERATE"): -70, ("BEARISH", "WEAK"): -40,
    }
    score = table.get((trend, strength), 0)

    extra = extra or {}
    adx = extra.get("adx")
    if adx is not None:
        if adx >= 30:
            score = score * 1.1 if score else (10 if adx >= 35 else 0)
        elif adx < float(extra.get("adx_trend_min", 20)):
            score *= 0.55          # weak / ranging market → trend means little

    if extra.get("supertrend_dir") and trend != "NEUTRAL":
        same = (extra["supertrend_dir"] > 0) == (score > 0)
        score += 12 if same else -18

    return max(-100.0, min(100.0, score))


def _score_momentum(mom) -> float:
    if mom is None:
        return 0.0
    score = 0.0
    rsi_map = {"OVERSOLD": 40, "NEUTRAL_BEARISH": -20, "NEUTRAL": 0,
               "NEUTRAL_BULLISH": 20, "OVERBOUGHT": -40}
    score += rsi_map.get(getattr(mom, "rsi_state", "NEUTRAL"), 0)

    cross = getattr(mom, "macd_cross", "NONE")
    if cross == "BULLISH_CROSS":
        score += 30
    elif cross == "BEARISH_CROSS":
        score -= 30
    state = getattr(mom, "macd_state", "")
    if state == "BULLISH":
        score += 10
    elif state == "BEARISH":
        score -= 10

    divergence = getattr(mom, "divergence", "NONE")
    score += {"BULLISH_DIVERGENCE": 50, "HIDDEN_BULLISH": 25,
              "BEARISH_DIVERGENCE": -50, "HIDDEN_BEARISH": -25}.get(divergence, 0)

    if getattr(mom, "strength", "") == "STRONG":
        score *= 1.1
    return max(-100.0, min(100.0, score))


def _score_volume(vol) -> float:
    if vol is None:
        return 0.0
    score = 0.0
    confirmation = getattr(vol, "trend_confirmation", "NEUTRAL")
    score += 30 if confirmation == "BULLISH" else (-30 if confirmation == "BEARISH" else 0)

    quality = getattr(vol, "breakout_quality", "NONE")
    score += {"STRONG": 40, "MODERATE": 20, "WEAK": -10}.get(quality, 0)
    if getattr(vol, "unusual_volume", False):
        score += 10
    if getattr(vol, "spike_strength", "NONE") == "STRONG":
        score += 8 * (1 if score >= 0 else -1)
    return max(-100.0, min(100.0, score))


def _score_structure(ms) -> float:
    if ms is None:
        return 0.0
    score = (ms.hh_count * 15 + ms.hl_count * 10 - ms.ll_count * 15 - ms.lh_count * 10)
    breakout = getattr(ms, "last_breakout_direction", None)
    if breakout == "BULLISH":
        score += 30
    elif breakout == "BEARISH":
        score -= 30
    if getattr(ms, "strength", "WEAK") == "STRONG":
        score = int(score * 1.2)
    return max(-100.0, min(100.0, score))


def _score_alignment(timeframes_analysis: Dict[str, Any], direction: Optional[str] = None) -> float:
    if not timeframes_analysis:
        return 0.0
    trends = []
    for value in timeframes_analysis.values():
        if isinstance(value, dict):
            trends.append(value.get("trend", "NEUTRAL"))
        elif hasattr(value, "trend"):
            trends.append(value.trend)
    if len(trends) < 2:
        return 0.0

    bullish = sum(1 for t in trends if t == "BULLISH")
    bearish = sum(1 for t in trends if t == "BEARISH")
    neutral = len(trends) - bullish - bearish
    total = len(trends)

    if bullish == total:
        return 100.0
    if bearish == total:
        return -100.0
    score = (bullish - bearish) / total * 65.0
    if neutral:
        score *= 0.85
    if direction == "LONG" and bearish:
        score -= 15
    if direction == "SHORT" and bullish:
        score += 15
    return max(-100.0, min(100.0, score))


def _score_volatility(vol) -> float:
    if vol is None:
        return 0.0
    regime = getattr(vol, "regime", "NORMAL")
    trending = getattr(vol, "is_trending", False)
    if regime == "EXTREME":
        return -80.0
    if regime == "HIGH":
        return 10.0 if trending else -30.0
    if regime == "LOW":
        return -10.0 if not trending else 5.0
    return 15.0 if trending else 5.0


def _score_levels(levels, price: float) -> float:
    """Signed proximity score: room above a resistance, a floor below support."""
    if levels is None or not price:
        return 0.0
    score = 0.0
    resistance = getattr(levels, "resistance_1", 0) or 0
    support = getattr(levels, "support_1", 0) or 0

    if resistance:
        distance = (resistance - price) / price * 100
        if 0 <= distance < 0.5:
            score -= 50
        elif distance < 1.5:
            score -= 25
        elif distance > 3:
            score += 15
    if support:
        distance = (price - support) / price * 100
        if 0 <= distance < 0.5:
            score += 50
        elif distance < 1.5:
            score += 25
        elif distance > 3:
            score -= 15

    strength_bonus = 0.0
    if support and getattr(levels, "support_1_strength", "WEAK") == "STRONG":
        strength_bonus += 10
    if resistance and getattr(levels, "resistance_1_strength", "WEAK") == "STRONG":
        strength_bonus -= 10
    score += strength_bonus * 0.5

    return max(-100.0, min(100.0, score))


def _score_news(news) -> Optional[float]:
    if news is None or not getattr(news, "available", False):
        return None
    reliability = float(getattr(news, "reliability", 0.0) or 0.0)
    if reliability <= 0.05:
        return None
    # Scale by reliability so thin/contradictory coverage counts less.
    return float(news.score) * (0.55 + 0.45 * reliability)


def _score_derivatives(derivatives, which: str = "positioning") -> Optional[float]:
    if derivatives is None or not getattr(derivatives, "available", False):
        return None
    value = getattr(derivatives, f"{which}_score", 0.0) or 0.0
    reliability = getattr(derivatives, f"{which}_reliability", None)
    reliability = float(reliability if reliability else getattr(derivatives, "reliability", 0.0) or 0.0)
    if reliability <= 0.05:
        return None
    return float(value) * max(0.35, reliability)


# =====================================================================
# weights
# =====================================================================

def resolve_weights(settings, availability: Dict[str, bool], *,
                    multipliers: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Effective weights: user weights × calibration × availability, normalised to 100."""
    weights = settings.weights()
    multipliers = multipliers or {}

    effective = {}
    for name, base in weights.items():
        if not availability.get(name, True):
            effective[name] = 0.0
            continue
        effective[name] = max(0.0, float(base) * float(multipliers.get(name, 1.0)))

    total = sum(effective.values())
    if total <= 0:
        # Everything disabled → fall back to pure trend so we never divide by 0.
        return {"trend": 100.0}
    return {name: weight / total * 100.0 for name, weight in effective.items()}


# =====================================================================
# main
# =====================================================================

def calculate_scores(*, trend="NEUTRAL", trend_strength="WEAK", momentum_analysis=None,
                     volume_analysis=None, ms_analysis=None, timeframes_analysis=None,
                     vol_analysis=None, levels=None, price=0.0, news=None, derivatives=None,
                     cross_asset=None, trend_extra=None, settings=None,
                     threshold_bonus: float = 0.0) -> AnalysisScores:
    settings = settings or get_settings()
    timeframes_analysis = timeframes_analysis or {}

    raw: Dict[str, Optional[float]] = {
        "trend": _score_trend(trend, trend_strength, trend_extra),
        "momentum": _score_momentum(momentum_analysis),
        "volume": _score_volume(volume_analysis),
        "ms": _score_structure(ms_analysis),
        "tf": _score_alignment(timeframes_analysis),
        "vol": _score_volatility(vol_analysis),
        "sr": _score_levels(levels, price),
        "news": _score_news(news),
        "derivatives": _score_derivatives(derivatives, "positioning"),
        "micro": _score_derivatives(derivatives, "micro"),
        "cross": (float(cross_asset.score) if cross_asset is not None and cross_asset.available else None),
    }

    availability = {name: value is not None for name, value in raw.items()}
    missing = [name for name, ok in availability.items() if not ok]

    multipliers: Dict[str, float] = {}
    if settings.weight_mode == "adaptive":
        try:
            from analysis.calibration import weight_multipliers

            multipliers = weight_multipliers(settings)
        except Exception:  # noqa: BLE001 - calibration is optional sugar
            multipliers = {}

    weights = resolve_weights(settings, availability, multipliers=multipliers)

    components: List[ScoreComponent] = []
    combined = 0.0
    for name, value in raw.items():
        weight = weights.get(name, 0.0)
        score = 0.0 if value is None else float(value)
        contribution = score * weight / 100.0
        combined += contribution
        note = ""
        if value is None:
            note = "data unavailable — weight dropped"
        elif multipliers.get(name) not in (None, 1.0):
            note = f"adaptive weight ×{multipliers[name]:.2f}"
        components.append(ScoreComponent(
            name=name, label=LABELS.get(name, name), score=score,
            base_weight=float(settings.weights().get(name, 0.0)), weight=weight,
            contribution=contribution, available=value is not None, note=note,
        ))

    combined = max(-100.0, min(100.0, combined))

    # ---- directional scores ----------------------------------------
    if combined >= 0:
        long_score = int(50 + combined * 0.5)
        short_score = int(50 - combined * 0.3)
    else:
        long_score = int(50 + combined * 0.3)
        short_score = int(50 - combined * 0.5)
    long_score = max(0, min(100, long_score))
    short_score = max(0, min(100, short_score))
    neutral_score = max(0, min(100, 100 - long_score - short_score))

    # ---- agreement across the components that voted ------------------
    votes = [c for c in components if c.available and c.weight > 0 and abs(c.score) > 5]
    agreement = 0.0
    if votes and abs(combined) > 1:
        sign = 1.0 if combined > 0 else -1.0
        weighted = sum((c.score * sign) * c.weight for c in votes)
        possible = sum(abs(c.score) * c.weight for c in votes) or 1.0
        agreement = max(0.0, min(1.0, weighted / possible))

    # ---- confidence --------------------------------------------------
    magnitude = abs(combined)
    if magnitude < settings.neutral_threshold:
        confidence = min(max(long_score, short_score, neutral_score), 30)
    elif magnitude < settings.entry_threshold:
        confidence = int(magnitude * 1.2 + 10)
    else:
        confidence = int(magnitude * 0.55 + agreement * 30 + 15)

    if settings.confidence_penalty_missing_data:
        confidence -= min(12, 3 * len(missing))

    if "news" in missing and settings.weight_news > 0:
        confidence -= 3
    confidence = max(0, min(100, confidence))

    # ---- proposal ----------------------------------------------------
    threshold = max(1.0, float(settings.entry_threshold) + float(threshold_bonus))
    if combined >= threshold:
        proposal = "LONG"
    elif combined <= -threshold:
        proposal = "SHORT"
    elif magnitude < settings.neutral_threshold:
        proposal = "NO_TRADE"
    else:
        proposal = "WAIT"

    if proposal == "LONG" and not settings.allow_longs:
        proposal = "WAIT"
    if proposal == "SHORT" and not settings.allow_shorts:
        proposal = "WAIT"

    notes: List[str] = []
    if multipliers:
        notes.append("adaptive weights active (from the signal journal)")
    if missing:
        notes.append("no data for: " + ", ".join(missing))

    scores = AnalysisScores(
        combined=combined,
        trend_score=raw["trend"] or 0.0,
        momentum_score=raw["momentum"] or 0.0,
        volume_score=raw["volume"] or 0.0,
        market_structure_score=raw["ms"] or 0.0,
        timeframe_alignment_score=raw["tf"] or 0.0,
        volatility_score=raw["vol"] or 0.0,
        support_resistance_score=raw["sr"] or 0.0,
        news_score=raw["news"] or 0.0,
        derivatives_score=raw["derivatives"] or 0.0,
        micro_score=raw["micro"] or 0.0,
        cross_score=raw["cross"] or 0.0,
        long_score=long_score,
        short_score=short_score,
        neutral_score=neutral_score,
        confidence=confidence,
        signal=proposal,
        proposal=proposal,
        agreement=agreement,
        components=sorted(components, key=lambda c: -abs(c.contribution)),
        weights_used=weights,
        missing=missing,
        factors={c.name: c.direction for c in components if c.available and abs(c.score) > 5},
        notes=notes,
    )
    return scores


def entry_threshold_with_penalty(settings, bonus: float = 0.0) -> float:
    return max(1.0, float(settings.entry_threshold) + float(bonus or 0.0))
