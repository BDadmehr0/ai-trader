"""
News + AI sentiment engine.

Pipeline
--------
    fetch headlines (RSS / CryptoPanic)  +  Fear & Greed index
        → dedupe, rank by recency, keep at most `news_max_headlines`
        → tag relevance to the traded symbol (aliases + user keywords)
        → score each headline with the configured engine
              ollama | openai-compatible | lexicon (offline)
        → recency-decayed, relevance-weighted mean → sentiment in [-1, 1]
        → bias / confidence / impact + "extreme news" guard (veto mode)

Everything is cached (`news_cache_ttl`) and every failure degrades to a
neutral, *flagged* result: a missing feed or a sleeping laptop must never
fabricate a bullish/bearish bias, and the analysis weight for news is simply
dropped by the scoring layer when `available` is False.
"""

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from analysis.news.lexicon import score_text
from analysis.news.sources import (
    NewsItem,
    apply_relevance,
    base_asset,
    dedupe,
    fetch_cryptopanic,
    fetch_fear_greed,
    fetch_rss,
    sort_by_recency,
    symbol_keywords,
)
from config.store import get_settings
from utils.cache import cache_for

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "news"

__all__ = ["NewsAnalysis", "analyze_news", "config_fingerprint"]


# =====================================================================
# result object
# =====================================================================

@dataclass
class NewsAnalysis:
    enabled: bool = True
    available: bool = False
    status: str = "DISABLED"          # OK | LOW_SAMPLE | NO_DATA | OFFLINE | DISABLED | ERROR
    provider: str = "lexicon"
    model: str = ""
    symbol: str = ""

    sentiment: float = 0.0            # [-1, 1]
    bias: str = "NEUTRAL"             # BULLISH | BEARISH | NEUTRAL
    score: float = 0.0               # [-100, 100] contribution for scoring
    reliability: float = 0.0         # 0..1 — how much scoring should trust it
    confidence: int = 0
    impact: str = "NONE"             # NONE | WEAK | MODERATE | STRONG

    item_count: int = 0
    symbol_count: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    agreement: float = 0.0

    fear_greed: Optional[Dict[str, Any]] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    top_bullish: List[Dict[str, Any]] = field(default_factory=list)
    top_bearish: List[Dict[str, Any]] = field(default_factory=list)

    veto: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    age_seconds: Optional[float] = None
    cache_state: str = "miss"
    fetched_at: Optional[str] = None

    @property
    def opposes_long(self) -> bool:
        return bool(self.veto.get("opposes") == "LONG")

    @property
    def opposes_short(self) -> bool:
        return bool(self.veto.get("opposes") == "SHORT")

    def headline_summary(self) -> str:
        if not self.available:
            return self.error or "no sentiment data"
        pct = f"{self.sentiment * 100:+.0f}"
        fg = f" · F&G {self.fear_greed['value']:.0f}" if self.fear_greed else ""
        return f"{self.bias} {pct} from {self.item_count} headlines ({self.provider}){fg}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "symbol": self.symbol,
            "sentiment": round(self.sentiment, 3),
            "bias": self.bias,
            "score": round(self.score, 1),
            "reliability": round(self.reliability, 2),
            "confidence": self.confidence,
            "impact": self.impact,
            "item_count": self.item_count,
            "symbol_count": self.symbol_count,
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "agreement": round(self.agreement, 2),
            "fear_greed": self.fear_greed,
            "items": self.items,
            "top_bullish": self.top_bullish,
            "top_bearish": self.top_bearish,
            "veto": self.veto,
            "notes": self.notes,
            "stats": self.stats,
            "error": self.error,
            "age_seconds": self.age_seconds,
            "cache_state": self.cache_state,
            "fetched_at": self.fetched_at,
            "summary": self.headline_summary(),
        }


def _bias_of(sentiment: float) -> str:
    if sentiment >= 0.12:
        return "BULLISH"
    if sentiment <= -0.12:
        return "BEARISH"
    return "NEUTRAL"


def _impact_of(sentiment: float, reliability: float) -> str:
    magnitude = abs(sentiment) * (0.5 + 0.5 * reliability)
    if magnitude >= 0.5:
        return "STRONG"
    if magnitude >= 0.28:
        return "MODERATE"
    if magnitude >= 0.1:
        return "WEAK"
    return "NONE"


# =====================================================================
# settings helpers
# =====================================================================

