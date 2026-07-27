import numpy as np


def calculate_metrics(
    trades,
    equity_curve,
    initial_balance,
):

    if not trades:

        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "total_return": 0,
            "max_drawdown": 0,
            "average_win": 0,
            "average_loss": 0,
            "expectancy": 0,
            "sharpe": 0,
            "long_trades": 0,
            "short_trades": 0,
        }

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

    profit_factor = (
        gross_profit
        / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    final_balance = (
        initial_balance
        + sum(pnls)
    )

    total_return = (
        final_balance
        / initial_balance
        - 1
    ) * 100

    # -------------------------
    # Drawdown
    # -------------------------

    equity = np.array(
        equity_curve
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

    # -------------------------
    # Expectancy
    # -------------------------

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

    # -------------------------
    # Sharpe Approximation
    # -------------------------

    returns = np.array(
        pnls
    ) / initial_balance

    if (
        len(returns) > 1
        and returns.std() > 0
    ):

        sharpe = (
            returns.mean()
            / returns.std()
        ) * np.sqrt(
            len(returns)
        )

    else:

        sharpe = 0

    # -------------------------
    # Long / Short
    # -------------------------

    long_trades = [
        trade
        for trade in trades
        if trade.direction == "LONG"
    ]

    short_trades = [
        trade
        for trade in trades
        if trade.direction == "SHORT"
    ]

    return {
        "total_trades": total_trades,

        "wins": len(wins),

        "losses": len(losses),

        "win_rate": win_rate,

        "profit_factor": profit_factor,

        "total_return": total_return,

        "max_drawdown": max_drawdown,

        "average_win": average_win,

        "average_loss": average_loss,

        "expectancy": expectancy,

        "sharpe": sharpe,

        "long_trades": len(
            long_trades
        ),

        "short_trades": len(
            short_trades
        ),

        "final_balance": final_balance,
    }