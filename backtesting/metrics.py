import math

import numpy as np


def calculate_metrics(
    trades,
    equity_curve,
    initial_balance,
):

    if not trades:

        return {}

    pnls = [

        trade.net_pnl

        for trade in trades

    ]

    wins = [

        pnl

        for pnl in pnls

        if pnl > 0

    ]

    losses = [

        pnl

        for pnl in pnls

        if pnl < 0

    ]

    total_trades = len(
        trades
    )

    win_rate = (

        len(wins)

        / total_trades

        * 100

    )

    gross_profit = sum(
        wins
    )

    gross_loss = abs(
        sum(losses)
    )

    if gross_loss > 0:

        profit_factor = (

            gross_profit

            / gross_loss

        )

    else:

        profit_factor = float(
            "inf"
        )

    final_balance = (

        initial_balance

        + sum(pnls)

    )

    total_return = (

        (
            final_balance
            / initial_balance
        )

        - 1

    ) * 100

    equity = np.array(
        equity_curve,
        dtype=float,
    )

    if len(equity) > 0:

        peaks = np.maximum.accumulate(
            equity
        )

        drawdowns = (

            equity

            - peaks

        ) / peaks

        max_drawdown = (

            abs(
                drawdowns.min()
            )

            * 100

        )

    else:

        max_drawdown = 0

    average_win = (

        np.mean(wins)

        if wins

        else 0

    )

    average_loss = (

        abs(
            np.mean(losses)
        )

        if losses

        else 0

    )

    expectancy = (

        (
            len(wins)
            / total_trades
        )

        * average_win

        -

        (
            len(losses)
            / total_trades
        )

        * average_loss

    )

    returns = (

        np.array(pnls)

        / initial_balance

    )

    if (

        len(returns) > 1

        and

        returns.std() > 0

    ):

        sharpe = (

            returns.mean()

            / returns.std()

        ) * np.sqrt(
            len(returns)
        )

    else:

        sharpe = 0

    long_trades = [

        trade

        for trade in trades

        if trade.direction
        == "LONG"

    ]

    short_trades = [

        trade

        for trade in trades

        if trade.direction
        == "SHORT"

    ]

    average_pnl = (

        float(np.mean(pnls))

        if pnls

        else 0.0

    )

    holding = [

        int(trade.holding_candles or 0)

        for trade in trades

    ]

    exits: dict = {}

    for trade in trades:

        reason = str(trade.exit_reason or "UNKNOWN")

        exits[reason] = exits.get(reason, 0) + 1

    equity_arr = np.array(equity_curve, dtype=float)

    downside = returns[returns < 0] if len(returns) else returns

    sortino = (

        float(returns.mean() / downside.std() * math.sqrt(len(returns)))

        if len(returns) > 1 and len(downside) > 0 and downside.std() > 0

        else 0.0

    )

    net_profit = final_balance - initial_balance

    recovery_factor = (

        net_profit / max(1e-9, float(initial_balance * max_drawdown / 100.0))

        if max_drawdown

        else 0.0

    )

    return {

        "average_pnl":

            average_pnl,

        "avg_holding_candles":

            float(np.mean(holding)) if holding else 0.0,

        "sortino":

            sortino,

        "recovery_factor":

            recovery_factor,

        "exit_reasons":

            exits,

        "net_profit":

            net_profit,

        "total_trades":
            total_trades,

        "wins":
            len(wins),

        "losses":
            len(losses),

        "win_rate":
            win_rate,

        "profit_factor":
            profit_factor,

        "total_return":
            total_return,

        "max_drawdown":
            max_drawdown,

        "average_win":
            average_win,

        "average_loss":
            average_loss,

        "expectancy":
            expectancy,

        "sharpe":
            sharpe,

        "long_trades":
            len(long_trades),

        "short_trades":
            len(short_trades),

        "final_balance":
            final_balance,

    }