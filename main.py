"""
AI Trader — command line entry point.

    python main.py                      # signal for the configured symbol
    python main.py signal --symbol SOL  # signal for another coin
    python main.py news                 # local news sentiment only
    python main.py backtest --plot      # MTF backtest on the active data source
    python main.py optimize --trials 20 --apply
    python main.py journal              # accuracy of the signals we recorded
    python main.py settings             # what is configured right now
    python main.py settings set entry_threshold 45
    python main.py panel                # web UI on :5000

Any of ``--symbol/--tf/--source/--csv`` temporarily overrides the saved
settings for that run only (nothing is written to data/settings.json).
"""

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.store import (
    ITEMS,
    export_settings,
    get_settings,
    override_settings,
    reset_settings,
    save_settings,
    settings_file,
    validate,
)

console = Console()


# ============================ helpers =================================
def _overrides(args) -> dict:
    """CLI flags -> settings keys (validated/coerced by the store)."""
    raw = {}
    if getattr(args, "symbol", None):
        raw["symbol"] = args.symbol.upper()
    if getattr(args, "tf", None):
        # --tf picks the *base* timeframe; mid/higher follow the same ladder
        ladder = ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
        chosen = args.tf.lower()
        if chosen not in ladder:
            console.print(f"[yellow]تایم‌فریم {chosen} را نمی‌شناسم؛ از {', '.join(ladder)} یکی را انتخاب کن.[/yellow]")
        else:
            index = ladder.index(chosen)
            picked = [ladder[i] for i in (index, index + 1, index + 3) if i < len(ladder)]
            raw["timeframes"] = ",".join(picked)
    if getattr(args, "source", None):
        raw["data_source"] = args.source
    if getattr(args, "csv", None):
        raw["csv_path"] = args.csv
        raw["data_source"] = "csv"
    if getattr(args, "no_news", False):
        raw["news_enabled"] = False
    if getattr(args, "no_derivatives", False):
        raw["derivatives_enabled"] = False
    if getattr(args, "offline", False):
        raw["data_source"] = "demo"
        raw["news_enabled"] = False
        raw["derivatives_enabled"] = False
        raw["cross_asset_enabled"] = False

    clean, errors = validate(raw, strict=False)
    for key, message in errors.items():
        console.print(f"[yellow]ignored {key}: {message}[/yellow]")
    return clean


def _verdict_markup(verdict: str) -> str:
    return {
        "BUY": "[bold green]خرید (BUY)[/bold green]",
        "SELL": "[bold red]فروش (SELL)[/bold red]",
    }.get(verdict, "[bold yellow]صبر (HOLD)[/bold yellow]")


def _price(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.4f}" if abs(number) < 10 else f"{number:,.2f}"


def _data_warning(market) -> None:
    if not market.is_live:
        console.print(f"[yellow]⚠ داده از منبع «{market.source}» است — در صورت لزوم "
                      f"`--source exchange` یا `--csv فایل.csv` را امتحان کن.[/yellow]")
    else:
        console.print(f"[dim]منبع داده: {market.describe()}[/dim]")


def _make_market(settings, market=None):
    if market is not None:
        return market
    from data.market_data import MarketData

    return MarketData(settings=settings)


