"""
Self-calibration of scoring weights.

`weight_mode = adaptive` turns the journal into a teacher: for each component
we measure how well its score predicted the realised outcome (Pearson IC
against signed R) and nudge its weight. A component that repeatedly points the
wrong way is dampened, one that keeps being right is amplified.

Guard rails, because small samples lie:
* nothing happens below `adaptive_min_samples` evaluated signals
* adjustments shrink with sample size (√-style damping)
* multipliers are clamped to [0.65, 1.45] — never a flip, never a monopoly
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

from config.store import get_settings

logger = logging.getLogger(__name__)

_CACHE_TTL = 120.0
_CACHE: Dict[str, Any] = {"expires": 0.0, "value": {}, "meta": {}}
_LOCK = threading.Lock()

MIN_MULTIPLIER = 0.65
MAX_MULTIPLIER = 1.45
GAIN = 1.4


def _clamp(value: float) -> float:
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, value))


def compute(settings=None) -> Dict[str, Any]:
    """{multipliers, meta, components} — the raw calibration result."""
    settings = settings or get_settings()
    from analysis.journal import component_stats, summary

    stats = component_stats(settings)
    totals = summary(settings)
    samples = int(totals.get("evaluated") or 0)
    minimum = max(5, int(settings.adaptive_min_samples))

    meta = {
        "samples": samples,
        "min_samples": minimum,
        "active": samples >= minimum,
        "win_rate": totals.get("win_rate"),
        "avg_r": totals.get("avg_r"),
    }

    if samples < minimum:
        meta["note"] = f"need {minimum - samples} more evaluated signals before adaptive weights kick in"
        return {"multipliers": {}, "meta": meta, "components": stats}

    damping = min(1.0, (samples / (minimum * 3.0)) ** 0.5)
    multipliers: Dict[str, float] = {}
    for name, row in (stats or {}).items():
        ic = float(row.get("ic") or 0.0)
        if abs(ic) < 0.05:
            continue
        multipliers[name] = round(_clamp(1.0 + GAIN * ic * damping), 3)

    return {"multipliers": multipliers, "meta": meta, "components": stats}


def weight_multipliers(settings=None) -> Dict[str, float]:
    """Cached multipliers, consumed by analysis.scoring.resolve_weights()."""
    settings = settings or get_settings()
    if settings.weight_mode != "adaptive":
        return {}

    now = time.time()
    with _LOCK:
        if _CACHE["expires"] > now and _CACHE["value"]:
            return dict(_CACHE["value"])

    try:
        result = compute(settings)
    except Exception as exc:  # noqa: BLE001 - calibration is optional
        logger.debug("calibration unavailable: %s", exc)
        return {}

    with _LOCK:
        _CACHE["value"] = result["multipliers"]
        _CACHE["meta"] = result["meta"]
        _CACHE["expires"] = now + _CACHE_TTL
    return dict(result["multipliers"])


def report(settings=None, force: bool = False) -> Dict[str, Any]:
    """Full report for the UI (settings page + journal panel)."""
    settings = settings or get_settings()
    if force:
        clear_cache()
    result = compute(settings)
    base = {name: float(weight) for name, weight in settings.weights().items()}
    effective = {}
    for name, weight in base.items():
        effective[name] = round(weight * result["multipliers"].get(name, 1.0), 2)
    return {
        "mode": settings.weight_mode,
        "meta": result["meta"],
        "multipliers": result["multipliers"],
        "components": result["components"],
        "base_weights": base,
        "effective_weights": effective,
    }


def clear_cache() -> None:
    with _LOCK:
        _CACHE["expires"] = 0.0
        _CACHE["value"] = {}
        _CACHE["meta"] = {}
