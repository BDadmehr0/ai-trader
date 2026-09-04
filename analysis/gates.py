"""
Quality gates — the "don't take every A-minus trade" layer.

The scoring engine decides a *direction*; the gates decide whether that
direction is actually tradable right now. Each gate is either:

* blocking → the signal is demoted to WAIT (hard rule)
* warning  → the signal survives with a confidence penalty (soft rule)

Every gate (passed, failed or skipped) is returned with a human note, which is
what the dashboard renders as "signal checks" and what makes the model auditable
instead of a black box.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from config.store import get_settings


@dataclass
class Gate:
    key: str
    label: str
    status: str = "SKIP"        # PASS | FAIL | SKIP
    blocking: bool = False
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.status in ("PASS", "SKIP")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GateResult:
    gates: List[Gate] = field(default_factory=list)
    signal: str = "WAIT"
    proposal: str = "WAIT"
    confidence: int = 0
    blocked_by: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_by)

    @property
    def passed_count(self) -> int:
        return sum(1 for g in self.gates if g.status == "PASS")

    @property
    def total_count(self) -> int:
        return sum(1 for g in self.gates if g.status in ("PASS", "FAIL"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gates": [g.to_dict() for g in self.gates],
            "signal": self.signal,
            "proposal": self.proposal,
            "confidence": self.confidence,
            "blocked": self.blocked,
            "blocked_by": self.blocked_by,
            "warnings": self.warnings,
            "notes": self.notes,
            "passed": self.passed_count,
            "total": self.total_count,
        }


def _value(snapshot: Optional[Dict[str, Any]], key: str, default: Any = None) -> Any:
    if not snapshot:
        return default
    value = snapshot.get(key, default)
    return default if value is None else value


def evaluate_gates(*, settings=None, proposal: str, confidence: int, primary: Optional[Dict] = None,
                   mid: Optional[Dict] = None, levels=None, setup=None, news=None,
                   derivatives=None, cross_asset=None, alignment: Optional[Dict[str, int]] = None,
                   enable_risk_gates: bool = True) -> GateResult:
    settings = settings or get_settings()
    gates: List[Gate] = []
    notes: List[str] = []
    primary = primary or {}
    mid = mid or {}

    direction = 1 if proposal == "LONG" else -1 if proposal == "SHORT" else 0
    is_trade = proposal in ("LONG", "SHORT")

    def add(key, label, passed, note, *, blocking=True, applicable=True):
        status = "SKIP" if applicable is False else ("PASS" if passed else "FAIL")
        gates.append(Gate(key=key, label=label, status=status, blocking=blocking, note=note))
        return status == "PASS"

    # ---- 1. direction enabled ---------------------------------------
    if is_trade:
        allowed = (proposal == "LONG" and settings.allow_longs) or (proposal == "SHORT" and settings.allow_shorts)
        add("direction", "Direction allowed", allowed,
            f"{proposal} enabled in settings" if allowed else f"{proposal} disabled in settings")

    # ---- 2. minimum confidence -------------------------------------
    if is_trade:
        ok = confidence >= int(settings.min_confidence)
        add("confidence", "Confidence floor", ok,
            f"{confidence}% vs floor {settings.min_confidence}%",
            blocking=False, applicable=True)

    # ---- 3. multi-timeframe alignment ------------------------------
    if is_trade and alignment:
        needed = int(settings.require_trend_alignment)
        label_key = "BULLISH" if proposal == "LONG" else "BEARISH"
        agreed = int(alignment.get(label_key, 0))
        add("alignment", "Timeframes aligned", agreed >= needed,
            f"{agreed}/{alignment.get('total', 3)} timeframes {label_key.lower()} (need {needed})",
            applicable=needed > 0)

    # ---- 4. RSI zone ------------------------------------------------
    rsi = _value(mid, "rsi") or _value(primary, "rsi")
    if is_trade and rsi is not None:
        if proposal == "LONG":
            ok = float(settings.rsi_long_min) <= rsi <= float(settings.rsi_long_max)
            zone = f"{settings.rsi_long_min:g}–{settings.rsi_long_max:g}"
        else:
            ok = float(settings.rsi_short_min) <= rsi <= float(settings.rsi_short_max)
            zone = f"{settings.rsi_short_min:g}–{settings.rsi_short_max:g}"
        add("rsi_zone", "RSI entry zone", ok, f"RSI {rsi:.1f} vs {zone} on {settings.tf_mid.upper()}",
            blocking=False)

    # ---- 5. MACD confirmation --------------------------------------
    if is_trade and settings.require_macd_cross:
        hist = _value(primary, "macd_histogram", _value(mid, "macd_histogram"))
        if hist is not None:
            ok = (float(hist) > 0) == (direction > 0)
            add("macd", "MACD confirmation", ok,
                f"histogram {float(hist):+.3f} {'supports' if ok else 'fights'} {proposal}")

    # ---- 6. volume confirmation ------------------------------------
    if is_trade and settings.require_volume_confirm:
        ratio = _value(primary, "volume_ratio", _value(mid, "volume_ratio"))
        if ratio is not None:
            ok = float(ratio) >= float(settings.min_volume_ratio)
            add("volume", "Volume confirmation", ok,
                f"volume {float(ratio):.2f}x vs min {settings.min_volume_ratio:g}x", blocking=False)

    # ---- 7. structure agreement ------------------------------------
    if is_trade and settings.require_structure_agreement:
        structure = str(_value(primary, "structure_trend", _value(mid, "structure_trend", "")) or "")
        if structure:
            want = "BULLISH" if proposal == "LONG" else "BEARISH"
            ok = structure == want or structure == "NEUTRAL"
            add("structure", "Market structure agrees", ok,
                f"structure {structure} vs {want} desired", blocking=False)

    # ---- 8. trend strength (ADX) -----------------------------------
    adx = _value(primary, "adx")
    if is_trade and adx is not None and float(settings.adx_trend_min) > 0:
        squeeze = bool(_value(primary, "bb_squeeze", False))
        ok = float(adx) >= float(settings.adx_trend_min) or squeeze
        add("adx", "Trend strength (ADX)", ok,
            f"ADX {float(adx):.1f} vs {settings.adx_trend_min:g}" + (" · squeeze breakout allowed" if squeeze and not float(adx) >= float(settings.adx_trend_min) else ""),
            blocking=False)

    # ---- 9. overextension (chasing) --------------------------------
    if is_trade:
        over = _value(mid, "overextension_pct", _value(primary, "overextension_pct"))
        if over is not None:
            ok = abs(float(over)) <= float(settings.max_overextension_pct) or (float(over) * direction) <= 0
            add("overextension", "Not overextended", ok,
                f"price is {float(over):+.2f}% from EMA{settings.ema_fast} (max {settings.max_overextension_pct:g}%)",
                blocking=False)

    # ---- 10. volatility regime -------------------------------------
    if is_trade:
        regime = str(_value(primary, "volatility_regime", "")) or None
        if regime:
            ok = regime != "EXTREME"
            add("volatility", "Volatility regime", ok, f"ATR regime {regime}")

    # ---- 11. liquidity / spread -------------------------------------
    if enable_risk_gates and derivatives is not None and getattr(derivatives, "available", False):
        liquidity_ok = getattr(derivatives, "liquidity_ok", None)
        if liquidity_ok is not None:
            add("liquidity", "Liquidity & spread", bool(liquidity_ok),
                "; ".join(getattr(derivatives, "gates", []) or []) or "spread and 24h volume acceptable")

    # ---- 12. risk / reward ------------------------------------------
    if enable_risk_gates and is_trade and setup is not None:
        rr = float(getattr(setup, "risk_reward_1", 0.0) or 0.0)
        ok = rr >= float(settings.min_risk_reward)
        add("risk_reward", "R:R acceptable", ok,
            f"TP1 at {rr:.2f}R (min {settings.min_risk_reward:g}R)", blocking=False)

        status = str(getattr(setup, "status", "") or "")
        if "NEARBY" in status.upper():
            add("target_clear", "Target path is clear", False,
                f"{status} — first target sits behind a level", blocking=False)
        else:
            add("target_clear", "Target path is clear", True, "no level between entry and TP1")

    # ---- 13. news guard ---------------------------------------------
    if is_trade and news is not None:
        veto = getattr(news, "veto", None) or {}
        if veto.get("triggered"):
            opposed = veto.get("opposes")
            if veto.get("blocking") and opposed == proposal:      # guard blocks this exact trade
                add("news", "News guard", False, veto.get("note", "extreme news"), blocking=True)
            else:
                add("news", "News guard", proposal != veto.get("opposes"),
                    veto.get("note", "news flow opposite"), blocking=False)
        else:
            add("news", "News guard", True, "no extreme headline risk",
                applicable=bool(getattr(news, "available", False)))

    # ---- 14. BTC regime ---------------------------------------------
    if is_trade and cross_asset is not None and getattr(cross_asset, "available", False):
        opposes = (proposal == "LONG" and cross_asset.opposes_long) or (proposal == "SHORT" and cross_asset.opposes_short)
        add("btc_regime", "Aligned with BTC", not opposes,
            "BTC trend opposes this direction" if opposes else f"BTC {cross_asset.btc_regime.lower()} regime ok",
            blocking=False)

    # ---- verdict -----------------------------------------------------
    blocked_by = [g.note or g.label for g in gates if g.status == "FAIL" and g.blocking]
    warnings = [g.note or g.label for g in gates if g.status == "FAIL" and not g.blocking]
    penalty = min(25, 4 * len(warnings))
    final_confidence = max(0, min(100, int(confidence) - (penalty if is_trade else 0)))

    final_signal = proposal
    if is_trade and blocked_by:
        final_signal = "NO_TRADE"
        notes.append("signal demoted by blocking gates: " + "; ".join(blocked_by))
        final_confidence = min(final_confidence, 35)

    return GateResult(gates=gates, signal=final_signal, proposal=proposal,
                      confidence=final_confidence, blocked_by=blocked_by, warnings=warnings,
                      notes=notes)
