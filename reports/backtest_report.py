from rich.console import Console
from rich.table import Table
from rich.panel import Panel


console = Console()


def print_backtest_report(
    metrics,
):

    console.print()

    console.print(
        Panel(
            "[bold cyan]"
            "BTC AI TRADER - BACKTEST"
            "[/bold cyan]",
            expand=False,
        )
    )

    console.print()

    table = Table(
        title="Backtest Performance"
    )

    table.add_column(
        "Metric"
    )

    table.add_column(
        "Value",
        justify="right",
    )

    table.add_row(
        "Total Trades",
        str(
            metrics[
                "total_trades"
            ]
        ),
    )

    table.add_row(
        "Wins",
        str(
            metrics[
                "wins"
            ]
        ),
    )

    table.add_row(
        "Losses",
        str(
            metrics[
                "losses"
            ]
        ),
    )

    table.add_row(
        "Win Rate",
        (
            f"{metrics['win_rate']:.2f}%"
        ),
    )

    table.add_row(
        "Profit Factor",
        (
            f"{metrics['profit_factor']:.2f}"
        ),
    )

    table.add_row(
        "Total Return",
        (
            f"{metrics['total_return']:.2f}%"
        ),
    )

    table.add_row(
        "Max Drawdown",
        (
            f"{metrics['max_drawdown']:.2f}%"
        ),
    )

    table.add_row(
        "Average PnL",
        (
            f"${metrics['average_pnl']:.2f}"
        ),
    )

    table.add_row(
        "Final Balance",
        (
            f"${metrics['final_balance']:.2f}"
        ),
    )

    console.print(
        table
    )

    console.print()

    console.print(
        "[dim]"
        "Backtest results are historical "
        "simulations and do not guarantee "
        "future performance."
        "[/dim]"
    )