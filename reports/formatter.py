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
    analysis_1h,
    analysis_4h,
    signal,
):

    console.print()

    console.print(
        Panel(
            "[bold cyan]BTC AI TRADER - VERSION 1[/bold cyan]",
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

    table.add_column(
        "Timeframe",
        justify="center",
    )

    table.add_column(
        "Trend",
        justify="center",
    )

    table.add_column(
        "Score",
        justify="center",
    )

    table.add_column(
        "Price",
        justify="right",
    )

    table.add_column(
        "RSI",
        justify="right",
    )

    table.add_column(
        "EMA20",
        justify="right",
    )

    table.add_column(
        "EMA50",
        justify="right",
    )

    table.add_column(
        "EMA200",
        justify="right",
    )

    table.add_column(
        "Volume",
        justify="right",
    )

    for analysis in [
        analysis_1h,
        analysis_4h,
    ]:

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

    signal_panel = Panel(
        get_signal_style(signal),
        title="Current Signal",
        expand=False,
    )

    console.print(
        signal_panel
    )

    console.print()

    # =========================
    # Explanation
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
        f"4H RSI: "
        f"{analysis_4h.rsi:.2f}"
    )

    console.print(
        f"1H RSI: "
        f"{analysis_1h.rsi:.2f}"
    )

    console.print(
        f"4H Volume: "
        f"{analysis_4h.volume_ratio:.2f}x"
    )

    console.print(
        f"1H Volume: "
        f"{analysis_1h.volume_ratio:.2f}x"
    )

    console.print()

    console.print(
        "[dim]This is a technical-analysis "
        "signal, not a guaranteed prediction.[/dim]"
    )

    console.print()