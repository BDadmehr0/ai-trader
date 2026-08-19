import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from analysis.live import build_signal_report
from data.market_data import MarketData
from config.settings import SYMBOL

console = Console()


def _verdict_style(verdict):
    if verdict == "BUY":
        return "[bold green]خرید  (BUY)[/bold green]"
    if verdict == "SELL":
        return "[bold red]فروش  (SELL)[/bold red]"
    return "[bold yellow]صبر  (HOLD)[/bold yellow]"


def cmd_signal():
    """Default command: fetch latest data and print a simple BUY/SELL signal."""
    console.print(f"[dim]در حال دریافت داده‌های {SYMBOL} ...[/dim]")

    market = MarketData()
    report = build_signal_report(market)

    price = report["price"]
    change = report["change_24h_pct"]

    console.print()
    console.print(
        Panel.fit(
            Text.from_markup(
                f"[bold]BTC / USDT[/bold]\n\n"
                f"[dim]قیمت فعلی[/dim]  {price:,.2f}  "
                f"({change:+.2f}% در ۲۴ ساعت)\n\n"
                f"پیشنهاد:  {_verdict_style(report['verdict'])}\n\n"
                f"اطمینان: {report['confidence']}%"
            ),
            border_style="cyan",
        )
    )

    console.print()
    console.print("[bold]توضیح ساده:[/bold]")
    console.print(report["explanation"])
    console.print()

    # Timeframe overview table
    table = Table(title="تحلیل چارچوب‌های زمانی")
    table.add_column("بازه")
    table.add_column("روند")
    table.add_column("نمره")
    table.add_column("RSI")
    table.add_column("EMA20")
    table.add_column("EMA50")
    table.add_column("MACD")
    table.add_column("حجم")

    for tf, data in report["timeframes"].items():
        table.add_row(
            tf,
            f"{data['trend_fa']} ({data['trend_en']})",
            str(data["score"]),
            f"{data['rsi']:.1f}",
            f"{data['ema20']:,.0f}",
            f"{data['ema50']:,.0f}",
            f"{data['macd_histogram']:+.2f}",
            f"{data['volume_ratio']:.2f}x",
        )

    console.print(table)

    if report["signal"] != "WAIT":
        s = report["setup"]
        setup_table = Table(title="سطوح معاملاتی")
        setup_table.add_column("پارامتر")
        setup_table.add_column("قیمت")
        setup_table.add_row("ورود (Entry)", f"{s['entry']:,.0f}")
        setup_table.add_row("حد ضرر (Stop Loss)", f"{s['stop_loss']:,.0f}")
        setup_table.add_row("هدف اول (TP1)", f"{s['take_profit_1']:,.0f}")
        setup_table.add_row("هدف دوم (TP2)", f"{s['take_profit_2']:,.0f}")
        setup_table.add_row("نسبت ریسک به بازده TP1", f"1:{s['risk_reward_1']:.1f}")
        console.print(setup_table)

    lv = report["levels"]
    levels_table = Table(title="سطوح حمایت و مقاومت")
    levels_table.add_column("سطح")
    levels_table.add_column("قیمت")
    levels_table.add_row("حمایت ۱", f"{lv['support_1']:,.0f}")
    levels_table.add_row("حمایت ۲", f"{lv['support_2']:,.0f}")
    levels_table.add_row("مقاومت ۱", f"{lv['resistance_1']:,.0f}")
    levels_table.add_row("مقاومت ۲", f"{lv['resistance_2']:,.0f}")
    console.print(levels_table)

    console.print()
    console.print("[bold]دلایل:[/bold]")
    for reason in report["reasons"]:
        console.print(f"  • {reason}")

    console.print()
    if not report["live"]:
        console.print(
            "[yellow]⚠ از داده‌ی نمایشی (آفلاین) استفاده شد — "
            "این اعداد واقعی نیستند.[/yellow]"
        )
    console.print("[dim]این یک تحلیل تکنیکال است و تضمین سوددهی ندارد.[/dim]")


def cmd_backtest():
    """Run the historical multi-timeframe backtest (existing logic)."""
    from data.market_data import MarketData
    from analysis.indicators import add_indicators
    from backtesting.mtf import prepare_mtf_data
    from backtesting.engine import BacktestEngine
    from backtesting.metrics import calculate_metrics
    from backtesting.export import export_trades
    from reports.charts import plot_equity_curve
    from reports.backtest_report import print_backtest_report
    from config.settings import CANDLE_LIMIT, INITIAL_BALANCE

    market = MarketData()

    df_15m = add_indicators(market.get_ohlcv(SYMBOL, "15m", CANDLE_LIMIT))
    df_1h = add_indicators(market.get_ohlcv(SYMBOL, "1h", CANDLE_LIMIT))
    df_4h = add_indicators(market.get_ohlcv(SYMBOL, "4h", CANDLE_LIMIT))

    df = prepare_mtf_data(df_15m, df_1h, df_4h)

    engine = BacktestEngine(INITIAL_BALANCE)
    trades = engine.run(df)
    metrics = calculate_metrics(trades, engine.equity_curve, INITIAL_BALANCE)

    if not metrics:
        console.print("[yellow]هیچ معامله‌ای در بازه‌ی داده‌ها یافت نشد.[/yellow]")
    else:
        print_backtest_report(metrics)
        export_trades(trades, "trades.csv")
        plot_equity_curve(engine.equity_curve)

    if not market.is_live:
        console.print(
            "[yellow]⚠ از داده‌ی نمایشی (آفلاین) استفاده شد — "
            "این اعداد واقعی نیستند.[/yellow]"
        )


def cmd_panel(port, host):
    from webapp.app import create_app

    app = create_app()
    console.print(f"[green]وب‌پنل روی http://{host}:{port} اجرا شد.[/green]")
    app.run(host=host, port=port, debug=False, threaded=True)


def main():
    parser = argparse.ArgumentParser(
        description="AI BTC Trader — سیگنال خرید/فروش لحظه‌ای بیت‌کوین"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="signal",
        choices=["signal", "backtest", "panel", "web"],
        help="signal (پیش‌فرض) | backtest | panel",
    )
    parser.add_argument("--port", type=int, default=5000, help="پورت وب‌پنل")
    parser.add_argument("--host", default="0.0.0.0", help="هوست وب‌پنل")

    args = parser.parse_args()

    if args.command in ("panel", "web"):
        cmd_panel(args.port, args.host)
    elif args.command == "backtest":
        cmd_backtest()
    else:
        cmd_signal()


if __name__ == "__main__":
    sys.exit(main())
