from rich.console import Console
from rich.table import Table
from rich.panel import Panel


console = Console()


def get_trend_style(
    trend: str,
) -> str:

    if trend == "BULLISH":
        return "[green]BULLISH[/green]"

    if trend == "BEARISH":
        return "[red]BEARISH[/red]"

    return "[yellow]NEUTRAL[/yellow]"


def get_signal_style(
    signal: str,
) -> str:

    if signal == "LONG":
        return "[bold green]LONG[/bold green]"

    if signal == "SHORT":
        return "[bold red]SHORT[/bold red]"

    return "[bold yellow]WAIT[/bold yellow]"


def print_analysis(
    analysis_15m,
    analysis_1h,
    analysis_4h,
    signal,
    confidence,
    levels,
    trade_setup,
):

    console.print()

    console.print(
        Panel(
            "[bold cyan]"
            "BTC AI TRADER - VERSION 2"
            "[/bold cyan]",
            expand=False,
        )
    )

    console.print()

    # =========================
    # Market Table
    # =========================

    table = Table(
        title="Market Analysis"
    )

    columns = [
        "Timeframe",
        "Trend",
        "Score",
        "Price",
        "RSI",
        "EMA20",
        "EMA50",
        "EMA200",
        "Volume",
    ]

    for column in columns:

        table.add_column(
            column,
            justify="center",
        )

    analyses = [
        analysis_15m,
        analysis_1h,
        analysis_4h,
    ]

    for analysis in analyses:

        table.add_row(
            analysis.timeframe,

            get_trend_style(
                analysis.trend
            ),

            str(
                analysis.score
            ),

            f"{analysis.price:,.2f}",

            f"{analysis.rsi:.2f}",

            f"{analysis.ema20:,.2f}",

            f"{analysis.ema50:,.2f}",

            f"{analysis.ema200:,.2f}",

            f"{analysis.volume_ratio:.2f}x",
        )

    console.print(table)

    console.print()

    # =========================
    # Signal
    # =========================

    console.print(
        Panel(
            (
                f"Signal: "
                f"{get_signal_style(signal)}\n"
                f"Confidence: "
                f"{confidence}%"
            ),
            title="Signal",
            expand=False,
        )
    )

    console.print()

    # =========================
    # Market Levels
    # =========================

    levels_table = Table(
        title="Market Levels"
    )

    levels_table.add_column(
        "Level"
    )

    levels_table.add_column(
        "Price",
        justify="right",
    )

    levels_table.add_row(
        "Support 1",
        f"{levels.support_1:,.2f}",
    )

    levels_table.add_row(
        "Support 2",
        f"{levels.support_2:,.2f}",
    )

    levels_table.add_row(
        "Resistance 1",
        f"{levels.resistance_1:,.2f}",
    )

    levels_table.add_row(
        "Resistance 2",
        f"{levels.resistance_2:,.2f}",
    )

    console.print(
        levels_table
    )

    console.print()

    # =========================
    # Trade Setup
    # =========================

    if signal != "WAIT":

        trade_table = Table(
            title="Trade Setup"
        )

        trade_table.add_column(
            "Parameter"
        )

        trade_table.add_column(
            "Value",
            justify="right",
        )

        trade_table.add_row(
            "Status",
            trade_setup.status,
        )

        trade_table.add_row(
            "Entry",
            f"{trade_setup.entry:,.2f}",
        )

        trade_table.add_row(
            "Stop Loss",
            f"{trade_setup.stop_loss:,.2f}",
        )

        trade_table.add_row(
            "Take Profit 1",
            f"{trade_setup.take_profit_1:,.2f}",
        )

        trade_table.add_row(
            "Take Profit 2",
            f"{trade_setup.take_profit_2:,.2f}",
        )

        trade_table.add_row(
            "Risk / Reward 1",
            (
                f"1:"
                f"{trade_setup.risk_reward_1:.2f}"
            ),
        )

        trade_table.add_row(
            "Risk / Reward 2",
            (
                f"1:"
                f"{trade_setup.risk_reward_2:.2f}"
            ),
        )

        console.print(
            trade_table
        )

    else:

        console.print(
            Panel(
                "No valid trade setup.",
                title="Trade Setup",
                expand=False,
            )
        )

    console.print()

    # =========================
    # Summary
    # =========================

    console.print(
        "[bold]Analysis Summary[/bold]"
    )

    console.print(
        f"4H Trend: "
        f"{get_trend_style(analysis_4h.trend)}"
    )

    console.print(
        f"1H Trend: "
        f"{get_trend_style(analysis_1h.trend)}"
    )

    console.print(
        f"15M Trend: "
        f"{get_trend_style(analysis_15m.trend)}"
    )

    console.print(
        f"4H RSI: "
        f"{analysis_4h.rsi:.2f}"
    )

    console.print(
        f"1H RSI: "
        f"{analysis_1h.rsi:.2f}"
    )

    console.print(
        f"15M RSI: "
        f"{analysis_15m.rsi:.2f}"
    )

    console.print()

    console.print(
        "[dim]"
        "This system provides technical "
        "analysis only and does not guarantee "
        "future market movements."
        "[/dim]"
    )

    console.print()