def config_fingerprint(settings, symbol: str) -> str:
    """Cache key: any change of news config (or symbol) forces a refetch."""
    payload = {
        "symbol": symbol.upper(),
        "provider": settings.news_provider,
        "model": settings.ollama_model if settings.news_provider == "ollama" else settings.openai_model,
        "url": settings.ollama_url if settings.news_provider == "ollama" else settings.openai_base_url,
        "feeds": [f.strip() for f in settings.rss_feeds],
        "panic": bool(settings.cryptopanic_enabled),
        "fng": bool(settings.fear_greed_enabled),
        "max": settings.news_max_headlines,
        "min": settings.news_min_items,
        "half_life": settings.recency_half_life_hours,
        "relevant_only": bool(settings.symbol_relevance_only),
        "extra_kw": settings.news_extra_keywords,
        "fg_weight": settings.fear_greed_weight,
        # these change the *answer*, not just the fetch, so they must bust the cache
        "veto": settings.news_veto_mode,
        "veto_at": settings.news_veto_threshold,
        "temperature": settings.llm_temperature,
        "batch": settings.llm_batch_size,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def llm_config(settings, symbol: str):
    from analysis.news.llm import LlmConfig

    if settings.news_provider == "ollama":
        return LlmConfig(
            provider="ollama",
            model=settings.ollama_model,
            base_url=settings.ollama_url,
            timeout=float(settings.llm_timeout),
            temperature=float(settings.llm_temperature),
            max_tokens=int(settings.llm_max_tokens),
            batch_size=int(settings.llm_batch_size),
            proxy=settings.proxy_url or None,
            symbol=symbol,
        )
    if settings.news_provider == "openai":
        return LlmConfig(
            provider="openai",
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key or "",
            timeout=float(settings.llm_timeout),
            temperature=float(settings.llm_temperature),
            max_tokens=int(settings.llm_max_tokens),
            batch_size=int(settings.llm_batch_size),
            proxy=settings.proxy_url or None,
            symbol=symbol,
        )
    return None


# =====================================================================
# core
# =====================================================================

def analyze_news(symbol: str, settings=None, *, force: bool = False) -> NewsAnalysis:
    settings = settings or get_settings()

    if not settings.news_enabled or settings.news_provider == "off":
        return NewsAnalysis(enabled=False, status="DISABLED", symbol=base_asset(symbol),
                            provider="off", notes=["news analysis disabled in settings"])

    cache = cache_for(CACHE_NAMESPACE)
    key = f"{base_asset(symbol)}:{config_fingerprint(settings, symbol)}"

    if not force:
        cached, age = cache.read(key)
        ttl = float(settings.news_cache_ttl)
        if isinstance(cached, dict) and (age is None or age <= ttl):
            result = _from_payload(cached)
            result.cache_state = "cache"
            result.age_seconds = age
            return result

    try:
        payload = _gather(symbol, settings)
    except Exception as exc:  # noqa: BLE001 - news must never break the signal
        logger.warning("news analysis failed: %s", exc)
        stale, age = cache.read(key)
        if isinstance(stale, dict):
            result = _from_payload(stale)
            result.cache_state = "stale"
            result.age_seconds = age
            result.notes.append(f"refresh failed, showing last good snapshot ({exc})")
            return result
        return NewsAnalysis(status="ERROR", error=str(exc)[:200], symbol=base_asset(symbol),
                            provider=settings.news_provider,
                            model=_model_name(settings), notes=["news unavailable"])

    cache.write(key, payload)
    result = _from_payload(payload)
    result.cache_state = "fetched"
    result.age_seconds = 0.0
    return result


def _model_name(settings) -> str:
    if settings.news_provider == "ollama":
        return settings.ollama_model
    if settings.news_provider == "openai":
        return settings.openai_model
    return "lexicon-v1"


def _gather(symbol: str, settings) -> Dict[str, Any]:
    """Fetch + score + aggregate. Returns a JSON-serialisable payload."""
    notes: List[str] = []
    timeout = float(settings.news_http_timeout)
    proxy = settings.proxy_url or None

    items: List[NewsItem] = []

    feeds = [str(f).strip() for f in (settings.rss_feeds or []) if str(f).strip()]
    if feeds:
        rss_items, rss_notes = fetch_rss(feeds, timeout=timeout, proxy=proxy)
        items.extend(rss_items)
        notes.extend(rss_notes)

    if settings.cryptopanic_enabled:
        panic_items, panic_notes = fetch_cryptopanic(
            settings.cryptopanic_token, [base_asset(symbol)], timeout=timeout, proxy=proxy)
        items.extend(panic_items)
        notes.extend(panic_notes)

    fear_greed = None
    if settings.fear_greed_enabled:
        fear_greed, fg_note = fetch_fear_greed(limit=4, timeout=timeout, proxy=proxy)
        if fg_note:
            notes.append(fg_note)

    keywords = symbol_keywords(symbol, settings.news_extra_keywords)
    items = apply_relevance(dedupe(sort_by_recency(items)), keywords)

    if settings.symbol_relevance_only and keywords:
        keep = [it for it in items if it.relevance == "SYMBOL"]
        # Keep macro context if we would otherwise have nothing to say.
        items = keep or [it for it in items if it.matched]

    limit = int(settings.news_max_headlines)
    items = items[:limit]

    if not items and not fear_greed:
        return _payload(symbol, settings, [], fear_greed, notes,
                        status="OFFLINE" if notes else "NO_DATA",
                        error=None if items else "no headlines matched the filters")

    # ---- scoring ----------------------------------------------------
    texts = [it.text for it in items]
    stats: Dict[str, Any] = {"engine": settings.news_provider, "items": len(items)}

    if settings.news_provider in ("ollama", "openai"):
        try:
            from analysis.news.llm import score_headlines

            cfg = llm_config(settings, symbol)
            scored, stats = score_headlines(texts, cfg)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{settings.news_provider} unavailable ({str(exc)[:120]}) → offline lexicon")
            scored, stats = _lexicon_scores(texts), {"engine": "lexicon", "items": len(items),
                                                      "requested": 0, "cached": 0, "fallbacks": len(items)}
    else:
        scored, stats = _lexicon_scores(texts), stats | {"engine": "lexicon"}

    for item, (score, reason, method) in zip(items, scored):
        item.score = float(score)
        item.method = method
        item.detail = [reason] if reason else []

    # ---- aggregation ------------------------------------------------
    half_life = max(0.5, float(settings.recency_half_life_hours))
    weights: List[float] = []
    values: List[float] = []

    freshness_samples: List[float] = []
    for item in items:
        age = item.age_hours()
        recency = 1.0 if age is None else 0.5 ** (age / half_life)
        freshness_samples.append(recency)
        relevance = 1.0 if item.relevance == "SYMBOL" else 0.55
        weight = max(0.02, recency * relevance)
        weights.append(weight)
        values.append(item.score)

    if fear_greed:
        fg_weight = (float(settings.fear_greed_weight) / 100.0) * 3.0
        mean_w = (sum(weights) / len(weights)) if weights else 1.0
        weights.append(max(0.02, fg_weight * mean_w))
        values.append(float(fear_greed["sentiment"]))

    total_weight = sum(weights) or 1.0
    sentiment = sum(w * v for w, v in zip(weights, values)) / total_weight

    variance = sum(w * (v - sentiment) ** 2 for w, v in zip(weights, values)) / total_weight
    agreement = max(0.0, 1.0 - math.sqrt(max(0.0, variance)) / 0.75)

    scored_items = [it for it in items if abs(it.score) > 0.05]
    bullish = [it for it in items if it.score > 0.15]
    bearish = [it for it in items if it.score < -0.15]
    symbol_hits = [it for it in items if it.relevance == "SYMBOL"]

    min_items = max(1, int(settings.news_min_items))
    sample = min(1.0, len(scored_items) / min_items) if scored_items else 0.0
    # reliability penalty when the preferred engine could not answer
    wanted = "llm" if settings.news_provider in ("ollama", "openai") else "lexicon"
    scoring = stats.get("scoring") or ("llm" if wanted == "llm" and stats.get("engine") else "lexicon")
    if scoring == wanted:
        coverage = 1.0
    elif scoring == "mixed":
        coverage = 0.93
    else:
        coverage = 0.85
    # A three-day-old headline must not carry the same trust as breaking news.
    # Weighting alone cannot express that: with one item the weighted mean is
    # independent of its weight, so freshness scales the reliability directly.
    freshness = round(sum(freshness_samples) / len(freshness_samples), 3) if freshness_samples else 1.0
    reliability = round(max(0.0, min(1.0, (0.55 * sample + 0.45 * agreement) * coverage
                                    * (0.45 + 0.55 * freshness))), 3)
    stats["freshness"] = freshness

    confidence = int(round(100 * reliability * (0.4 + 0.6 * min(1.0, len(items) / (min_items * 2)))))
    impact = _impact_of(sentiment, reliability)
    bias = _bias_of(sentiment)

    status = "OK"
    if not items:
        status = "PARTIAL"          # only Fear & Greed
    elif sample < 1.0:
        status = "LOW_SAMPLE"

    veto = _veto(sentiment, bias, float(settings.news_veto_threshold), settings.news_veto_mode, impact)

    ordered = sorted(items, key=lambda it: it.score)
    return {
        "symbol": base_asset(symbol),
        "status": status,
        "available": True,
        "provider": str(stats.get("engine") or settings.news_provider),
        "model": _model_name(settings),
        "sentiment": round(sentiment, 3),
        "bias": bias,
        "score": round(sentiment * 100.0, 1),
        "reliability": reliability,
        "confidence": max(0, min(100, confidence)),
        "impact": impact,
        "item_count": len(items),
        "symbol_count": len(symbol_hits),
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "agreement": round(agreement, 3),
        "fear_greed": _clean_fg(fear_greed),
        "items": [it.to_dict() for it in sort_by_recency(items)][:25],
        "top_bullish": [it.to_dict() for it in sorted(bullish, key=lambda x: -x.score)[:4]],
        "top_bearish": [it.to_dict() for it in sorted(bearish, key=lambda x: x.score)[:4]],
        "veto": veto,
        "notes": notes[:8],
        "stats": stats,
        "error": None if items else (None if fear_greed else "no headlines available"),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _clean_fg(fear_greed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not fear_greed:
        return None
    updated = fear_greed.get("updated")
    return {
        "value": fear_greed.get("value"),
        "label": fear_greed.get("label"),
        "sentiment": fear_greed.get("sentiment"),
        "trend": fear_greed.get("trend"),
        "history": [
            {"value": row["value"], "label": row["label"]}
            for row in (fear_greed.get("history") or [])[:5]
        ],
        "updated": updated.isoformat(timespec="minutes") if isinstance(updated, datetime) else None,
    }


def _lexicon_scores(texts: Sequence[str]) -> List[Tuple[float, str, str]]:
    out = []
    for text in texts:
        score, hits, _label = score_text(text)
        out.append((score, ", ".join(hits[:2]), "lexicon"))
    return out


def _veto(sentiment: float, bias: str, threshold: float, mode: str, impact: str) -> Dict[str, Any]:
    """Should extreme news stop us from taking the trade in the opposite direction?"""
    result = {"mode": mode, "threshold": threshold, "triggered": False, "opposes": None,
              "note": "news guard off" if mode == "off" else "sentiment inside normal range"}
    if mode == "off" or bias == "NEUTRAL":
        return result

    if abs(sentiment) < threshold:
        return result

    result["triggered"] = True
    result["opposes"] = "SHORT" if bias == "BULLISH" else "LONG"
    result["note"] = (
        f"extreme {bias.lower()} news ({sentiment:+.2f}, {impact.lower()}) — "
        + ("signal against the news flow is blocked" if mode == "block"
           else "entry threshold raised for trades against the news flow")
    )
    result["blocking"] = mode == "block"
    result["threshold_bonus"] = 0 if mode == "block" else 12.0
    return result


def _payload(symbol: str, settings, items, fear_greed, notes, status: str,
             error: Optional[str]) -> Dict[str, Any]:
    """Empty / degraded payload."""
    return {
        "symbol": base_asset(symbol),
        "status": status,
        "available": False,
        "provider": settings.news_provider,
        "model": _model_name(settings),
        "sentiment": 0.0,
        "bias": "NEUTRAL",
        "score": 0.0,
        "reliability": 0.0,
        "confidence": 0,
        "impact": "NONE",
        "item_count": 0,
        "symbol_count": 0,
        "bullish_count": 0,
        "bearish_count": 0,
        "agreement": 0.0,
        "fear_greed": _clean_fg(fear_greed),
        "items": [it.to_dict() for it in items],
        "top_bullish": [],
        "top_bearish": [],
        "veto": {"mode": settings.news_veto_mode, "triggered": False, "opposes": None},
        "notes": notes[:8],
        "stats": {"engine": settings.news_provider, "items": len(items)},
        "error": error,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _from_payload(payload: Dict[str, Any]) -> NewsAnalysis:
    data = {k: v for k, v in payload.items() if k in NewsAnalysis.__dataclass_fields__}
    data.setdefault("enabled", True)
    fear_greed = data.get("fear_greed")
    if isinstance(fear_greed, dict) and isinstance(fear_greed.get("updated"), datetime):
        data["fear_greed"] = {**fear_greed, "updated": data["fear_greed"]["updated"].isoformat()}
    return NewsAnalysis(**data)
