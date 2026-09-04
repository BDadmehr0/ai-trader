"""Trade export — accepts engine Trade objects or serialised trade dicts."""

import pandas as pd

FIELDS = (
    "entry_time",
    "exit_time",
    "direction",
    "entry_price",
    "exit_price",
    "initial_stop",
    "final_stop",
    "take_profit",
    "position_size",
    "leverage",
    "margin_used",
    "entry_fee",
    "exit_fee",
    "funding_fee",
    "slippage_cost",
    "gross_pnl",
    "net_pnl",
    "return_on_margin",
    "exit_reason",
    "holding_candles",
)


def _value(trade, name):
    if isinstance(trade, dict):
        return trade.get(name)
    return getattr(trade, name, None)


def export_trades(trades, filename="trades.csv"):
    if not trades:
        print("No trades to export.")
        return None

    rows = [{field: _value(trade, field) for field in FIELDS} for trade in trades]
    df = pd.DataFrame(rows)
    df.to_csv(filename, index=False)
    print(f"{len(df)} trades exported to {filename}")
    return df