# ============================ signal =================================
def cmd_signal(args, market=None):
    from analysis.live import build_signal_report

    settings = get_settings()
    market = _make_market(settings, market)

    if args.json:
        report = build_signal_report(market, settings.symbol)
        print(json.dumps({k: v for k, v in report.items() if k != "chart"}, ensure_ascii=False, indent=2, default=str))
        return 0

    console.print(f"[dim]در حال دریافت داده‌های {settings.symbol} ({market.source}) و تحلیل ...[/dim]")
    report = build_signal_report(
        market,
        settings.symbol,
        include_news=False if args.no_news else None,
        include_derivatives=False if args.no_derivatives else None,
        record_journal=False if args.no_journal else None,
    )

    price, change = report["price"], report["change_24h_pct"]
    verdict = report["verdict"]
    tone = {"BUY": "green", "SELL": "red"}.get(verdict, "yellow")

    lines = [
        f"[bold]{report['symbol']} / {settings.quote}[/bold]",
        "",
        f"[dim]قیمت[/dim]  {_price(price)}   [dim]تغییر ۲۴ ساعت[/dim]  {change:+.2f}%",
        "",
        f"نظر:  {_verdict_markup(verdict)}   [dim]اطمینان[/dim] {report['confidence']}%",
    ]
    if report.get("proposal"):
        lines.append(f"پیشنهاد نهایی: [bold]{report['proposal']}[/bold]")
    console.print(Panel("\n".join(lines), border_style=tone, expand=False))

    console.print("[bold]توضیح:[/bold] " + report["explanation"])

    if report["timeframes"]:
        table = Table(title="تحلیل چند تایم‌فریمی")
        for column in ("بازه", "روند", "نمره", "RSI", "ADX", "MACD", "حجم", "فاصله VWAP"):
            table.add_column(column)
        for tf, data in report["timeframes"].items():
            table.add_row(
                tf,
                f"{data.get('trend_fa', '')} ({data.get('trend_en', '')})",
                str(data.get("score", 0)),
                f"{data.get('rsi', 0):.1f}",
                f"{data.get('adx', 0):.1f}",
                f"{data.get('macd_histogram', 0):+.2f}",
                f"{data.get('volume_ratio', 0):.2f}x",
                f"{data.get('vwap_gap_pct', data.get('vwap_dist_pct', 0)):+.2f}%",
            )
        console.print(table)

    setup = report["setup"]
    if setup and setup.get("status") not in (None, "NO TRADE"):
        table = Table(title=f"سطوح معامله — {setup.get('signal', '')}")
        table.add_column("پارامتر")
        table.add_column("مقدار")
        rows = [
            ("وضعیت", setup.get("status")),
            ("ورود", _price(setup.get("entry"))),
            ("حد ضرر", f"{_price(setup.get('stop_loss'))}  ({setup.get('stop_distance_pct', 0)}%)"),
            ("هدف اول", f"{_price(setup.get('take_profit_1'))}  (1:{setup.get('risk_reward_1', 0)}R)"),
            ("هدف دوم", f"{_price(setup.get('take_profit_2'))}  (1:{setup.get('risk_reward_2', 0)}R)"),
            ("حجم پوزیشن", f"{setup.get('position_size', 0)} {settings.symbol}"),
            ("ریسک", f"{setup.get('risk_amount', 0):,.2f} {settings.quote} "
                     f"({settings.risk_per_trade}% از {(settings.initial_balance or 0):,.0f})"),
            ("اهرم", f"{setup.get('leverage', settings.leverage)}x"),
        ]
        for label, value in rows:
            table.add_row(label, str(value))
        console.print(table)
        for note in setup.get("notes") or []:
            console.print(f"  [dim]· {note}[/dim]")

    levels = report["levels"]
    if levels:
        table = Table(title="سطوح کلیدی")
        table.add_column("حمایت", justify="right")
        table.add_column("مقاومت", justify="right")
        table.add_row(_price(levels.get("support_1")), _price(levels.get("resistance_1")))
        table.add_row(_price(levels.get("support_2")), _price(levels.get("resistance_2")))
        console.print(table)

    gates = report.get("gates") or {}
    if gates.get("gates"):
        table = Table(title=f"فیلترهای کیفیت ستاپ ({gates.get('passed_count')}/{gates.get('total')} رد شده)")
        table.add_column("فیلتر")
        table.add_column("وضعیت")
        table.add_column("توضیح")
        for gate in gates["gates"]:
            mark = {"PASS": "[green]PASS[/green]", "FAIL": "[red]FAIL[/red]"}.get(gate["status"], "[yellow]WARN[/yellow]")
            if gate.get("blocking") and gate["status"] == "FAIL":
                mark += " [red]⛔[/red]"
            table.add_row(gate["label"], mark, gate.get("note", ""))
        console.print(table)

    news = report.get("news") or {}
    if news and news.get("status") not in (None, "", "DISABLED", "SKIPPED"):
        head = (f"احساس اخبار: [bold]{news.get('bias') or 'NEUTRAL'}[/bold] "
                f"(امتیاز {news.get('score', 0):+.0f}/100، {news.get('item_count', 0)} خبر، "
                f"موتور [bold]{news.get('provider')}[/bold]"
                + (f" / {news.get('model')}" if news.get("model") else "") + ")")
        notes = "".join(f"\n[dim]· {note}[/dim]" for note in (news.get("notes") or [])[:3])
        console.print(Panel(head + notes, title="📰 اخبار", border_style="cyan", expand=False))
        for item in (news.get("items") or [])[:5]:
            sign = "+" if item.get("score", 0) > 0.05 else "-" if item.get("score", 0) < -0.05 else "·"
            style = "green" if sign == "+" else "red" if sign == "-" else "dim"
            console.print(f"  [{style}]{sign}[/{style}] {item.get('headline')} "
                          f"[dim]({item.get('source')} · {item.get('method')})[/dim]")

    derivatives = report.get("derivatives") or {}
    if derivatives and derivatives.get("available"):
        console.print(f"[dim]وانت‌شده: فاندینگ {derivatives.get('funding_rate', 0):+.5f} · "
                      f"OI {derivatives.get('open_interest_change_pct', 0):+.1f}% · "
                      f"{derivatives.get('crowd_state', '')} · امتیاز {derivatives.get('score', 0):+.2f}[/dim]")

    if report.get("reasons"):
        console.print("[bold]دلایل:[/bold]")
        for reason in report["reasons"]:
            console.print(f"  • {reason}")

    _data_warning(market)
    console.print("[dim]این یک تحلیل تکنیکال است و توصیه مالی یا تضمین سوددهی نیست.[/dim]")
    return 0


