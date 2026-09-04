"""
Parameter optimizer (walk-forward).

Searches strategy/risk parameters against *your* data — the exchange feed or a
CSV you uploaded — and ranks the combinations by an objective on the training
slice while reporting the untouched out-of-sample slice. That split is the
point: a parameter set that only works on the full history is overfitted, and
the UI shows both numbers so you can see it happening.

* `optimizer_mode = grid`   → deterministic cartesian product (capped by trials)
* `optimizer_mode = random` → seeded random search over the ranges (default)

Ranges come from `optimizer_ranges` in the settings; empty falls back to the
params flagged `optimizer=True` in config/definition.py.
"""

import itertools
import json
import logging
import re
import math
import random
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backtesting.service import build_frames, run_backtest
from config.definition import ITEMS
from config.store import validate, get_settings, override_settings, save_settings

logger = logging.getLogger(__name__)

#: fallback search space when the user did not define ranges
DEFAULT_SPACE: Dict[str, List[Any]] = {
    "entry_threshold": [20, 25, 30, 35, 40],
    "min_confidence": [30, 40, 50],
    "pullback_distance": [0.008, 0.015, 0.025, 0.035],
    "min_volume_ratio": [1.0, 1.1, 1.3],
    "atr_stop_multiplier": [1.0, 1.5, 2.0, 2.5],
    "atr_tp_multiplier": [2.0, 3.0, 4.0],
    "max_holding_candles": [48, 96, 144],
    "cooldown_candles": [2, 8, 16],
    "adx_trend_min": [15, 20, 25],
    "max_overextension_pct": [2.0, 3.5, 6.0],
}

FINER_SPACE: Dict[str, List[Any]] = {
    "rsi_period": [9, 14, 21],
    "atr_period": [10, 14, 20],
    "supertrend_multiplier": [2.0, 3.0, 4.0],
}


# =====================================================================
# objectives
# =====================================================================

def composite_score(metrics: Dict[str, Any], min_trades: int = 5) -> float:
    """Balanced objective: return, risk-adjusted return, quality, and a
    heavy penalty for barely trading or blowing up."""
    if not metrics:
        return -1e9

    trades = int(metrics.get("total_trades") or 0)
    if trades <= 0:
        return -1e9

    total_return = float(metrics.get("total_return") or 0.0)
    sharpe = float(metrics.get("sharpe") or 0.0)
    profit_factor = metrics.get("profit_factor")
    drawdown = float(metrics.get("max_drawdown") or 0.0)
    win_rate = float(metrics.get("win_rate") or 0.0)

    if profit_factor in (None, ""):
        pf = 1.0
    else:
        pf = float(profit_factor)
        pf = 6.0 if math.isinf(pf) else min(pf, 6.0)

    score = (
        total_return * 0.5
        + max(-3.0, min(sharpe, 6.0)) * 12.0
        + (pf - 1.0) * 18.0
        + (win_rate - 50.0) * 0.35
        - drawdown * 0.9
    )

    if trades < min_trades:
        score -= (min_trades - trades) * 25.0     # nothing worth concluding
    return round(score, 3)


def objective_value(metrics: Dict[str, Any], objective: str) -> float:
    if not metrics:
        return -1e9
    if objective == "score":
        return composite_score(metrics)
    value = metrics.get(objective)
    if value is None:
        return -1e9
    try:
        value = float(value)
    except (TypeError, ValueError):
        return -1e9
    return 6.0 if math.isinf(value) else value


# =====================================================================
# search space
# =====================================================================

