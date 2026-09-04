"""
Derivatives & microstructure.

Positioning data is the single cheapest edge most retail dashboards miss:

* funding rate        → who is paying to stay in the market (crowded side)
* open interest       → is fresh money entering or leaving the move
* long/short ratios   → retail vs top-trader positioning
* taker buy/sell      → aggressive flow of the last hours
* order book imbalance → micro pressure right now

Sources are public Binance Futures endpoints (no API key) plus the exchange
order book through ccxt. Everything is cached and any failure degrades to
`available=False`, which makes the scorer drop this component's weight instead
of silently guessing zero.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config.store import get_settings
from utils.cache import cache_for
from utils.http import HttpError, request_json

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "derivatives"


@dataclass
class DerivativesAnalysis:
    available: bool = False
    status: str = "OFFLINE"                 # OK | PARTIAL | OFFLINE | DISABLED
    symbol: str = ""
    score: float = 0.0                       # [-100, 100] for the scoring engine
    positioning_score: float = 0.0           # funding / OI / ratios part
    micro_score: float = 0.0                 # order book part
    reliability: float = 0.0
    positioning_reliability: float = 0.0
    micro_reliability: float = 0.0
    crowd_state: str = "UNKNOWN"             # BALANCED | CROWDED_* | EXTREME_*
    funding_rate: Optional[float] = None
    funding_annual_pct: Optional[float] = None
    funding_note: str = ""
    open_interest_value: Optional[float] = None
    oi_change_pct: Optional[float] = None
    oi_price_alignment: str = "UNKNOWN"
    ls_account_ratio: Optional[float] = None
    ls_change_pct: Optional[float] = None
    top_trader_ratio: Optional[float] = None
    taker_buy_sell: Optional[float] = None
    book_imbalance: Optional[float] = None
    spread_pct: Optional[float] = None
    quote_volume_24h: Optional[float] = None
    liquidity_ok: Optional[bool] = None
    gates: List[str] = field(default_factory=list)
    factors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    error: Optional[str] = None
    age_seconds: Optional[float] = None
    updated: Optional[str] = None

    @property
    def crowded_against_long(self) -> bool:
        return self.crowd_state in ("CROWDED_LONG", "EXTREME_LONG")

    @property
    def crowded_against_short(self) -> bool:
        return self.crowd_state in ("CROWDED_SHORT", "EXTREME_SHORT")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "symbol": self.symbol,
            "score": round(self.score, 1),
            "positioning_score": round(self.positioning_score, 1),
            "micro_score": round(self.micro_score, 1),
            "reliability": round(self.reliability, 2),
            "crowd_state": self.crowd_state,
            "funding_rate": self.funding_rate,
            "funding_annual_pct": self.funding_annual_pct,
            "funding_note": self.funding_note,
            "open_interest_value": self.open_interest_value,
            "oi_change_pct": self.oi_change_pct,
            "oi_price_alignment": self.oi_price_alignment,
            "ls_account_ratio": self.ls_account_ratio,
            "ls_change_pct": self.ls_change_pct,
            "top_trader_ratio": self.top_trader_ratio,
            "taker_buy_sell": self.taker_buy_sell,
            "book_imbalance": self.book_imbalance,
            "spread_pct": self.spread_pct,
            "quote_volume_24h": self.quote_volume_24h,
            "liquidity_ok": self.liquidity_ok,
            "gates": self.gates,
            "factors": self.factors,
            "notes": self.notes,
            "error": self.error,
            "age_seconds": self.age_seconds,
            "updated": self.updated,
        }


# =====================================================================
# futures helpers
# =====================================================================

def futures_symbol(symbol: str) -> str:
    return str(symbol or "").replace("/", "").upper()


def _get_json(url: str, params: Dict[str, Any], settings) -> Any:
    return request_json(url, params=params, timeout=float(settings.derivatives_http_timeout),
                        proxy=settings.proxy_url or None)


def _series(rows: List[Dict[str, Any]], key: str) -> List[float]:
    out: List[float] = []
    for row in rows or []:
        try:
            out.append(float(row.get(key)))
        except (TypeError, ValueError):
            continue
    return out


# =====================================================================
# main
# =====================================================================

def analyze_derivatives(symbol: str, settings=None, *, price_change_pct: Optional[float] = None,
                        market=None, force: bool = False) -> DerivativesAnalysis:
    settings = settings or get_settings()
    fut = futures_symbol(symbol)

    if not settings.derivatives_enabled:
        return DerivativesAnalysis(symbol=fut, status="DISABLED", notes=["derivatives disabled in settings"])

    cache = cache_for(CACHE_NAMESPACE)
    key = (f"{fut}:{int(settings.oi_lookback_hours)}:{settings.micro_enabled}:"
           f"{settings.futures_base_url}")

    if not force:
        cached, age = cache.read(key)
        if isinstance(cached, dict):
            result = DerivativesAnalysis(**{k: v for k, v in cached.items()
                                           if k in DerivativesAnalysis.__dataclass_fields__})
            result.age_seconds = age
            return result

    base = settings.futures_base_url.rstrip("/")
    notes: List[str] = []
    data: Dict[str, Any] = {}

    # --- funding / premium index ------------------------------------
    try:
        premium = _get_json(f"{base}/fapi/v1/premiumIndex", {"symbol": fut}, settings)
        data["funding_rate"] = float(premium.get("lastFundingRate"))
        data["mark_price"] = float(premium.get("markPrice") or 0) or None
        next_time = premium.get("nextFundingTime")
        data["next_funding"] = next_time
    except (HttpError, ValueError, TypeError) as exc:
        notes.append(f"funding: {exc}")

    # --- open interest history --------------------------------------
    period = "1h"
    limit = max(2, int(settings.oi_lookback_hours))
    try:
        rows = _get_json(f"{base}/futures/data/openInterestHist",
                         {"symbol": fut, "period": period, "limit": limit}, settings)
        values = _series(rows if isinstance(rows, list) else [], "sumOpenInterestValue")
        if values:
            data["oi_value"] = values[-1]
            if len(values) >= 2 and values[0]:
                data["oi_change_pct"] = (values[-1] / values[0] - 1.0) * 100.0
    except (HttpError, ValueError, TypeError) as exc:
        notes.append(f"open interest: {exc}")

    # --- long / short ratios ----------------------------------------
    for field_name, endpoint, ratio_key in (
        ("ls_account", "globalLongShortAccountRatio", "longShortRatio"),
        ("ls_top", "topLongShortPositionRatio", "longShortRatio"),
    ):
        try:
            rows = _get_json(f"{base}/futures/data/{endpoint}",
                             {"symbol": fut, "period": period, "limit": max(2, limit)}, settings)
            series = _series(rows if isinstance(rows, list) else [], ratio_key)
            if series:
                data[field_name] = series[-1]
                if len(series) >= 2 and series[0]:
                    data[f"{field_name}_change_pct"] = (series[-1] / series[0] - 1.0) * 100.0
        except (HttpError, ValueError, TypeError) as exc:
            notes.append(f"{field_name}: {exc}")

    # --- taker buy / sell -------------------------------------------
    try:
        rows = _get_json(f"{base}/futures/data/takerlongshortRatio",
                         {"symbol": fut, "period": period, "limit": 3}, settings)
        series = _series(rows if isinstance(rows, list) else [], "buySellRatio")
        if series:
            data["taker_buy_sell"] = sum(series[-3:]) / len(series[-3:])
    except (HttpError, ValueError, TypeError) as exc:
        notes.append(f"taker ratio: {exc}")

    # --- order book microstructure ----------------------------------
    if settings.micro_enabled and market is not None:
        try:
            book = market.get_order_book(symbol, int(settings.order_book_depth))
            if book:
                data["book_imbalance"] = book.get("imbalance")
                data["spread_pct"] = book.get("spread_pct")
                data["best_bid"] = book.get("best_bid")
                data["best_ask"] = book.get("best_ask")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"order book: {exc}")

    ticker = None
    if market is not None:
        try:
            ticker = market.get_ticker(symbol)
        except Exception:  # noqa: BLE001
            ticker = None
    if ticker:
        try:
            if ticker.get("quote_volume"):
                data["quote_volume_24h"] = float(ticker["quote_volume"])
        except (TypeError, ValueError):
            pass

    # Only the exchange-derived numbers make this component trustworthy; 24h
    # volume by itself must not be dressed up as "positioning data".
    hard = any(key in data for key in ("funding_rate", "oi_value", "ls_account",
                                       "ls_top", "taker_buy_sell", "book_imbalance"))
    if not hard:
        result = DerivativesAnalysis(symbol=fut, status="OFFLINE", available=False,
                                     notes=notes[:6], error=notes[0] if notes else "no derivatives data")
        return result

    positioning, micro, crowd, factors, gates, pos_rel, micro_rel = _score_positioning(
        data, settings, price_change_pct)
    score = max(-100.0, min(100.0, positioning + micro))
    reliability = round(max(pos_rel, micro_rel), 3)

    from datetime import datetime, timezone

    payload = {
        "available": True,
        "status": "OK" if not notes else "PARTIAL",
        "symbol": fut,
        "score": score,
        "positioning_score": positioning,
        "micro_score": micro,
        "reliability": reliability,
        "positioning_reliability": pos_rel,
        "micro_reliability": micro_rel,
        "crowd_state": crowd,
        "funding_rate": data.get("funding_rate"),
        "funding_annual_pct": (data["funding_rate"] * 3 * 365 * 100) if data.get("funding_rate") is not None else None,
        "funding_note": factors[0] if factors else "",
        "open_interest_value": data.get("oi_value"),
        "oi_change_pct": data.get("oi_change_pct"),
        "oi_price_alignment": data.get("oi_alignment", "UNKNOWN"),
        "ls_account_ratio": data.get("ls_account"),
        "ls_change_pct": data.get("ls_account_change_pct"),
        "top_trader_ratio": data.get("ls_top"),
        "taker_buy_sell": data.get("taker_buy_sell"),
        "book_imbalance": data.get("book_imbalance"),
        "spread_pct": data.get("spread_pct"),
        "quote_volume_24h": data.get("quote_volume_24h"),
        "liquidity_ok": data.get("liquidity_ok"),
        "gates": gates,
        "factors": factors,
        "notes": notes[:6],
        "error": None,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mark_price": data.get("mark_price"),
    }
    cache.write(key, payload)
    result = DerivativesAnalysis(**{k: v for k, v in payload.items()
                                    if k in DerivativesAnalysis.__dataclass_fields__})
    result.oi_price_alignment = payload["oi_price_alignment"]
    return result


# =====================================================================
# positioning model
# =====================================================================

def _score_positioning(data: Dict[str, Any], settings, price_change_pct: Optional[float]):
    """Return (positioning_score, micro_score, crowd, factors, gates, pos_rel, micro_rel)."""
    score = 0.0          # positioning (funding / OI / ratios / flow)
    micro = 0.0          # order-book microstructure
    factors: List[str] = []
    gates: List[str] = []
    used = 0
    micro_used = 0

    # ---- funding ----------------------------------------------------
    funding = data.get("funding_rate")
    extreme = float(settings.funding_extreme)
    crowded = float(settings.funding_crowded)
    crowd = "BALANCED"
    if funding is not None:
        used += 1
        if funding >= extreme:
            score -= 45
            crowd = "EXTREME_LONG"
            factors.append(f"funding {funding * 100:.3f}%/8h — longs overpaying, squeeze risk")
        elif funding >= crowded:
            score -= 15
            crowd = "CROWDED_LONG"
            factors.append(f"funding {funding * 100:.3f}%/8h — longs crowded")
        elif funding <= -extreme:
            score += 35
            crowd = "EXTREME_SHORT"
            factors.append(f"funding {funding * 100:.3f}%/8h — shorts pay, squeeze fuel")
        elif funding <= -crowded:
            score += 12
            crowd = "CROWDED_SHORT"
            factors.append(f"funding {funding * 100:.3f}%/8h — shorts paying")
        else:
            factors.append(f"funding {funding * 100:.3f}%/8h — neutral")

    # ---- OI vs price -------------------------------------------------
    oi_change = data.get("oi_change_pct")
    if oi_change is not None:
        used += 1
        strong = float(settings.oi_strong_change) * 100.0
        price_up = (price_change_pct or 0) > 0
        price_known = price_change_pct is not None
        if oi_change >= strong:
            if not price_known:
                data["oi_alignment"] = "OI_UP"
                factors.append(f"open interest +{oi_change:.1f}% (fresh money)")
            elif price_up:
                data["oi_alignment"] = "TREND_CONFIRMED_UP"
                score += 18
                factors.append(f"OI +{oi_change:.1f}% with rising price — trend backed by new longs")
            else:
                data["oi_alignment"] = "SHORT_BUILD"
                score -= 18
                factors.append(f"OI +{oi_change:.1f}% with falling price — shorts being added")
        elif oi_change <= -strong:
            data["oi_alignment"] = "DELEVERAGING"
            if price_known:
                score += 6 if not price_up else -6
            factors.append(f"OI {oi_change:.1f}% — positions closing, move looks less persistent")
        else:
            data["oi_alignment"] = "STABLE"
            factors.append(f"OI {oi_change:+.1f}% — positioning stable")

    # ---- retail long/short ratio (contrarian) -----------------------
    ls = data.get("ls_account")
    if ls is not None:
        used += 1
        threshold = float(settings.ls_ratio_extreme)
        if ls >= threshold:
            score -= 22
            crowd = "EXTREME_LONG" if funding and funding >= extreme else "CROWDED_LONG"
            factors.append(f"long/short accounts {ls:.2f} — retail one-sided long (contrarian)")
        elif ls <= 1.0 / max(0.2, threshold):
            score += 18
            crowd = "CROWDED_SHORT"
            factors.append(f"long/short accounts {ls:.2f} — retail one-sided short")
        else:
            factors.append(f"long/short accounts {ls:.2f} — balanced positioning")

    top = data.get("ls_top")
    if top is not None:
        used += 1
        if top >= 1.6:
            score += 12
            factors.append(f"top traders net long {top:.2f} — smart-money bias up")
        elif top <= 0.75:
            score -= 12
            factors.append(f"top traders net short {top:.2f} — smart-money bias down")

    # ---- aggressive flow --------------------------------------------
    taker = data.get("taker_buy_sell")
    if taker is not None:
        used += 1
        if taker >= 1.06:
            score += 16
            factors.append(f"taker buy/sell {taker:.2f} — aggressive buying")
        elif taker <= 0.94:
            score -= 16
            factors.append(f"taker buy/sell {taker:.2f} — aggressive selling")

    # ---- order book --------------------------------------------------
    imbalance = data.get("book_imbalance")
    if imbalance is not None:
        micro_used += 1
        if imbalance >= 0.15:
            micro += 55
            factors.append(f"order book bid-heavy ({imbalance * 100:+.0f}%)")
        elif imbalance <= -0.15:
            micro -= 55
            factors.append(f"order book ask-heavy ({imbalance * 100:+.0f}%)")
        else:
            factors.append(f"order book balanced ({imbalance * 100:+.0f}%)")

    spread = data.get("spread_pct")
    if spread is not None:
        micro_used += 1
        if spread > float(settings.max_spread_pct):
            micro -= 30
            factors.append(f"wide spread {spread:.3f}% — execution risk")

    # ---- liquidity gates (hard filters, not scores) -----------------
    if spread is not None:
        data["max_spread_ok"] = spread <= float(settings.max_spread_pct)
        if spread > float(settings.max_spread_pct):
            gates.append(f"spread {spread:.3f}% above max {settings.max_spread_pct:.3f}%")
            data["liquidity_ok"] = False
        else:
            data["liquidity_ok"] = True

    quote_volume = data.get("quote_volume_24h")
    if quote_volume is not None and settings.min_quote_volume_24h > 0:
        if quote_volume < float(settings.min_quote_volume_24h):
            gates.append(f"24h volume {quote_volume:,.0f} below minimum")
            data["liquidity_ok"] = False
        else:
            data.setdefault("liquidity_ok", True)

    pos_rel = round(min(1.0, 0.35 + 0.15 * used), 3) if used else 0.0
    micro_rel = round(min(1.0, 0.4 + 0.25 * micro_used), 3) if micro_used else 0.0
    return (max(-100.0, min(100.0, score)), max(-100.0, min(100.0, micro)), crowd, factors, gates,
            pos_rel, micro_rel)


def crowd_label(state: str) -> str:
    return {
        "EXTREME_LONG": "خریداران بیش‌ازحد (ریسک سقوط ناگهانی)",
        "CROWDED_LONG": "لانگ شلوغ",
        "EXTREME_SHORT": "فروشندگان بیش‌ازحد (پتانسیل اسکوییز)",
        "CROWDED_SHORT": "شورت شلوغ",
        "BALANCED": "متعادل",
    }.get(state, "نامشخص")