# ============================ news ===================================
def cmd_news(args, market=None):
    from analysis.news import analyze_news

    settings = get_settings()
    symbol = args.symbol or settings.symbol
    result = analyze_news(symbol, settings, force=bool(args.json)).to_dict()

    items = result.get("items", [])[: (args.limit or 12)]
    table = Table(title=f"اخبار {symbol}")
    table.add_column("خبر")
    table.add_column("منبع")
    table.add_column("امتیاز")
    table.add_column("روش")
    for item in items:
        score = item.get("score", 0)
        table.add_row(
            item.get("headline", "")[:110],
            f"{item.get('source')} ({item.get('age_hours', 0)}h)",
            f"[{'green' if score > 0.05 else 'red' if score < -0.05 else 'white'}]{score:+.2f}[/]",
            item.get("method", ""),
        )
    if items:
        console.print(table)
    else:
        console.print(f"[dim]هیچ خبری برای نمایش نیست (status={result.get('status')})[/dim]")

    summary = Table(show_header=False)
    summary.add_row("status", result.get("status"))
    summary.add_row("engine", f"{result.get('provider')}" + (f" · {result.get('model')}" if result.get("model") else ""))
    summary.add_row("sentiment", f"{result.get('sentiment', 0):+.3f} → {result.get('bias')}")
    summary.add_row("confidence", f"{result.get('confidence', 0)}% (available={result.get('available')})")
    summary.add_row("direction", f"{result.get('bullish_count', 0)} مثبت / {result.get('bearish_count', 0)} منفی از {result.get('item_count', 0)}")
    if result.get("fear_greed"):
        fg = result["fear_greed"]
        summary.add_row("fear&greed", f"{fg.get('value')} ({fg.get('label')})")
    veto = result.get("veto") or {}
    if veto.get("triggered"):
        summary.add_row("[red]veto[/red]", f"[red]{veto.get('note')}[/red]")
    console.print(summary)

    for note in result.get("notes", []):
        console.print(f"[yellow]· {note}[/yellow]")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


# ============================ backtest ===============================
def cmd_backtest(args, market=None):
    from backtesting.service import run_backtest

    settings = get_settings()
    market = _make_market(settings, market)

    console.print(f"[dim]در حال ساخت داده و اجرای بک‌تست روی {settings.symbol} "
                  f"({market.source}) با {settings.backtest_candles} کندل ...[/dim]")
    result = run_backtest(settings.symbol, settings, market)

    if not result.ok:
        console.print(f"[red]بک‌تست انجام نشد: {result.error}[/red]")
        return 1

    from reports.backtest_report import print_backtest_report

    print_backtest_report(result.metrics)

    table = Table(title="جزئیات")
    for column in ("متریک", "مقدار"):
        table.add_column(column)
    for key in ("average_pnl", "avg_holding_candles", "sortino", "recovery_factor", "sharpe",
                "expectancy", "max_consecutive_losses", "net_profit", "trailing_exits",
                "avg_win", "avg_loss"):
        if key in result.metrics:
            table.add_row(key, f"{result.metrics[key]:.3f}" if isinstance(result.metrics[key], float) else str(result.metrics[key]))
    if result.metrics.get("exit_reasons"):
        table.add_row("exit reasons", ", ".join(f"{k}:{v}" for k, v in result.metrics["exit_reasons"].items()))
    table.add_row("data", f"{result.source} · {result.coverage.get('rows', 0)} candles · "
                          f"{result.coverage.get('start', '')} → {result.coverage.get('end', '')}")
    console.print(table)

    if args.export:
        from backtesting.export import export_trades

        export_trades(result.trades, args.export)
    if args.plot:
        from reports.charts import plot_equity_curve

        path = plot_equity_curve(result.equity, filename=args.plot,
                                  title=f"{result.symbol} equity — {result.source}")
        if path:
            console.print(f"[dim]نمودار ذخیره شد: {path}[/dim]")

    _data_warning(market)
    return 0


