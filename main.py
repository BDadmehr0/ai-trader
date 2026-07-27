from data.market_data import (
    MarketData,
)

from analysis.indicators import (
    add_indicators,
)

from backtesting.mtf import (
    prepare_mtf_data,
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

from reports.charts import (
    plot_equity_curve,
)

from config.settings import (
    SYMBOL,
    CANDLE_LIMIT,
    INITIAL_BALANCE,
)


def run_backtest():

    print(
        "Fetching 15M data..."
    )

    market = MarketData()

    df_15m = (
        market.get_ohlcv(
            SYMBOL,
            "15m",
            CANDLE_LIMIT,
        )
    )

    print(
        "Fetching 1H data..."
    )

    df_1h = (
        market.get_ohlcv(
            SYMBOL,
            "1h",
            CANDLE_LIMIT,
        )
    )

    print(
        "Fetching 4H data..."
    )

    df_4h = (
        market.get_ohlcv(
            SYMBOL,
            "4h",
            CANDLE_LIMIT,
        )
    )

    print(
        "Calculating indicators..."
    )

    df_15m = add_indicators(
        df_15m
    )

    df_1h = add_indicators(
        df_1h
    )

    df_4h = add_indicators(
        df_4h
    )

    print(
        "Synchronizing timeframes..."
    )

    df = prepare_mtf_data(

        df_15m,

        df_1h,

        df_4h,

    )

    print(

        f"Prepared "
        f"{len(df)} candles."

    )

    print(
        "Running V5 MTF backtest..."
    )

    engine = BacktestEngine(

        INITIAL_BALANCE

    )

    trades = engine.run(
        df
    )

    metrics = calculate_metrics(

        trades,

        engine.equity_curve,

        INITIAL_BALANCE,

    )

    print()

    print(
        "========== V5 BACKTEST RESULT =========="
    )

    if not metrics:

        print(
            "No trades found."
        )

        return

    print(

        f"Trades: "
        f"{metrics['total_trades']}"

    )

    print(

        f"Wins: "
        f"{metrics['wins']}"

    )

    print(

        f"Losses: "
        f"{metrics['losses']}"

    )

    print(

        f"Win Rate: "
        f"{metrics['win_rate']:.2f}%"

    )

    print(

        f"Profit Factor: "
        f"{metrics['profit_factor']:.2f}"

    )

    print(

        f"Return: "
        f"{metrics['total_return']:.2f}%"

    )

    print(

        f"Max Drawdown: "
        f"{metrics['max_drawdown']:.2f}%"

    )

    print(

        f"Average Win: "
        f"${metrics['average_win']:.2f}"

    )

    print(

        f"Average Loss: "
        f"${metrics['average_loss']:.2f}"

    )

    print(

        f"Expectancy: "
        f"${metrics['expectancy']:.2f}"

    )

    print(

        f"Sharpe: "
        f"{metrics['sharpe']:.2f}"

    )

    print(

        f"Long Trades: "
        f"{metrics['long_trades']}"

    )

    print(

        f"Short Trades: "
        f"{metrics['short_trades']}"

    )

    print(

        f"Final Balance: "
        f"${metrics['final_balance']:.2f}"

    )

    print()

    export_trades(
        trades,
        "trades.csv",
    )

    plot_equity_curve(
        engine.equity_curve
    )


if __name__ == "__main__":

    run_backtest()