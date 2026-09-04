"""
Backtest service — one code path for the CLI, the web panel and the optimizer.

Fetches the three configured timeframes from whichever source is active
(exchange / your own CSV / demo), builds the MTF frame, runs the engine and
returns serialisable results.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from analysis.indicators import add_indicators
from backtesting.engine import BacktestEngine
from backtesting.metrics import calculate_metrics
from backtesting.mtf import prepare_mtf_data
from config.store import get_settings

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    symbol: str = ""
    source: str = ""
    live: bool = False
    ok: bool = True
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    initial_balance: float = 0.0

    def to_dict(self, *, include_trades: bool = True) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "live": self.live,
            "ok": self.ok,
            "error": self.error,
            "metrics": self.metrics,
            "trades": self.trades if include_trades else [],
            "equity": self.equity,
            "coverage": self.coverage,
            "params": self.params,
            "duration_ms": self.duration_ms,
            "initial_balance": self.initial_balance,
        }


def build_frames(market, settings, symbol: str) -> Dict[str, Any]:
    """{base_label: indicator frame} for the configured timeframes."""
    frames = {}
    for timeframe in settings.timeframe_list():
        frame = market.get_ohlcv(symbol, timeframe, settings.backtest_candles)
        frames[timeframe] = add_indicators(frame, settings)
    return frames


def run_backtest(symbol: Optional[str] = None, settings=None, market=None, *,
                 frames: Optional[Dict[str, Any]] = None, include_trades: bool = True
                 ) -> BacktestResult:
    settings = settings or get_settings()
    from data.market_data import MarketData

    started = time.time()
    symbol = symbol or settings.symbol
    owns_market = market is None
    market = market or MarketData(settings=settings)

    balance = float(settings.initial_balance)
    try:
        frames = frames or build_frames(market, settings, symbol)
        ordered = list(frames.values())
        if len(ordered) < 3 or any(frame is None or frame.empty for frame in ordered):
            return BacktestResult(symbol=symbol, ok=False, error="not enough candles for the configured timeframes",
                                  source=getattr(market, "source", "?"),
                                  live=bool(getattr(market, "is_live", False)))

        frame = prepare_mtf_data(ordered[0], ordered[1], ordered[2])
        if len(frame) < 60:
            return BacktestResult(symbol=symbol, ok=False,
                                  error=f"only {len(frame)} merged candles available — need 60+",
                                  source=getattr(market, "source", "?"),
                                  live=bool(getattr(market, "is_live", False)))

        engine = BacktestEngine(balance, settings=settings)
        trades = engine.run(frame)
        metrics = calculate_metrics(trades, engine.equity_curve, balance)

        return BacktestResult(
            symbol=symbol,
            source=getattr(market, "source", "?"),
            live=bool(getattr(market, "is_live", False)),
            metrics=metrics,
            trades=[serialize_trade(trade) for trade in trades][:200] if include_trades else [],
            equity=serialize_equity(engine.equity_curve, frame),
            coverage={
                "rows": int(len(frame)),
                "start": str(frame["timestamp"].iloc[0]),
                "end": str(frame["timestamp"].iloc[-1]),
                "timeframes": list(frames.keys()),
                "candles_per_timeframe": {tf: int(len(df)) for tf, df in frames.items()},
            },
            params={
                "risk_per_trade": settings.risk_per_trade,
                "leverage": settings.leverage,
                "stop_mode": settings.stop_mode,
                "atr_stop_multiplier": settings.atr_stop_multiplier,
                "target_mode": settings.target_mode,
                "tp2_r": settings.tp2_r,
                "entry_threshold": settings.entry_threshold,
                "pullback_distance": settings.pullback_distance,
                "min_volume_ratio": settings.min_volume_ratio,
                "max_atr_ratio": settings.max_atr_ratio,
                "max_overextension_pct": settings.max_overextension_pct,
                "max_holding_candles": settings.max_holding_candles,
                "cooldown_candles": settings.cooldown_candles,
                "adx_trend_min": settings.adx_trend_min,
                "taker_fee": settings.taker_fee,
                "slippage": settings.slippage,
            },
            duration_ms=int((time.time() - started) * 1000),
            initial_balance=balance,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        logger.exception("backtest failed")
        return BacktestResult(symbol=symbol, ok=False, error=str(exc)[:300],
                              duration_ms=int((time.time() - started) * 1000),
                              initial_balance=balance)


def serialize_trade(trade) -> Dict[str, Any]:
    return {
        "entry_time": str(trade.entry_time),
        "exit_time": str(trade.exit_time),
        "direction": trade.direction,
        "entry_price": round(float(trade.entry_price), 6),
        "exit_price": round(float(trade.exit_price), 6),
        "initial_stop": round(float(trade.initial_stop), 6),
        "final_stop": round(float(trade.final_stop), 6),
        "gross_pnl": round(float(trade.gross_pnl), 2),
        "net_pnl": round(float(trade.net_pnl), 2),
        "return_on_margin": round(float(trade.return_on_margin), 3),
        "exit_reason": trade.exit_reason,
        "holding_candles": trade.holding_candles,
        "fees": round(float(trade.entry_fee) + float(trade.exit_fee) + float(trade.funding_fee), 4),
        "take_profit": round(float(trade.take_profit), 6),
        "position_size": round(float(trade.position_size), 8),
        "leverage": round(float(trade.leverage), 2),
        "margin_used": round(float(trade.margin_used), 4),
        "entry_fee": round(float(trade.entry_fee), 6),
        "exit_fee": round(float(trade.exit_fee), 6),
        "funding_fee": round(float(trade.funding_fee), 6),
        "slippage_cost": round(float(trade.slippage_cost), 6),
    }


def serialize_equity(curve, frame=None, limit: int = 400) -> List[Dict[str, Any]]:
    """Down-sampled equity curve for the chart."""
    if not curve:
        return []

    stamps = list(frame["timestamp"]) if frame is not None and len(frame) == len(curve) else [None] * len(curve)
    step = max(1, len(curve) // limit)
    points = []
    for index in range(0, len(curve), step):
        value = float(curve[index])
        stamp = stamps[index]
        points.append({
            "i": index,
            "equity": round(value, 2),
            "time": int(pd_timestamp_seconds(stamp)) if stamp is not None else index,
        })
    return points


def pd_timestamp_seconds(stamp) -> int:
    try:
        import pandas as pd

        return int(pd.Timestamp(stamp).timestamp())
    except Exception:  # noqa: BLE001
        return 0