# ============================ optimizer ==============================
def cmd_optimize(args, market=None):
    from backtesting.optimizer import run as run_optimizer

    settings = get_settings()
    market = _make_market(settings, market)

    console.print(f"[dim]جست‌وجوی پارامتر ({args.trials or settings.optimizer_trials} حالت) با split آموزش/آزمون ...[/dim]")
    result = run_optimizer(settings.symbol, settings, market, limit=args.trials or settings.optimizer_trials)

    if not result.get("ok"):
        console.print(f"[red]بهینه‌سازی بی‌نتیجه: {result.get('error')}[/red]")
        return 1

    table = Table(title=f"بهترین حالت‌ها — هدف {result['objective']} · {len(result['trials'])} تست"
                  f" · {result['rows']} کندل")
    for column in ("#", "پارامترها", "نمره train", "نمره test", "trades", "win%", "بازده test", "DD test"):
        table.add_column(column)
    for index, trial in enumerate(result["trials"][: args.limit_rows or 8], start=1):
        params = " ".join(f"{k}={v}" for k, v in trial["params"].items())
        train, test = trial["train"], trial["test"]
        table.add_row(
            str(index),
            params[:90],
            f"{trial['train_objective']:.1f}",
            f"{trial['test_objective']:.1f}" if trial["test_objective"] > -1e8 else "n/a",
            f"{train.get('total_trades', 0)}/{test.get('total_trades', 0)}",
            f"{train.get('win_rate', 0):.0f}%",
            f"{test.get('total_return', 0):+.2f}%",
            f"{test.get('max_drawdown', 0):.2f}%",
        )
    console.print(table)
    console.print(f"[dim]rows train/test: {result['train_rows']}/{result['test_rows']} · "
                  f"overfit gap {result.get('overfit_gap', '—')} · منبع {result['source']}[/dim]")
    if abs(result.get("overfit_gap") or 0) > 40:
        console.print("[yellow]اختلاف زیاد train/test یعنی بیش‌برازش؛ حالت‌های میانی را امتحان کن.[/yellow]")

    best = result.get("best") or {}
    if args.apply and best.get("params"):
        from backtesting.optimizer import apply_best

        saved, errors = apply_best(best["params"], settings)
        if saved:
            console.print(f"[green]بهترین پارامترها ذخیره شد در {settings_file()}[/green]")
        for key, message in errors.items():
            console.print(f"[yellow]{key}: {message}[/yellow]")
    elif best.get("params"):
        console.print("[dim]برای ذخیره بهترین حالت: [/dim][bold]--apply[/bold]")
    return 0


