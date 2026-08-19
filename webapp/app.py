"""
Flask web panel for the AI BTC Trader.

Routes
------
GET /             -> server-rendered dashboard (live signal)
GET /api/signal   -> JSON signal report (used by the page to auto-refresh)
GET /backtest     -> run a backtest and show the results table
"""

from flask import Flask, jsonify, render_template

from analysis.live import build_signal_report
from data.market_data import MarketData
from config.settings import SYMBOL


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    def current_report():
        return build_signal_report(MarketData(), SYMBOL)

    @app.route("/")
    def dashboard():
        report = current_report()
        return render_template("dashboard.html", report=report)

    @app.route("/api/signal")
    def api_signal():
        report = current_report()
        return jsonify(report)

    @app.route("/backtest")
    def backtest_page():
        metrics, trades, backtest_live = _run_backtest()
        return render_template(
            "backtest.html",
            metrics=metrics,
            trades=trades,
            live=backtest_live,
        )

    return app


def _run_backtest():
    """Run the historical backtest and return (metrics, trades, live_flag)."""
    from analysis.indicators import add_indicators
    from backtesting.mtf import prepare_mtf_data
    from backtesting.engine import BacktestEngine
    from backtesting.metrics import calculate_metrics
    from backtesting.models import Trade
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