def parse_ranges(raw: Any) -> Dict[str, List[Any]]:
    """Normalise the optimizer ranges into ``{setting: [values…]}``.

    Accepts a dict or JSON text. Per key either an explicit list of values, a
    single value, or a ``{"min": 20, "max": 60, "step": 10}`` window — the form
    that is easiest to hand-edit. Unknown keys are ignored (with a log line) so
    a stale range file cannot break a run.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            logger.warning("optimizer ranges are not valid JSON — ignored")
            return {}
    if not isinstance(raw, dict):
        return {}

    out: Dict[str, List[Any]] = {}
    for key, values in raw.items():
        if key not in ITEMS:
            logger.warning("optimizer ranges: unknown setting %r ignored", key)
            continue
        if isinstance(values, dict):
            values = _expand_window(values)
            if values is None:
                logger.warning("optimizer ranges: %s needs min and max", key)
                continue
        if isinstance(values, str) and any(sep in values for sep in (",", ";", "\n")):
            values = [part for part in re.split(r"[,;\n]", values)]
        elif isinstance(values, (int, float, str, bool)):
            values = [values]
        values = list(values or [])
        if not values:
            continue
        item = ITEMS[key]
        clean = []
        for value in values:
            try:
                clean.append(float(value))
            except (TypeError, ValueError):
                clean.append(value)
        out[key] = clean
    return out


def _expand_window(spec: Dict[str, Any]) -> Optional[List[float]]:
    try:
        low = float(spec["min"])
        high = float(spec["max"])
    except (KeyError, TypeError, ValueError):
        return None
    if high < low:
        low, high = high, low
    step = spec.get("step")
    try:
        step = float(step) if step not in (None, "") else None
    except (TypeError, ValueError):
        step = None
    if not step or step <= 0:
        count = int(spec.get("count") or 4)
        count = max(2, min(12, count))
        step = (high - low) / (count - 1) if high > low else 1.0
    values: List[float] = []
    current = low
    while current <= high + 1e-9 and len(values) < 24:
        values.append(round(current, 6))
        current += step
    return values or [low]


def active_space(settings) -> Dict[str, List[Any]]:
    user = parse_ranges(settings.optimizer_ranges)
    if user:
        return user
    if int(settings.optimizer_trials) > 30:
        space = dict(DEFAULT_SPACE)
        space.update(FINER_SPACE)
        return space
    return dict(DEFAULT_SPACE)


def _coerce(key: str, value: Any) -> Any:
    item = ITEMS[key]
    if item.type == "int":
        return int(round(float(value)))
    if item.type == "float":
        return float(value)
    if item.type == "bool":
        return bool(value)
    return value


def _rounded(key: str, value: Any) -> Any:
    number = _coerce(key, value)
    if isinstance(number, float):
        return round(number, 6)
    return number


def build_trials(settings, space: Dict[str, List[Any]], limit: int) -> List[Dict[str, Any]]:
    keys = [key for key in space if key in ITEMS]
    values = [space[key] for key in keys]

    if settings.optimizer_mode == "grid" and keys:
        combos = list(itertools.product(*values))
        if len(combos) > limit:
            step = math.ceil(len(combos) / limit)
            combos = combos[::step][:limit]
        return [{key: _rounded(key, value) for key, value in zip(keys, combo)} for combo in combos]

    rng = random.Random(int(settings.optimizer_seed))
    trials: List[Dict[str, Any]] = []
    seen = set()
    guard = 0
    while len(trials) < limit and keys and guard < limit * 40:
        guard += 1
        combo = {key: _rounded(key, rng.choice(space[key])) for key in keys}
        signature = json.dumps(combo, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        trials.append(combo)
    return trials


# =====================================================================
# run
# =====================================================================

def run(symbol: Optional[str] = None, settings=None, market=None, *, trials: Optional[List[Dict]] = None,
        limit: Optional[int] = None) -> Dict[str, Any]:
    settings = settings or get_settings()
    symbol = symbol or settings.symbol
    space = active_space(settings)
    limit = int(limit or settings.optimizer_trials)

    from data.market_data import MarketData

    market = market or MarketData(settings=settings)

    try:
        frames = build_frames(market, settings, symbol)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"data: {exc}", "trials": [], "space": space}

    ordered = list(frames.values())
    if len(ordered) < 3:
        return {"ok": False, "error": "need three timeframes for a backtest", "trials": [], "space": space}

    from backtesting.mtf import prepare_mtf_data

    base = prepare_mtf_data(ordered[0], ordered[1], ordered[2])
    rows = len(base)
    if rows < 120:
        return {"ok": False, "error": f"only {rows} merged candles — need 120+", "trials": [], "space": space}

    ratio = float(settings.optimizer_train_ratio)
    objective = settings.optimizer_objective

    combos = trials or build_trials(settings, space, limit)
    results: List[Dict[str, Any]] = []

    for combo in combos:
        try:
            with override_settings(**combo):
                trial_settings = get_settings()
                trial_frames = build_frames(market, trial_settings, symbol)
                ordered_trial = list(trial_frames.values())
                merged = prepare_mtf_data(ordered_trial[0], ordered_trial[1], ordered_trial[2])
                cut = max(40, int(len(merged) * ratio))
                train = _metrics_for(merged.iloc[:cut].reset_index(drop=True), trial_settings)
                test = _metrics_for(merged.iloc[cut:].reset_index(drop=True), trial_settings)
        except Exception as exc:  # noqa: BLE001 - one bad combo must not kill the search
            logger.debug("trial %s failed: %s", combo, exc)
            continue

        results.append({
            "params": combo,
            "train_objective": round(objective_value(train, objective), 3),
            "test_objective": round(objective_value(test, objective), 3),
            "train": _compact(train),
            "test": _compact(test),
        })

    ranked = sorted(results, key=lambda item: item["train_objective"], reverse=True)
    best = ranked[0] if ranked else None

    overfit_gap = None
    if best and best["test_objective"] > -1e8 and best["train_objective"] > -1e8:
        overfit_gap = round(best["train_objective"] - best["test_objective"], 2)

    return {
        "ok": bool(ranked),
        "symbol": symbol,
        "source": getattr(market, "source", "?"),
        "live": bool(getattr(market, "is_live", False)),
        "objective": objective,
        "mode": settings.optimizer_mode,
        "space": {k: v for k, v in space.items()},
        "rows": rows,
        "train_rows": int(max(40, int(rows * ratio))),
        "test_rows": int(max(0, rows - max(40, int(rows * ratio)))),
        "trials": ranked,
        "best": best,
        "overfit_gap": overfit_gap,
        "error": None if ranked else "no trial produced metrics",
    }


def _metrics_for(frame, settings) -> Dict[str, Any]:
    if frame is None or len(frame) < 30:
        return {}
    from backtesting.engine import BacktestEngine
    from backtesting.metrics import calculate_metrics

    engine = BacktestEngine(float(settings.initial_balance), settings=settings)
    trades = engine.run(frame)
    metrics = calculate_metrics(trades, engine.equity_curve, float(settings.initial_balance))
    if metrics:
        metrics["total_trades"] = int(metrics.get("total_trades") or 0)
    return metrics


def _compact(metrics: Dict[str, Any]) -> Dict[str, Any]:
    if not metrics:
        return {"total_trades": 0}
    keys = ("total_trades", "win_rate", "profit_factor", "total_return", "max_drawdown", "sharpe",
            "final_balance", "expectancy")
    out = {}
    for key in keys:
        value = metrics.get(key)
        if value is None:
            continue
        if isinstance(value, float):
            value = round(float(value), 3) if not math.isinf(value) else "inf"
        out[key] = value
    return out


def apply_best(params: Dict[str, Any], settings=None) -> Tuple[bool, Dict[str, str]]:
    """Persist the winning parameters into data/settings.json.

    Every key is validated (type *and* range) before anything is written, and
    the caller gets the full error map — a partially applied parameter set would
    silently change what the next backtest measures.
    """
    settings = settings or get_settings()
    clean, errors = validate(params or {}, strict=True)
    if not clean:
        return False, errors or {"params": "nothing to apply"}
    if errors:
        return False, errors

    _, save_errors = save_settings(clean)
    return (not save_errors), save_errors