# ============================ journal ================================
def cmd_journal(args, market=None):
    from analysis import journal
    from analysis.calibration import report as calibration_report

    settings = get_settings()
    if args.evaluate:
        outcome = journal.evaluate_open_signals(_make_market(settings))
        console.print(f"[dim]ارزیابی: {outcome['evaluated']} بسته شد، {outcome['pending']} در انتظار، "
                      f"{outcome['total']} رکورد کل[/dim]")
        for error in outcome.get("errors", []):
            console.print(f"[yellow]{error}[/yellow]")

    stats = journal.summary(settings)
    console.print(Panel.fit(
        f"رکوردها: {stats['records']} · ارزیابی‌شده: {stats['evaluated']} · باز: {stats['pending']}\n"
        f"win rate: [bold]{stats['win_rate'] if stats['win_rate'] is not None else '—'}[/bold]% · "
        f"میانگین R: [bold]{stats['avg_r'] if stats['avg_r'] is not None else '—'}[/bold] · "
        f"expectancy: {stats['expectancy'] if stats['expectancy'] is not None else '—'}",
        title="ژورنال سیگنال", border_style="cyan"))
    if stats.get("by_symbol"):
        table = Table(title="دقت به تفکیک نماد")
        for column in ("نماد", "تعداد", "میانگین R"):
            table.add_column(column)
        for symbol, row in stats["by_symbol"].items():
            table.add_row(symbol, str(row["trades"]), str(row["avg_r"]))
        console.print(table)
    if stats.get("by_confidence"):
        table = Table(title="دقت به تفکیک اطمینان")
        for column in ("بازه", "تعداد", "win%", "میانگین R"):
            table.add_column(column)
        for bucket, row in stats["by_confidence"].items():
            table.add_row(bucket, str(row["trades"]), str(row["win_rate"]), str(row["avg_r"]))
        console.print(table)

    calibration = calibration_report(settings, force=True)
    table = Table(title=f"کالیبراسیون وزن‌ها ({calibration['mode']})")
    for column in ("کامپوننت", "وزن پایه", "ضریب", "وزن مؤثر", "IC", "نمونه"):
        table.add_column(column)
    for name, weight in calibration["base_weights"].items():
        row = calibration["components"].get(name, {})
        table.add_row(name, f"{weight:.2f}", f"{calibration['multipliers'].get(name, 1.0):.3f}",
                      f"{calibration['effective_weights'].get(name, weight):.2f}",
                      f"{row.get('ic', 0):+.3f}" if row else "—", str(row.get("samples", 0)))
    console.print(table)
    if not calibration["meta"].get("active"):
        console.print(f"[dim]{calibration['meta'].get('note', '')}[/dim]")
    console.print(f"[dim]فایل: {stats['path']}[/dim]")
    return 0


# ============================ settings ===============================
def cmd_settings(args):
    action = args.action or "show"

    if action == "path":
        print(settings_file())
        return 0

    if action == "reset":
        reset_settings()
        console.print(f"[green]تنظیمات به حالت پیش‌فرض برگشت ({settings_file()} حذف شد)[/green]")
        return 0

    if action == "export":
        text = export_settings()
        if args.file:
            with open(args.file, "w", encoding="utf-8") as handle:
                handle.write(text)
            console.print(f"[green]written {args.file}[/green]")
        else:
            print(text)
        return 0

    if action == "import":
        with open(args.file, encoding="utf-8") as handle:
            payload = json.load(handle)
        settings, errors = save_settings(payload)
        console.print(f"[green]{len(payload)} کلید خوانده شد، {len(settings.to_dict())} مؤثر[/green]")
        for key, message in errors.items():
            console.print(f"[yellow]{key}: {message}[/yellow]")
        return 0

    if action == "set":
        values, errors = validate({args.key: args.value}, strict=True)
        if errors:
            for key, message in errors.items():
                console.print(f"[red]{key}: {message}[/red]")
            console.print("[dim]مقادیر مجاز را با `settings show --all` یا در صفحه تنظیمات ببین.[/dim]")
            return 2
        settings, errors = save_settings(values)
        for key, value in values.items():
            console.print(f"[green]{key} = {value}[/green] [dim]({ITEMS[key].label})[/dim]")
        for key, message in errors.items():
            console.print(f"[yellow]{key}: {message}[/yellow]")
        return 0

    if action == "get":
        settings = get_settings()
        item = ITEMS.get(args.key)
        if item is None:
            console.print(f"[red]کلید ناشناخته: {args.key}[/red]")
            return 2
        print(f"{settings.get(args.key)}")
        return 0

    settings = get_settings()
    table = Table(title=f"تنظیمات — {settings_file()}")
    for column in ("کلید", "مقدار", "پیش‌فرض", "توضیح"):
        table.add_column(column)

    for key, item in ITEMS.items():
        value = settings.get(key)
        changed = value != item.default
        if not args.all and not changed:
            continue
        display = value if not isinstance(value, (list, dict)) else json.dumps(value, ensure_ascii=False)
        if item.type == "secret":
            display = "•" * 8 if value else "(empty)"
        table.add_row(
            key,
            f"[bold cyan]{str(display)[:60]}[/bold cyan]" if changed else str(display)[:60],
            str(item.default)[:40] if changed else "",
            (item.help or item.label)[:60],
        )
    if not table.rows:
        console.print(f"[green]هیچ تنظیمی تغییر نکرده — همه روی پیش‌فرض هستند[/green] [dim]({settings_file()})[/dim]")
        if not args.all:
            console.print("[dim]همه را با `--all` ببین، یا در وب‌پنل صفحه Settings.[/dim]")
        return 0
    console.print(table)
    console.print(f"[dim]فایل: {settings_file()} · برای ویرایش: وب‌پنل ← Settings[/dim]")
    return 0


