"""
Flask web panel - Professional AI Trading Dashboard.
"""

from flask import Flask, jsonify, render_template, request

from analysis.live import build_signal_report
from data.market_data import MarketData
from config.settings import (
    SYMBOL, QUOTE, SUPPORTED_COINS, CHART_CANDLE_LIMIT, CANDLE_LIMIT,
)

CHART_TIMEFRAMES = ("15m", "1h", "4h")


def normalize_symbol(value):
    raw = (value or "").strip().upper()
    if not raw:
        return SYMBOL
    base = raw.replace("_", "/").replace("-", "/").split("/")[0].strip()
    if not base:
        return SYMBOL
    return f"{base}/{QUOTE}"


def _valid_timeframe(value):
    return value if value in CHART_TIMEFRAMES else "1h"


def _chart_candles(market, symbol, timeframe):
    df = market.get_ohlcv(symbol, timeframe, CHART_CANDLE_LIMIT)
    df = df.tail(CHART_CANDLE_LIMIT)
    candles = []
    for row in df.itertuples(index=False):
        candles.append({
            "time": int(row.timestamp.timestamp()),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        })
    return candles


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    def current_report(symbol):
        return build_signal_report(MarketData(), symbol)

    @app.context_processor
    def inject_globals():
        return {"coins": SUPPORTED_COINS, "default_symbol": SYMBOL}

    @app.route("/")
    def dashboard():
        symbol = normalize_symbol(request.args.get("symbol"))
        timeframe = _valid_timeframe(request.args.get("tf"))

        market = MarketData()
        report = build_signal_report(market, symbol)
        candles = _chart_candles(market, symbol, timeframe)

        chart_data = {
            "symbol": symbol,
            "tf": timeframe,
            "signal": report["signal"],
            "live": market.is_live,
            "candles": candles,
            "setup": report["setup"],
            "levels": report["levels"],
            "scores": report.get("scores", {}),
        }

        return render_template("dashboard.html", report=report, symbol=symbol,
                                timeframe=timeframe, chart_data=chart_data)

    @app.route("/api/signal")
    def api_signal():
        symbol = normalize_symbol(request.args.get("symbol"))
        return jsonify(current_report(symbol))

    @app.route("/api/candles")
    def api_candles():
        symbol = normalize_symbol(request.args.get("symbol"))
        timeframe = _valid_timeframe(request.args.get("tf"))

        market = MarketData()
        candles = _chart_candles(market, symbol, timeframe)
        return jsonify({
            "symbol": symbol,
            "tf": timeframe,
            "live": market.is_live,
            "candles": candles,
        })

    @app.route("/backtest")
    def backtest_page():
        metrics, trades, backtest_live = _run_backtest()
        return render_template("backtest.html", metrics=metrics, trades=trades,
                                live=backtest_live, symbol=SYMBOL)

    return app


def _run_backtest():
    from analysis.indicators import add_indicators
    from backtesting.mtf import prepare_mtf_data
    from backtesting.engine import BacktestEngine
    from backtesting.metrics import calculate_metrics
    from config.settings import CANDLE_LIMIT, INITIAL_BALANCE

    market = MarketData()

    df_15m = add_indicators(market.get_ohlcv(SYMBOL, "15m", CANDLE_LIMIT))
    df_1h = add_indicators(market.get_ohlcv(SYMBOL, "1h", CANDLE_LIMIT))
    df_4h = add_indicators(market.get_ohlcv(SYMBOL, "4h", CANDLE_LIMIT))

    df = prepare_mtf_data(df_15m, df_1h, df_4h)

    engine = BacktestEngine(INITIAL_BALANCE)
    trades = engine.run(df)
    metrics = calculate_metrics(trades, engine.equity_curve, INITIAL_BALANCE)

    trade_rows = [_serialize_trade(t) for t in trades]
    return metrics, trade_rows, market.is_live


def _serialize_trade(trade):
    return {
        "entry_time": str(trade.entry_time),
        "exit_time": str(trade.exit_time),
        "direction": trade.direction,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "net_pnl": trade.net_pnl,
        "return_on_margin": trade.return_on_margin,
        "exit_reason": trade.exit_reason,
        "holding_candles": trade.holding_candles,
    }