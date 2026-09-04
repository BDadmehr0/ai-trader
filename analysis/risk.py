"""
Trade construction: stop, targets, size.

Stops and targets are no longer fixed ATR multiples: the mode is configurable
(ATR / structure / hybrid), targets respect the nearest S/R zone so we never
promise a TP that sits above a wall, and position size is derived from the
account risk — which is the only part of a "signal" that actually protects
capital.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.store import get_settings


@dataclass
class TradeSetup:
    signal: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward_1: float
    risk_reward_2: float
    confidence: int
    status: str
    stop_mode: str = ""
    target_mode: str = ""
    stop_distance: float = 0.0
    stop_distance_pct: float = 0.0
    risk_amount: float = 0.0
    position_size: float = 0.0
    notional: float = 0.0
    margin_required: float = 0.0
    notes: List[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        return self.signal in ("LONG", "SHORT") and self.stop_distance > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal": self.signal,
            "status": self.status,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "take_profit_2": self.take_profit_2,
            "risk_reward_1": self.risk_reward_1,
            "risk_reward_2": self.risk_reward_2,
            "confidence": self.confidence,
            "stop_mode": self.stop_mode,
            "target_mode": self.target_mode,
            "stop_distance": self.stop_distance,
            "stop_distance_pct": self.stop_distance_pct,
            "risk_amount": self.risk_amount,
            "position_size": self.position_size,
            "notional": self.notional,
            "margin_required": self.margin_required,
            "notes": self.notes,
        }


def _round(value: float, price: float) -> float:
    if not value:
        return 0.0
    magnitude = max(1e-8, abs(price))
    if magnitude >= 1000:
        digits = 1
    elif magnitude >= 10:
        digits = 2
    elif magnitude >= 0.1:
        digits = 4
    else:
        digits = 8
    return round(value, digits)


def _stop_for_direction(direction: int, entry: float, atr: float, swing: Optional[float],
                        settings) -> tuple:
    """Return (stop_price, mode_used, note)."""
    atr_mult = float(settings.atr_stop_multiplier)
    atr_stop = entry - direction * atr * atr_mult
    mode = settings.stop_mode
    notes: List[str] = []

    structure_stop = None
    if swing and ((direction > 0 and swing < entry) or (direction < 0 and swing > entry)):
        buffer = float(settings.stop_structure_buffer) * atr
        structure_stop = swing - direction * buffer

    max_distance = 3.0 * atr if atr > 0 else abs(entry) * 0.06

    if mode == "atr" or structure_stop is None:
        return atr_stop, "atr", ("" if mode == "atr" else "no usable swing level — ATR stop used")

    structure_distance = abs(entry - structure_stop)
    if mode == "structure":
        if structure_distance > max_distance:
            return atr_stop, "atr", f"structure stop too far ({structure_distance / atr:.1f}×ATR) — ATR used"
        return structure_stop, "structure", ""

    # hybrid: the safer (wider) of both, capped so risk stays sane
    stop = min(atr_stop, structure_stop) if direction > 0 else max(atr_stop, structure_stop)
    if abs(entry - stop) > max_distance:
        stop = entry - direction * max_distance
        notes.append("stop capped at 3×ATR")
    return stop, "hybrid", "; ".join(notes)


def create_trade_setup(signal, price, atr, support, resistance, confidence, *, settings=None,
                       swing_low=None, swing_high=None, levels=None,
                       volatility_regime: Optional[str] = None, balance: Optional[float] = None
                       ) -> TradeSetup:
    settings = settings or get_settings()
    price = float(price or 0.0)
    atr = float(atr or 0.0) or price * 0.01
    notes: List[str] = []

    if signal not in ("LONG", "SHORT"):
        return TradeSetup(signal="WAIT", entry=_round(price, price), stop_loss=0.0,
                          take_profit_1=0.0, take_profit_2=0.0, risk_reward_1=0.0,
                          risk_reward_2=0.0, confidence=int(confidence), status="NO TRADE",
                          notes=["no active setup"])

    direction = 1 if signal == "LONG" else -1
    swing = swing_low if direction > 0 else swing_high
    if swing is None and levels is not None:
        swing = getattr(levels, "last_swing_low" if direction > 0 else "last_swing_high", None)
    if swing is None:
        swing = support if direction > 0 else resistance

    entry = price
    stop, stop_mode, stop_note = _stop_for_direction(direction, entry, atr, swing, settings)
    if stop_note:
        notes.append(stop_note)

    risk = abs(entry - stop)
    if risk <= 0:
        stop = entry - direction * atr * 1.2
        risk = abs(entry - stop)
        stop_mode = "atr"
        notes.append("stop had no distance — ATR fallback used")

    if risk <= 0 or entry <= 0:
        # degenerate input (no price, no volatility): never invent levels for it
        return TradeSetup(signal="WAIT", entry=_round(entry, price or 0.0), stop_loss=0.0,
                          take_profit_1=0.0, take_profit_2=0.0, risk_reward_1=0.0,
                          risk_reward_2=0.0, confidence=int(confidence), status="NO TRADE",
                          notes=notes + ["no usable price/volatility data — no stop could be placed"])

    # ---- targets ----------------------------------------------------
    tp_mode = settings.target_mode
    tp1_r, tp2_r = float(settings.tp1_r), float(settings.tp2_r)
    atr_target = entry + direction * atr * float(settings.atr_tp_multiplier)

    wall = resistance if direction > 0 else support

    if tp_mode == "atr":
        tp1 = atr_target
        tp2 = entry + direction * atr * float(settings.atr_tp_multiplier) * 1.75
    elif tp_mode == "structure" and wall:
        candidate = wall - direction * max(atr * 0.1, abs(wall) * 0.0004)
        if abs(candidate - entry) < risk:               # wall is closer than 1R
            tp1 = atr_target
            tp2 = atr_target + direction * risk
            notes.append("nearest level is inside 1R — ATR targets used")
        else:
            tp1 = candidate
            tp2 = entry + direction * risk * tp2_r
    else:
        tp1 = entry + direction * risk * tp1_r
        tp2 = entry + direction * risk * tp2_r

    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk

    # ---- status -----------------------------------------------------
    status = f"{signal} SETUP"
    if direction > 0 and wall and entry < wall < tp1:
        status = "WAIT - RESISTANCE NEARBY"
        notes.append(f"resistance at {wall:,.6g} blocks TP1")
    elif direction < 0 and wall and tp1 < wall < entry:
        status = "WAIT - SUPPORT NEARBY"
        notes.append(f"support at {wall:,.6g} blocks TP1")

    if volatility_regime == "EXTREME":
        status = "WAIT - EXTREME VOLATILITY"
        notes.append("ATR regime EXTREME: stop distance unreliable")
    elif volatility_regime == "HIGH":
        notes.append("elevated volatility — consider half size")

    if rr1 < float(settings.min_risk_reward):
        notes.append(f"TP1 offers only {rr1:.2f}R (min {settings.min_risk_reward:g}R)")

    # ---- liquidation sanity (isolated margin) ------------------------
    leverage_setting = max(1.0, float(settings.leverage))
    liq = liquidation_distance(entry, stop, leverage_setting, float(settings.maintenance_margin))
    if liq and risk > liq:
        notes.append(
            f"stop is {risk / entry * 100:.2f}% away but at {leverage_setting:g}x you are liquidated "
            f"after {liq / entry * 100:.2f}% — lower the leverage or widen the margin"
        )
        if status.startswith(signal):
            status = f"{signal} SETUP (LIQUIDATION RISK)"

    # ---- sizing -----------------------------------------------------
    balance_value = float(balance if balance is not None else settings.initial_balance)
    risk_amount = balance_value * float(settings.risk_per_trade)
    size = risk_amount / risk if risk else 0.0
    notional = size * entry
    leverage = max(1.0, float(settings.leverage))
    max_notional = balance_value * leverage
    if notional > max_notional and notional > 0:
        size = max_notional / entry if entry else 0.0
        notional = max_notional
        risk_amount = size * risk
        notes.append(f"size capped by {leverage:g}x leverage")

    return TradeSetup(
        signal=signal,
        entry=_round(entry, price),
        stop_loss=_round(stop, price),
        take_profit_1=_round(tp1, price),
        take_profit_2=_round(tp2, price),
        risk_reward_1=round(rr1, 2),
        risk_reward_2=round(rr2, 2),
        confidence=int(confidence),
        status=status,
        stop_mode=stop_mode,
        target_mode=tp_mode,
        stop_distance=risk,
        stop_distance_pct=round(risk / entry * 100.0, 3) if entry else 0.0,
        risk_amount=round(risk_amount, 4),
        position_size=round(size, 8),
        notional=round(notional, 4),
        margin_required=round(notional / leverage, 4) if leverage else 0.0,
        notes=notes,
    )


def liquidation_distance(entry: float, stop: float, leverage: float, maintenance: float) -> float:
    """Absolute distance from entry to the (isolated-margin) liquidation price.

    ``1/leverage`` is the margin fraction, minus the maintenance buffer: a stop
    that sits further out than this never fires — the position is closed first.
    """
    entry = abs(float(entry or 0.0))
    leverage = float(leverage or 0.0)
    if not entry or leverage <= 0:
        return 0.0
    per_side = max(0.0, 1.0 / leverage - float(maintenance or 0.0))
    return round(entry * per_side, 8)


def stop_is_safe(entry: float, stop: float, leverage: float, maintenance: float) -> bool:
    """True when the stop fires before liquidation would."""
    if not entry:
        return False
    distance = abs(float(entry) - float(stop))
    liq = liquidation_distance(entry, stop, leverage, maintenance)
    return distance < liq
