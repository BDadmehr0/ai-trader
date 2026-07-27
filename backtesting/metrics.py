import numpy as np


def calculate_metrics(
    trades,
    equity_curve,
    initial_balance,
):

    if not trades:

        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "total_return": 0,
            "max_drawdown": 0,
            "average_pnl": 0,
            "wins": 0,
            "losses": 0,
        }

    pnls = [
        trade.pnl
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
            - initial_balance
        )
        / initial_balance
        * 100
    )

    # =========================
    # Maximum Drawdown
    # =========================

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
        ) / peaks * 100

        max_drawdown = abs(
            drawdowns.min()
        )

    else:

        max_drawdown = 0

    average_pnl = (
        sum(pnls)
        / total_trades
    )

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "average_pnl": average_pnl,
        "wins": len(wins),
        "losses": len(losses),
        "final_balance": final_balance,
    }