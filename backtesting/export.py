import pandas as pd


def export_trades(
    trades,
    filename="backtest_trades.csv",
):

    if not trades:

        return

    rows = []

    for trade in trades:

        rows.append(
            {
                "entry_time": (
                    trade.entry_time
                ),

                "exit_time": (
                    trade.exit_time
                ),

                "direction": (
                    trade.direction
                ),

                "entry_price": (
                    trade.entry_price
                ),

                "exit_price": (
                    trade.exit_price
                ),

                "stop_loss": (
                    trade.stop_loss
                ),

                "take_profit": (
                    trade.take_profit
                ),

                "position_size": (
                    trade.position_size
                ),

                "pnl": (
                    trade.pnl
                ),

                "pnl_percent": (
                    trade.pnl_percent
                ),

                "exit_reason": (
                    trade.exit_reason
                ),
            }
        )

    df = pd.DataFrame(
        rows
    )

    df.to_csv(
        filename,
        index=False,
    )

    print(
        f"Trades exported to {filename}"
    )