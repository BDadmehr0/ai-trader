"""
Signal journal.

Every emitted signal is appended to `data/logs/signals.jsonl` together with the
score of each component, the weights that were used and the trade levels. After
`journal_eval_after_candles` candles the outcome is simulated from real candles
(TP or SL first) and written back.

That gives two things no backtest can:

1. a live hit-rate per symbol / verdict / confidence bucket, and
2. the data for `analysis.calibration` to re-weight the components by how well
   each of them *actually* predicted the outcome.
"""

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from config.store import REPO_ROOT, get_settings, resolve_path
from data.csv_source import timeframe_minutes

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
MAX_RECORDS = 5000

#: params snapshot keys that matter when comparing historical signals
PARAM_KEYS = (
    "entry_threshold", "min_confidence", "require_trend_alignment", "pullback_distance",
    "min_volume_ratio", "max_overextension_pct", "atr_stop_multiplier", "atr_tp_multiplier",
    "tp1_r", "tp2_r", "stop_mode", "target_mode", "news_enabled", "news_provider",
    "derivatives_enabled", "weight_mode",
)


def journal_path(settings=None) -> Path:
    settings = settings or get_settings()
    return resolve_path(settings.journal_path or "data/logs/signals.jsonl")


def enabled(settings=None) -> bool:
    settings = settings or get_settings()
    return bool(settings.journal_enabled)


# =====================================================================
# writing
# =====================================================================

def params_fingerprint(settings=None) -> str:
    settings = settings or get_settings()
    blob = json.dumps({key: settings.get(key) for key in PARAM_KEYS}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:10]


def build_record(report: Dict[str, Any], settings=None) -> Dict[str, Any]:
    settings = settings or get_settings()
    scores = report.get("scores") or {}
    components = {c["name"]: c.get("score", 0) for c in (scores.get("breakdown") or [])}
    setup = report.get("setup") or {}
    news = report.get("news") or {}

    return {
        "id": hashlib.sha1(
            f"{report.get('symbol')}|{report.get('updated_at')}|{components.get('trend', 0)}".encode()
        ).hexdigest()[:12],
        "ts": report.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        "symbol": report.get("symbol"),
        "signal": report.get("signal"),
        "verdict": report.get("verdict"),
        "proposal": scores.get("proposal"),
        "confidence": report.get("confidence"),
        "price": report.get("price"),
        "entry": setup.get("entry"),
        "stop_loss": setup.get("stop_loss"),
        "take_profit_1": setup.get("take_profit_1"),
        "risk_reward_1": setup.get("risk_reward_1"),
        "components": components,
        "weights": scores.get("weights") or {},
        "news_sentiment": news.get("sentiment"),
        "news_bias": news.get("bias"),
        "gates_failed": [g.get("label") for g in (report.get("gates") or {}).get("gates", [])
                         if g.get("status") == "FAIL"],
        "params": {key: settings.get(key) for key in PARAM_KEYS},
        "fingerprint": params_fingerprint(settings),
        "outcome": None,          # +1 TP1 first, -1 SL first, 0 timeout
        "outcome_r": None,
        "evaluated_at": None,
        "data_source": (report.get("data") or {}).get("used"),
    }


def record_signal(report: Dict[str, Any], settings=None) -> Optional[Dict[str, Any]]:
    """Append one signal record. Never raises — logging must not break analysis."""
    settings = settings or get_settings()
    if not enabled(settings) or not report:
        return None
    try:
        record = build_record(report, settings)
        path = journal_path(settings)
        if _is_repeat(read_records(settings), record, settings):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            _trim(path)
        return record
    except Exception as exc:  # noqa: BLE001
        logger.debug("journal write failed: %s", exc)
        return None