# ============================ web ====================================
def cmd_panel(args):
    from webapp.app import create_app

    app = create_app()
    console.print(f"[green]وب‌پنل روی http://{args.host}:{args.port} اجرا شد — "
                  f"بخش Settings برای تنظیم دقیق و بارگذاری CSV داده خودت.[/green]")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


# ============================ parser =================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-trader",
        description="AI Trader — تحلیل تکنیکال + اخبار با مدل محلی + تنظیمات کامل",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command", nargs="?", default="signal",
                        choices=["signal", "news", "backtest", "optimize", "journal", "settings", "panel", "web"],
                        help="signal (پیش‌فرض) | news | backtest | optimize | journal | settings | panel")
    parser.add_argument("--symbol", help="نماد (مثلاً BTC، ETH، SOL)")
    parser.add_argument("--tf", help="تایم‌فریم پایه (15m/1h/4h)")
    parser.add_argument("--source", choices=["auto", "exchange", "csv", "demo"], help="منبع داده")
    parser.add_argument("--csv", help="مسیر فایل CSV داده خودت (OHLCV)")
    parser.add_argument("--offline", action="store_true", help="بدون شبکه: داده دمو + بدون اخبار/وانت‌شده")
    parser.add_argument("--no-news", action="store_true", help="در این اجرا اخبار را نادیده بگیر")
    parser.add_argument("--no-derivatives", action="store_true", help="داده‌های فیوترز را نادیده بگیر")
    parser.add_argument("--json", action="store_true", help="خروجی JSON")

    parser.add_argument("--limit", type=int, help="تعداد ردیف (news)")
    parser.add_argument("--limit-rows", type=int, help="تعداد ردیف جدول (optimize)")
    parser.add_argument("--trials", type=int, help="تعداد حالت‌های بهینه‌ساز")
    parser.add_argument("--apply", action="store_true", help="بهترین حالت را ذخیره کن")
    parser.add_argument("--evaluate", action="store_true", help="سیگنال‌های باز را ببند (journal)")
    parser.add_argument("--export", metavar="FILE", help="فایل CSV برای خروجی معامله‌ها")
    parser.add_argument("--plot", nargs="?", const="equity_curve.png", metavar="PNG", help="ذخیره نمودار equity")
    parser.add_argument("--all", action="store_true", help="نمایش همه تنظیمات")
    parser.add_argument("--port", type=int, default=5000, help="پورت وب‌پنل")
    parser.add_argument("--host", default="0.0.0.0", help="هاست وب‌پنل")

    # settings <action> [key] [value]
    parser.add_argument("action", nargs="?", default=None,
                        choices=["show", "get", "set", "reset", "export", "import", "path"], help="کنشِ settings")
    parser.add_argument("key", nargs="?", default=None, help="کلید تنظیم")
    parser.add_argument("value", nargs="?", default=None, help="مقدار جدید")
    parser.add_argument("--file", help="فایل ورودی/خروجی settings")
    parser.add_argument("--no-journal", action="store_true", help="این اجرا را در ژورنال ثبت نکن")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging_setup()

    overrides = _overrides(args)
    with override_settings(**overrides):
        if args.command in ("panel", "web"):
            return cmd_panel(args)
        if args.command == "settings":
            return cmd_settings(args)
        if args.command == "news":
            return cmd_news(args)
        if args.command == "backtest":
            return cmd_backtest(args)
        if args.command == "optimize":
            return cmd_optimize(args)
        if args.command == "journal":
            return cmd_journal(args)
        return cmd_signal(args, market=None)


def logging_setup():
    """INFO for our own modules, WARNING for http libs; AI_TRADER_LOG overrides."""
    import logging
    import os

    level = getattr(logging, os.environ.get("AI_TRADER_LOG", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for name in ("ai-trader", "analysis", "config", "data", "backtesting", "webapp", "utils"):
        logging.getLogger(name).setLevel(level)


if __name__ == "__main__":
    sys.exit(main())
