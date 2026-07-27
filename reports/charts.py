import matplotlib.pyplot as plt


def plot_equity_curve(
    equity_curve,
):

    if not equity_curve:

        return

    plt.figure(
        figsize=(12, 6)
    )

    plt.plot(
        equity_curve
    )

    plt.title(
        "BTC AI Trader - Equity Curve"
    )

    plt.xlabel(
        "Backtest Step"
    )

    plt.ylabel(
        "Equity"
    )

    plt.grid(
        True
    )

    plt.tight_layout()

    plt.savefig(
        "equity_curve.png"
    )

    plt.show()