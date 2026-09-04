"""
Cross-asset context (a.k.a. "don't fight Bitcoin").

Altcoins are leveraged beta to BTC: a strong BTC downtrend turns most alt LONG
setups into losses regardless of how pretty the 15m chart looks. This module
computes the BTC regime from the same indicator pipeline, plus correlation and
relative strength for the traded symbol, and turns it into a score component
and (optionally) a blocking gate.

Works completely offline: it only needs two OHLCV frames, which the demo data
provider also supplies.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from config.store import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CrossAssetAnalysis:
    available: bool = False
    status: str = "DISABLED"            # OK | SKIPPED | NO_DATA | DISABLED
    symbol: str = ""
    btc_regime: str = "NEUTRAL"
    btc_score: int = 0
    btc_trend_strength: str = "WEAK"
    correlation: Optional[float] = None
    beta: Optional[float] = None
    relative_strength_pct: Optional[float] = None
    score: float = 0.0                   # [-100, 100]
    opposes_long: bool = False
    opposes_short: bool = False
    factors: List[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "symbol": self.symbol,
            "btc_regime": self.btc_regime,
            "btc_score": self.btc_score,
            "btc_trend_strength": self.btc_trend_strength,
            "correlation": self.correlation,
            "beta": self.beta,
            "relative_strength_pct": self.relative_strength_pct,
            "score": round(self.score, 1),
            "opposes_long": self.opposes_long,
            "opposes_short": self.opposes_short,
            "factors": self.factors,
            "note": self.note,
        }


def _regime(df: pd.DataFrame) -> tuple:
    """Score a frame -5..+5 from EMAs / MACD / RSI, with ADX & SuperTrend context."""
    if df is None or df.empty:
        return "NEUTRAL", 0, "WEAK", 0.0

    row = df.dropna().iloc[-1]
    score = 0
    close = float(row["close"])

    if close > float(row["ema_fast"]):
        score += 1
    else:
        score -= 1
    if float(row["ema_fast"]) > float(row["ema_mid"]):
        score += 1
    else:
        score -= 1
    if float(row["ema_mid"]) > float(row["ema_slow"]):
        score += 1
    else:
        score -= 1
    if float(row["macd"]) > float(row["macd_signal"]):
        score += 1
    else:
        score -= 1
    if float(row["rsi"]) > 50:
        score += 1
    else:
        score -= 1

    if "supertrend_dir" in row.index and not pd.isna(row["supertrend_dir"]):
        score += 1 if row["supertrend_dir"] > 0 else -1
    if "adx" in row.index and not pd.isna(row["adx"]) and float(row["adx"]) < 18:
        score = int(round(score * 0.6))

    regime = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"
    strength = "STRONG" if abs(score) >= 5 else "MODERATE" if abs(score) >= 4 else "WEAK"
    change_pct = 0.0
    try:
        first = float(df["close"].iloc[-min(len(df), 96)])
        change_pct = (close / first - 1.0) * 100.0 if first else 0.0
    except (IndexError, ZeroDivisionError):
        pass
    return regime, score, strength, change_pct


def analyze_cross_asset(symbol: str, df: Optional[pd.DataFrame], btc_df: Optional[pd.DataFrame],
                        settings=None) -> CrossAssetAnalysis:
    settings = settings or get_settings()
    base = str(symbol or "").split("/")[0].upper()

    if not settings.cross_asset_enabled:
        return CrossAssetAnalysis(status="DISABLED", symbol=base, note="BTC filter off")
    if base == "BTC":
        return CrossAssetAnalysis(status="SKIPPED", symbol=base, note="symbol is BTC itself")
    if btc_df is None or len(btc_df) < 30:
        return CrossAssetAnalysis(status="NO_DATA", symbol=base, note="no BTC data available")

    regime, btc_score, strength, btc_change = _regime(btc_df)

    correlation = None
    beta = None
    relative = None
    factors: List[str] = []

    if df is not None and len(df) > 5:
        try:
            lookback = max(20, int(settings.cross_asset_lookback))
            asset = df[["timestamp", "close"]].tail(lookback).copy()
            bench = btc_df[["timestamp", "close"]].tail(lookback).copy()
            merged = pd.merge(asset, bench, on="timestamp", suffixes=("_a", "_b")).dropna()

            if len(merged) >= 12:
                ra = merged["close_a"].pct_change().dropna().to_numpy()
                rb = merged["close_b"].pct_change().dropna().to_numpy()
                size = min(len(ra), len(rb))
                ra, rb = ra[-size:], rb[-size:]
                if size > 5 and np.std(rb) > 0:
                    correlation = float(np.corrcoef(ra, rb)[0, 1])
                    beta = float(np.cov(ra, rb)[0, 1] / np.var(rb))

                pa, pb = float(merged["close_a"].iloc[-1]), float(merged["close_a"].iloc[0])
                ca, cb = float(merged["close_b"].iloc[-1]), float(merged["close_b"].iloc[0])
                if pa and pb and ca and cb:
                    relative = ((pa / pb) - 1.0) * 100.0 - ((ca / cb) - 1.0) * 100.0
        except Exception as exc:  # noqa: BLE001 - math on short series
            logger.debug("cross-asset stats failed: %s", exc)

    score = 0.0
    opposes_long = opposes_short = False
    strong = abs(btc_score) >= 4

    # A coin that does not trade with BTC must not be vetoed by BTC: the regime
    # effect is scaled by how correlated the two actually are.
    corr_min = max(0.05, float(settings.cross_asset_corr_min))
    if correlation is None:
        relaxation = 1.0
    elif correlation <= 0:
        relaxation = 0.0
        factors.append(f"no positive link to BTC (corr {correlation:.2f}) — regime filter skipped")
    else:
        relaxation = min(1.0, correlation / corr_min)
        if relaxation < 0.6:
            factors.append(f"weak link to BTC (corr {correlation:.2f}) — filter at {relaxation * 100:.0f}%")

    magnitude = 55.0 * (1.0 if strong else 0.6) * relaxation
    if magnitude > 1.0:
        if regime == "BEARISH":
            score -= magnitude
            factors.append(f"BTC trend bearish (score {btc_score:+d}, {btc_change:+.1f}%)")
            opposes_long = strong and relaxation >= 0.6
        elif regime == "BULLISH":
            score += magnitude
            factors.append(f"BTC trend bullish (score {btc_score:+d}, {btc_change:+.1f}%)")
            opposes_short = strong and relaxation >= 0.6

    if relative is not None:
        if relative > 2.0:
            score += min(20, relative)
            factors.append(f"outperforming BTC by {relative:+.1f}%")
        elif relative < -2.0:
            score -= min(20, abs(relative))
            factors.append(f"underperforming BTC by {relative:+.1f}%")

    if beta is not None and abs(beta) > 1.6:
        factors.append(f"high beta to BTC ({beta:.1f}x) — position size down")
        score *= 0.9

    return CrossAssetAnalysis(
        available=True,
        status="OK",
        symbol=base,
        btc_regime=regime,
        btc_score=btc_score,
        btc_trend_strength=strength,
        correlation=None if correlation is None else round(correlation, 3),
        beta=None if beta is None else round(beta, 2),
        relative_strength_pct=None if relative is None else round(relative, 2),
        score=max(-100.0, min(100.0, score)),
        opposes_long=opposes_long,
        opposes_short=opposes_short,
        factors=factors,
        note="BTC regime + correlation",
    )
