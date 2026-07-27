import sys

from data.market_data import (
    MarketData,
)

from analysis.indicators import (
    add_indicators,
)

from backtesting.engine import (
    BacktestEngine,
)

from backtesting.metrics import (
    calculate_metrics,
)

from backtesting.export import (
    export_trades,
)

from reports.backtest_report import (
    print_backtest_report,
)

from config.settings import (
    SYMBOL,
    CANDLE_LIMIT,
)


def run_backtest():

    print(
        "Fetching historical BTC data..."
    )

    market = MarketData()

    df = market.get_ohlcv(
        symbol=SYMBOL,
        timeframe="1h",
        limit=CANDLE_LIMIT,
    )

    print(
        f"Loaded {len(df)} candles."
    )

    print(
        "Calculating indicators..."
    )

    df = add_indicators(
        df
    )

    print(
        "Running backtest..."
    )

    engine = BacktestEngine()

    trades = engine.run(
        df
    )

    metrics = calculate_metrics(
        trades=trades,
        equity_curve=(
            engine.equity_curve
        ),
        initial_balance=(
            engine.initial_balance
        ),
    )

    export_trades(
        trades
    )

    print_backtest_report(
        metrics
    )


def main():

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python main.py backtest"
        )

        return

    command = (
        sys.argv[1].lower()
    )

    if command == "backtest":

        run_backtest()

    else:

        print(
            f"Unknown command: {command}"
        )


if __name__ == "__main__":

    main()