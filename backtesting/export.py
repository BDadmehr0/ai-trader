import pandas as pd


def export_trades(
    trades,
    filename="trades.csv",
):

    if not trades:

        print(
            "No trades to export."
        )

        return

    rows = []

    for trade in trades:

        rows.append({

            "entry_time":
                trade.entry_time,

            "exit_time":
                trade.exit_time,

            "direction":
                trade.direction,

            "entry_price":
                trade.entry_price,

            "exit_price":
                trade.exit_price,

            "initial_stop":
                trade.initial_stop,

            "final_stop":
                trade.final_stop,

            "take_profit":
                trade.take_profit,

            "position_size":
                trade.position_size,

            "leverage":
                trade.leverage,

            "margin_used":
                trade.margin_used,

            "entry_fee":
                trade.entry_fee,

            "exit_fee":
                trade.exit_fee,

            "funding_fee":
                trade.funding_fee,

            "slippage_cost":
                trade.slippage_cost,

            "gross_pnl":
                trade.gross_pnl,

            "net_pnl":
                trade.net_pnl,

            "return_on_margin":
                trade.return_on_margin,

            "exit_reason":
                trade.exit_reason,

            "holding_candles":
                trade.holding_candles,

        })

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