def _is_repeat(records: List[Dict[str, Any]], record: Dict[str, Any], settings) -> bool:
    """Skip a signal that repeats the last one for the same symbol.

    The dashboard refreshes every minute; without this, an unchanged setup would
    be logged dozens of times and dominate the accuracy stats.  A record is only
    skipped while the previous one could not have been judged yet — after that
    window the (possibly changed) situation is worth recording again.
    """
    window = max(1, int(settings.journal_eval_after_candles))
    try:
        minutes = window * timeframe_minutes(settings.tf_base)
    except Exception:  # noqa: BLE001 - unknown timeframe label: fall back to 1h bars
        minutes = window * 60
    limit = max(60.0, float(minutes))

    symbol = record.get("symbol")
    for previous in reversed(records):
        if previous.get("symbol") != symbol:
            continue
        same = (previous.get("signal") == record.get("signal")
                and previous.get("fingerprint") == record.get("fingerprint")
                and abs(float(previous.get("price") or 0.0) - float(record.get("price") or 0.0))
                <= max(1e-9, float(record.get("price") or 0.0) * 0.0005))
        if not same:
            return False
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(str(previous.get("ts")).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            return False
        return age.total_seconds() / 60.0 < limit
    return False


def _trim(path: Path, limit: int = MAX_RECORDS) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > limit:
        try:
            path.write_text("\n".join(lines[-limit:]) + "\n", encoding="utf-8")
        except OSError:
            pass


def read_records(settings=None) -> List[Dict[str, Any]]:
    path = journal_path(settings)
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    out.append(record)
    except OSError as exc:  # pragma: no cover
        logger.debug("journal read failed: %s", exc)
    return out


def _write_records(records: List[Dict[str, Any]], settings=None) -> None:
    path = journal_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records[-MAX_RECORDS:]:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


# =====================================================================
# evaluation
# =====================================================================

def evaluate_open_signals(market=None, settings=None, *, force: bool = False) -> Dict[str, Any]:
    """Simulate the outcome of signals that have had enough candles since."""
    settings = settings or get_settings()
    records = read_records(settings)
    if not records:
        return {"evaluated": 0, "pending": 0, "total": 0, "errors": []}

    from data.market_data import MarketData

    market = market or MarketData(settings=settings)
    eval_after = max(1, int(settings.journal_eval_after_candles))
    conservative = str(settings.journal_touch_tolerance) == "conservative"

    changed = 0
    pending = 0
    errors: List[str] = []
    cache: Dict[str, Any] = {}

    for record in records:
        if record.get("outcome") is not None and not force:
            continue
        if record.get("signal") not in ("LONG", "SHORT"):
            record["outcome"] = 0
            record["outcome_r"] = 0.0
            record["evaluated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            changed += 1
            continue

        symbol = record.get("symbol") or settings.symbol
        try:
            ts = datetime.fromisoformat(str(record["ts"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            pending += 1
            continue

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if symbol not in cache:
            try:
                # the fetch is "the last N candles", so one call serves every
                # record of that symbol regardless of its timestamp
                cache[symbol] = market.get_ohlcv(symbol, settings.tf_base,
                                                 min(1000, eval_after * 6 + 60))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{symbol}: {exc}")
                cache[symbol] = None

        frame = cache[symbol]
        if frame is None or frame.empty:
            pending += 1
            continue

        future = frame[frame["timestamp"] >= ts]
        if future.empty:
            # the signal is newer than the last candle we have (or the source
            # does not cover that date at all) — nothing to judge it by yet
            pending += 1
            continue
        if len(future) < eval_after and not force:
            pending += 1
            continue

        outcome, realized_r = _simulate(record, future.head(eval_after + 1), conservative)
        record["outcome"] = outcome
        record["outcome_r"] = round(realized_r, 4)
        record["evaluated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        changed += 1

    if changed:
        try:
            _write_records(records, settings)
        except OSError as exc:  # pragma: no cover
            errors.append(f"write: {exc}")

    return {"evaluated": changed, "pending": pending, "total": len(records), "errors": errors[:3]}


def _simulate(record: Dict[str, Any], frame, conservative: bool) -> tuple:
    """+1 if TP1 hit first, -1 if SL hit first, 0 → partial R after the window."""
    if frame is None or frame.empty:
        return 0, 0.0
    entry = float(record.get("entry") or record.get("price") or 0.0)
    stop = float(record.get("stop_loss") or 0.0)
    target = float(record.get("take_profit_1") or 0.0)
    direction = 1 if record.get("signal") == "LONG" else -1

    if not entry or not stop or not target or (target - entry) * direction <= 0:
        return 0, 0.0

    risk = abs(entry - stop)
    if risk <= 0:
        return 0, 0.0

    for row in frame.itertuples(index=False):
        hit_stop = (row.low <= stop) if direction > 0 else (row.high >= stop)
        hit_target = (row.high >= target) if direction > 0 else (row.low <= target)

        if hit_stop and hit_target:
            if conservative:
                return -1, -1.0
            # whichever the candle opened closer to
            gap_stop = abs(row.open - stop)
            gap_target = abs(row.open - target)
            return (-1, -1.0) if gap_stop <= gap_target else (1, float(record.get("risk_reward_1") or 1.5))
        if hit_stop:
            return -1, -1.0
        if hit_target:
            return 1, float(record.get("risk_reward_1") or 1.5)

    last = float(frame["close"].iloc[-1])
    realized = (last - entry) * direction / risk
    return (0 if abs(realized) < 0.25 else (1 if realized > 0 else -1)), realized


# =====================================================================
# statistics
# =====================================================================

def summary(settings=None) -> Dict[str, Any]:
    settings = settings or get_settings()
    records = read_records(settings)
    evaluated = [r for r in records if r.get("outcome") is not None and r.get("signal") in ("LONG", "SHORT")]

    out: Dict[str, Any] = {
        "records": len(records),
        "signals": len([r for r in records if r.get("signal") in ("LONG", "SHORT")]),
        "evaluated": len(evaluated),
        "pending": len([r for r in records if r.get("outcome") is None and r.get("signal") in ("LONG", "SHORT")]),
        "path": str(journal_path(settings)),
        "enabled": enabled(settings),
    }
    if not evaluated:
        out.update({"win_rate": None, "avg_r": None, "expectancy": None, "by_symbol": {},
                    "by_confidence": {}, "components": {}})
        return out

    wins = sum(1 for r in evaluated if r["outcome"] > 0)
    rs = [float(r.get("outcome_r") or 0.0) for r in evaluated]
    out.update({
        "win_rate": round(100.0 * wins / len(evaluated), 1),
        "avg_r": round(float(np.mean(rs)), 3) if rs else 0.0,
        "expectancy": round(float(np.mean(rs)), 3) if rs else 0.0,
        "best_r": round(max(rs), 3) if rs else 0.0,
        "worst_r": round(min(rs), 3) if rs else 0.0,
        "by_symbol": _group(evaluated, "symbol"),
        "by_confidence": _by_confidence(evaluated),
        "components": component_stats(settings, evaluated=evaluated),
    })
    return out


def _group(records: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    buckets: Dict[str, List[float]] = {}
    for record in records:
        buckets.setdefault(str(record.get(key) or "?"), []).append(float(record.get("outcome_r") or 0.0))
    return {
        name: {"trades": len(values), "win_rate": None, "avg_r": round(float(np.mean(values)), 3)}
        for name, values in buckets.items()
    }


def _by_confidence(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, List[float]] = {}
    for record in records:
        confidence = float(record.get("confidence") or 0)
        label = "<40" if confidence < 40 else "40-59" if confidence < 60 else "60-79" if confidence < 80 else "80+"
        buckets.setdefault(label, []).append(float(record.get("outcome_r") or 0.0))
    out = {}
    for label, values in buckets.items():
        wins = sum(1 for v in values if v > 0)
        out[label] = {"trades": len(values), "win_rate": round(100.0 * wins / len(values), 1),
                      "avg_r": round(float(np.mean(values)), 3)}
    return out


def component_stats(settings=None, *, evaluated: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Information coefficient per component (correlation with realised R)."""
    settings = settings or get_settings()
    records = evaluated if evaluated is not None else [
        r for r in read_records(settings)
        if r.get("outcome") is not None and r.get("signal") in ("LONG", "SHORT")
    ]
    if len(records) < 3:
        return {}

    names = set()
    for record in records:
        names.update((record.get("components") or {}).keys())

    realized = np.array([float(r.get("outcome_r") or 0.0) for r in records], dtype=float)
    direction = np.array([1.0 if r.get("signal") == "LONG" else -1.0 for r in records], dtype=float)
    signed = realized * direction          # >0 = the trade worked in its own direction

    out: Dict[str, Any] = {}
    for name in sorted(names):
        series = np.array([float((r.get("components") or {}).get(name, 0.0) or 0.0) for r in records], dtype=float)
        if np.std(series) < 1e-6 or np.std(signed) < 1e-6:
            out[name] = {"samples": int(len(records)), "ic": 0.0, "avg_when_right": 0.0,
                         "avg_when_wrong": 0.0, "usable": False}
            continue
        ic = float(np.corrcoef(series, signed)[0, 1])
        mask_right = signed > 0
        mask_wrong = signed <= 0
        out[name] = {
            "samples": int(len(records)),
            "ic": round(ic, 3),
            "avg_when_right": round(float(series[mask_right].mean()), 1) if mask_right.any() else 0.0,
            "avg_when_wrong": round(float(series[mask_wrong].mean()), 1) if mask_wrong.any() else 0.0,
            "usable": abs(ic) >= 0.1,
        }
    return out
