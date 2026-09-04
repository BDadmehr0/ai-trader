"""
Flask web panel — analysis dashboard, settings, data sources, backtest.

Everything the UI can change is written through the settings store, so a saved
change is picked up by the very next analysis run (no restart), and the same
values are what the CLI, the backtest and the optimizer use.

Routes
------
GET  /                      dashboard (symbol, tf, news, live refresh)
GET  /settings              full configuration page (10 groups)
GET  /backtest              backtest + walk-forward optimizer
GET  /journal               signal journal, hit-rate, calibration
GET  /api/signal            full report as JSON
GET  /api/candles           candles + chart overlays/markers
GET  /api/news              news + AI sentiment only
GET  /api/derivatives       funding / OI / order book only
GET  /api/journal           stats + calibration
GET  /api/backtest          run a backtest
POST /api/settings          validate + persist (partial payload allowed)
POST /api/settings/reset    back to defaults
POST /api/settings/import   paste a JSON config
POST /api/settings/test/news|llm|data     live probes for the settings page
POST /api/journal/evaluate  settle open signals
POST /api/backtest/optimize walk-forward parameter search
POST /api/backtest/apply    save the winning parameters
POST /api/data/upload       upload your own OHLCV CSV
POST /api/data/use          switch the active data source
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from flask import Flask, Response, jsonify, render_template, request, url_for
from werkzeug.utils import secure_filename

from analysis.calibration import report as calibration_report
from analysis.derivatives import analyze_derivatives
from analysis.indicators import add_indicators, overlay_series
from analysis.journal import evaluate_open_signals, summary as journal_summary
from analysis.live import build_signal_report
from analysis.news import analyze_news, llm_config
from config.definition import ITEMS
from config.store import (
    REPO_ROOT,
    get_settings, override_settings, reset_settings, save_settings, schema_payload,
    settings_file, validate,
)
from data import csv_source
from data.market_data import MarketData

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


# =====================================================================
# helpers
# =====================================================================

def _json_default(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if hasattr(value, "item"):                      # numpy scalar
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    if hasattr(value, "isoformat"):                  # datetime / Timestamp
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return str(value)


def safe_payload(data) -> str:
    return json.dumps(data, default=_json_default, ensure_ascii=False)


def normalize_symbol(value, settings=None) -> str:
    settings = settings or get_settings()
    raw = (value or "").strip().upper()
    if not raw:
        return settings.symbol
    base = raw.replace("_", "/").replace("-", "/").split("/")[0].strip()
    if not base:
        return settings.symbol
    if "/" in raw and raw.split("/")[1]:
        return f"{base}/{raw.split('/')[1]}"
    return f"{base}/{settings.quote}"


def _timeframe(value, market: MarketData, settings) -> str:
    text = str(value or settings.tf_base).strip().lower()
    if not re.fullmatch(r"\d+[mhdw]", text):
        text = settings.tf_mid
    supported = market.supported_timeframes()
    if text not in supported:
        # keep the request working: fall back to the closest supported timeframe
        minutes = csv_source.timeframe_minutes(text)
        text = min(supported, key=lambda tf: abs(csv_source.timeframe_minutes(tf) - minutes))
    return text


def _flag(name: str, default: bool = True) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "yes", "on")


def _chart_payload(market: MarketData, symbol: str, timeframe: str, settings, report=None) -> dict:
    """Candles + server-computed overlays for one timeframe (single fetch)."""
    frame = add_indicators(market.get_ohlcv(symbol, timeframe, settings.candle_limit), settings)

    seconds = pd.to_datetime(frame["timestamp"]).values.astype("datetime64[s]").astype("int64")
    candles = [
        {
            "time": int(stamp),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for stamp, row in zip(seconds, frame.itertuples(index=False))
    ][-int(settings.chart_candle_limit):]

    window_start = candles[0]["time"] if candles else 0
    overlays = overlay_series(frame.tail(int(settings.chart_candle_limit) + 1).reset_index(drop=True), settings)
    overlays.pop("volume", None)
    for name, points in list(overlays.items()):
        if isinstance(points, list) and points and isinstance(points[0], dict) and "time" in points[0]:
            overlays[name] = [point for point in points if point["time"] >= window_start]
    overlays["markers"] = [marker for marker in overlays.get("markers", []) if marker["time"] >= window_start]

    return {
        "symbol": symbol,
        "tf": timeframe,
        "live": bool(getattr(market, "is_live", False)),
        "source": getattr(market, "source", "exchange"),
        "candles": candles,
        "overlays": overlays,
        "setup": (report or {}).get("setup") or {},
        "levels": (report or {}).get("levels") or {},
        "signal": (report or {}).get("signal"),
        "verdict": (report or {}).get("verdict"),
        "timeframes": settings.timeframe_list(),
    }


def _form_values(payload: dict) -> dict:
    """Flatten a form/JSON body into {setting_key: raw_value}."""
    values: dict = {}
    if isinstance(payload, dict) and "values" in payload and isinstance(payload["values"], dict):
        return payload["values"]

    for key, raw in (payload or {}).items():
        if key in ("csrf", "action", "submit", "_form"):
            continue
        values[key] = raw
    return values


# =====================================================================
# app
# =====================================================================

def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

    class Provider(app.json_provider_class):
        def dumps(self, obj, **kwargs):
            kwargs.setdefault("default", _json_default)
            return super().dumps(obj, **kwargs)

    app.json = Provider(app)

    # -----------------------------------------------------------------
    # pages
    # -----------------------------------------------------------------
    @app.context_processor
    def inject_globals():
        settings = get_settings()
        return {
            "coins": settings.supported_coins,
            "settings": settings.to_dict(),
            "settings_meta": {
                "file": str(settings_file()),
                "version": "1.0",
            },
            "default_symbol": settings.symbol,
            "ui": {
                "language": settings.ui_language,
                "show_fa": settings.ui_show_persian_help,
                "refresh": settings.ui_refresh_seconds,
                "show_reasoning": settings.ui_show_reasoning,
                "overlays": {
                    "bb": settings.ui_chart_overlay_bb,
                    "vwap": settings.ui_chart_overlay_vwap,
                    "supertrend": settings.ui_chart_overlay_supertrend,
                    "ema": settings.ui_chart_overlay_ema,
                },
            },
        }

    @app.route("/")
    def dashboard():
        settings = get_settings()
        market = MarketData(settings=settings)
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        timeframe = _timeframe(request.args.get("tf"), market, settings)

        started = time.time()
        report = build_signal_report(
            market, symbol,
            settings=settings,
            include_news=_flag("news", settings.news_enabled),
            include_derivatives=_flag("derivatives", True),
            record_journal=_flag("journal", settings.journal_enabled),
        )
        chart = _chart_payload(market, symbol, timeframe, settings, report)

        return render_template(
            "dashboard.html",
            report=report,
            symbol=symbol,
            timeframe=timeframe,
            chart_data=chart,
            elapsed_ms=int((time.time() - started) * 1000),
            timeframes=settings.timeframe_list(),
        )

    @app.route("/settings")
    def settings_page():
        payload = schema_payload()
        return render_template("settings.html", schema=payload,
                               optimizable=[key for key, item in ITEMS.items() if item.optimizer])

    @app.route("/backtest")
    def backtest_page():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        result = None
        if request.args.get("run") != "0":
            market = MarketData(settings=settings)
            result = run_backtest_safe(symbol, market, settings)
        return render_template("backtest.html", result=result, symbol=symbol)

    @app.route("/journal")
    def journal_page():
        settings = get_settings()
        stats = journal_summary(settings)
        calibration = calibration_report(settings)
        records = []
        try:
            from analysis.journal import read_records

            records = read_records(settings)[::-1][:60]
        except Exception:  # noqa: BLE001
            records = []
        return render_template("journal.html", stats=stats, calibration=calibration, records=records)

    # -----------------------------------------------------------------
    # analysis APIs
    # -----------------------------------------------------------------
    @app.route("/api/signal")
    def api_signal():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        report = build_signal_report(
            MarketData(settings=settings), symbol, settings=settings,
            include_news=_flag("news", settings.news_enabled),
            include_derivatives=_flag("derivatives", settings.derivatives_enabled),
            record_journal=_flag("journal", False),
        )
        if request.args.get("full") in ("0", "false"):
            keys = ("symbol", "signal", "verdict", "confidence", "price", "scores", "setup", "news",
                    "derivatives", "gates", "updated_at", "data")
            report = {key: report.get(key) for key in keys}
        return jsonify(report)

    @app.route("/api/analysis")
    def api_analysis():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        market = MarketData(settings=settings)
        analyses = {}
        for label, timeframe in zip(settings.timeframe_labels, settings.timeframe_list()):
            frame = add_indicators(market.get_ohlcv(symbol, timeframe, settings.candle_limit), settings)
            analyses[label] = overlay_series(frame)["summary"] | {"candles": int(len(frame))}
        return jsonify({"symbol": symbol, "timeframes": analyses, "live": market.is_live})

    @app.route("/api/candles")
    def api_candles():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        market = MarketData(settings=settings)
        timeframe = _timeframe(request.args.get("tf"), market, settings)
        return jsonify(_chart_payload(market, symbol, timeframe, settings))

    @app.route("/api/news")
    def api_news():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        news = analyze_news(symbol, settings, force=_flag("refresh", False))
        return jsonify(news.to_dict())

    @app.route("/api/derivatives")
    def api_derivatives():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        market = MarketData(settings=settings)
        result = analyze_derivatives(symbol, settings, market=market, force=_flag("refresh", False))
        return jsonify(result.to_dict())

    # -----------------------------------------------------------------
    # settings APIs
    # -----------------------------------------------------------------
    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        settings = get_settings()
        if request.args.get("schema") == "0":
            return jsonify({"values": settings.to_dict()})
        return jsonify(schema_payload())

    @app.route("/api/settings", methods=["POST"])
    def api_settings_save():
        payload = _payload()
        values = _form_values(payload.get("values") if isinstance(payload.get("values"), dict) else payload)

        # checkboxes that are unchecked never appear in a form post
        for key, item in ITEMS.items():
            if item.type == "bool" and key not in values and payload.get("_form"):
                values[key] = False

        snapshot, errors = save_settings(values)
        if errors:
            return jsonify({"ok": False, "errors": errors,
                            "message": "some values were rejected — nothing was saved"}), 422
        return jsonify({
            "ok": True,
            "changed": sorted(values.keys()),
            "file": str(settings_file()),
            "values": snapshot.to_dict(),
        })

    @app.route("/api/settings/reset", methods=["POST"])
    def api_settings_reset():
        snapshot = reset_settings()
        return jsonify({"ok": True, "values": snapshot.to_dict(), "message": "settings reset to defaults"})

    @app.route("/api/settings/export")
    def api_settings_export():
        body = json.dumps(get_settings().to_dict(), indent=2, ensure_ascii=False, default=_json_default)
        return Response(body, mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="ai-trader-settings.json"'})

    @app.route("/api/settings/import", methods=["POST"])
    def api_settings_import():
        text = _payload().get("json") or request.get_data(as_text=True) or ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return jsonify({"ok": False, "errors": {"json": f"invalid json: {exc.msg}"}}), 400
        if not isinstance(data, dict):
            return jsonify({"ok": False, "errors": {"json": "expected an object"}}), 400
        data.pop("_meta", None)
        clean, errors = validate(data, strict=False)
        # a settings file usually comes from another machine: say what was skipped
        ignored = {key: "unknown setting" for key in data if key not in ITEMS}
        ignored.update(errors)
        if not clean:
            return jsonify({"ok": False, "errors": ignored or {"json": "no recognised settings"},
                            "ignored": ignored}), 422

        snapshot, save_errors = save_settings(clean)
        return jsonify({"ok": not save_errors, "applied": len(clean), "ignored": ignored,
                        "errors": save_errors, "values": snapshot.to_dict()})

    @app.route("/api/settings/test/news", methods=["POST"])
    def api_test_news():
        values = _form_values(_payload().get("values") or _payload())
        clean, _errors = validate(values, strict=False)
        settings_snapshot = get_settings()
        with override_settings(**{**clean, "news_cache_ttl": -1}):
            symbol = normalize_symbol(values.get("symbol") or settings_snapshot.symbol)
            try:
                news = analyze_news(symbol, force=True)
            except Exception as exc:  # noqa: BLE001
                return jsonify({"ok": False, "error": str(exc)}), 502
        return jsonify({"ok": news.available, "news": news.to_dict(), "applied": clean})

    @app.route("/api/settings/test/llm", methods=["POST"])
    def api_test_llm():
        values = _form_values(_payload().get("values") or _payload())
        clean, _errors = validate(values, strict=False)
        with override_settings(**clean):
            settings = get_settings()
            symbol = normalize_symbol(values.get("symbol") or settings.symbol)
            cfg = llm_config(settings, symbol)
            if cfg is None:
                return jsonify({"ok": True, "reachable": None, "detail": "engine is 'lexicon' or 'off' — no model call needed",
                                "provider": settings.news_provider})
            from analysis.news.llm import ping, score_headlines, LlmError

            status = ping(cfg)
            samples = [
                "SEC approves spot Bitcoin ETF with record inflows on day one",
                "Major exchange halted after $180M exploit; token crashes",
                "Weekly crypto digest: what moved markets this week",
            ]
            try:
                scored, stats = score_headlines(samples, cfg)
                results = [{"headline": text, "score": round(score, 3), "reason": reason, "method": method}
                           for text, (score, reason, method) in zip(samples, scored)]
            except LlmError as exc:
                return jsonify({"ok": False, "ping": status, "error": str(exc)[:400],
                                "hint": _llm_hint(settings, str(exc)),
                                "provider": settings.news_provider, "model": cfg.model,
                                "fallback": "lexicon",
                                "fallback_note": "analysis keeps working: headlines are scored by the "
                                                 "offline lexicon while the model is unreachable"}), 502
            return jsonify({"ok": True, "ping": status, "results": results, "stats": stats,
                            "provider": settings.news_provider, "model": cfg.model})

    @app.route("/api/settings/test/data", methods=["POST"])
    def api_test_data():
        values = _form_values(_payload().get("values") or _payload())
        clean, _errors = validate(values, strict=False)
        with override_settings(**clean):
            settings = get_settings()
            market = MarketData(settings=settings)
            symbol = normalize_symbol(values.get("symbol") or settings.symbol)
            out = {"symbol": symbol, "source": market.source, "live": market.is_live,
                   "describe": market.describe(), "timeframes": {}}
            try:
                for timeframe in settings.timeframe_list():
                    frame = market.get_ohlcv(symbol, timeframe, settings.candle_limit)
                    out["timeframes"][timeframe] = {
                        "rows": int(len(frame)),
                        "start": str(frame["timestamp"].iloc[0]),
                        "end": str(frame["timestamp"].iloc[-1]),
                        "last_close": float(frame["close"].iloc[-1]),
                    }
                out["ok"] = all(rows["rows"] >= 60 for rows in out["timeframes"].values())
            except Exception as exc:  # noqa: BLE001
                out["ok"] = False
                out["error"] = str(exc)[:300]

            if settings.csv_path:
                out["csv"] = csv_source.profile(settings.csv_path, settings.csv_timeframe)
            out["supported_timeframes"] = market.supported_timeframes()[:14]
        return jsonify(out)

    # -----------------------------------------------------------------
    # data source APIs
    # -----------------------------------------------------------------
    @app.route("/api/data/files")
    def api_data_files():
        return jsonify({
            "files": csv_source.list_csvs(UPLOAD_DIR),
            "current": get_settings().csv_path or None,
            "profile": csv_source.profile(get_settings().csv_path, get_settings().csv_timeframe)
            if get_settings().csv_path else None,
        })

    @app.route("/api/data/upload", methods=["POST"])
    def api_data_upload():
        file = request.files.get("file")
        if file is None or not file.filename:
            return jsonify({"ok": False, "error": "no file"}), 400

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        name = secure_filename(file.filename) or "dataset.csv"
        if not name.lower().endswith(".csv"):
            name += ".csv"
        target = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{name}"
        file.save(target)

        timeframe = (request.form.get("timeframe") or "").strip() or None
        try:
            info = csv_source.profile(target, timeframe)
        except Exception as exc:  # noqa: BLE001
            target.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": str(exc)}), 422

        if not info.get("ok"):
            target.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": info.get("error") or "unreadable file"}), 422

        relative = str(target.relative_to(UPLOAD_DIR.parent.parent))
        _snapshot, errors = save_settings({"csv_path": relative, "csv_timeframe": info["timeframe"],
                                           "data_source": "csv" if request.form.get("activate") in ("1", "true", "on")
                                           else get_settings().data_source})
        return jsonify({"ok": not errors, "file": relative, "profile": info, "errors": errors,
                        "activate_message": "active data source is now your CSV"
                        if request.form.get("activate") in ("1", "true", "on") else
                        'saved — set "Data source" to csv to use it'})

    @app.route("/api/data/use", methods=["POST"])
    def api_data_use():
        payload = _payload()
        values = {}
        if payload.get("clear"):
            values = {"data_source": "auto", "csv_path": ""}
        else:
            path = payload.get("path") or ""
            if path:
                resolved, problem = _resolve_dataset(path)
                if problem:
                    return jsonify({"ok": False, "error": problem, "path": path}), 400
                values = {"data_source": "csv", "csv_path": str(path)}
                if payload.get("timeframe"):
                    values["csv_timeframe"] = payload["timeframe"]
            elif payload.get("data_source"):
                values = {"data_source": payload["data_source"]}
        _snapshot, errors = save_settings(values)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 422
        cache_for_reset()
        return jsonify({"ok": True, "applied": values})

    # -----------------------------------------------------------------
    # journal / calibration
    # -----------------------------------------------------------------
    @app.route("/api/journal")
    def api_journal():
        settings = get_settings()
        return jsonify({
            "summary": journal_summary(settings),
            "calibration": calibration_report(settings, force=_flag("recalc", False)),
        })

    @app.route("/api/journal/evaluate", methods=["POST"])
    def api_journal_evaluate():
        settings = get_settings()
        result = evaluate_open_signals(MarketData(settings=settings), settings,
                                       force=_flag("force", False))
        return jsonify({"ok": True, **result, "summary": journal_summary(settings)})

    # -----------------------------------------------------------------
    # backtest / optimizer
    # -----------------------------------------------------------------
    @app.route("/api/backtest")
    def api_backtest():
        settings = get_settings()
        symbol = normalize_symbol(request.args.get("symbol"), settings)
        market = MarketData(settings=settings)
        result = run_backtest_safe(symbol, market, settings)
        return jsonify(result.to_dict(include_trades=_flag("trades", True)))

    @app.route("/api/backtest/optimize", methods=["POST"])
    def api_backtest_optimize():
        from backtesting import optimizer

        settings = get_settings()
        payload = _payload()
        symbol = normalize_symbol(payload.get("symbol") or request.args.get("symbol"), settings)
        trials = payload.get("trials") or payload.get("optimizer_trials")
        values = {"data_source": payload["data_source"]} if payload.get("data_source") else {}
        if trials:
            values["optimizer_trials"] = int(trials)
        if payload.get("mode"):
            values["optimizer_mode"] = payload["mode"]
        if payload.get("objective"):
            values["optimizer_objective"] = payload["objective"]
        if payload.get("ranges"):
            values["optimizer_ranges"] = payload["ranges"]

        clean, errors = validate(values, strict=True)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 422

        with override_settings(**clean):
            active = get_settings()
            result = optimizer.run(symbol, active, MarketData(settings=active))
        return jsonify(result)

    @app.route("/api/backtest/apply", methods=["POST"])
    def api_backtest_apply():
        from backtesting.optimizer import apply_best

        payload = _payload()
        params = payload.get("params") or {}
        ok, errors = apply_best(params)
        status = 200 if ok else 422
        return jsonify({"ok": ok, "errors": errors, "applied": params}), status

    # -----------------------------------------------------------------
    # misc
    # -----------------------------------------------------------------
    @app.route("/api/health")
    def api_health():
        settings = get_settings()
        market = MarketData(settings=settings)
        try:
            frame = market.get_ohlcv(settings.symbol, settings.tf_base, 120)
            rows = int(len(frame))
        except Exception as exc:  # noqa: BLE001
            rows, error = 0, str(exc)[:200]
            return jsonify({"ok": False, "rows": 0, "error": error,
                            "source": market.source, "live": market.is_live}), 502
        return jsonify({
            "ok": True,
            "rows": rows,
            "source": market.source,
            "live": market.is_live,
            "settings_file": str(settings_file()),
            "news": {"enabled": settings.news_enabled, "provider": settings.news_provider},
            "timeframes": settings.timeframe_list(),
        })

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "unknown endpoint"}), 404
        return render_template("error.html", message="page not found"), 404

    return app


# =====================================================================
# small service wrappers
# =====================================================================

def run_backtest_safe(symbol: str, market: MarketData, settings):
    from backtesting.service import run_backtest

    try:
        return run_backtest(symbol, settings, market)
    except Exception as exc:  # noqa: BLE001
        logger.exception("backtest crashed")

        class _Failed:
            ok = False
            error = str(exc)[:300]
            metrics: dict = {}
            trades: list = []
            equity: list = []
            coverage: dict = {}
            params: dict = {}
            duration_ms = 0
            initial_balance = float(settings.initial_balance)
            source = getattr(market, "source", "?")
            live = False
            symbol = symbol

            @staticmethod
            def to_dict(include_trades=True):
                return {"ok": False, "error": str(exc)[:300], "metrics": {}, "trades": [],
                        "equity": [], "coverage": {}, "params": {}, "symbol": symbol}

        return _Failed()


def cache_for_reset():
    """Drop cached candles when the data source changes."""
    from utils.cache import cache_for

    for namespace in ("ohlcv",):
        try:
            cache_for(namespace).clear()
        except OSError:
            pass


def _resolve_dataset(path) -> tuple:
    """Resolve a user-supplied CSV path and decide whether the app may read it.

    Anything inside the repository is fine (that is where uploads land). Outside
    it is refused unless the operator explicitly opts in, because the value comes
    from an HTTP request and ends up in data/settings.json — a stale or hostile
    path there is read on every analysis run.
    """
    import os

    root = REPO_ROOT.resolve()
    candidate = Path(str(path).strip()).expanduser()
    resolved = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = resolved.resolve()
    except OSError:
        return None, f"cannot read that path: {path}"
    if not resolved.exists() or not resolved.is_file():
        return None, f"no such file: {path}"
    if root not in resolved.parents and resolved != root:
        if os.environ.get("AITRADER_ALLOW_EXTERNAL_DATA", "").lower() not in ("1", "true", "yes"):
            return None, (f"{path} is outside the project folder — put the CSV in data/uploads/ "
                          "or set AITRADER_ALLOW_EXTERNAL_DATA=1 to allow it")
        if resolved.suffix.lower() not in (".csv", ".txt", ".tsv"):
            return None, "external data must be a .csv/.txt/.tsv file"
    return resolved, None


def _payload() -> dict:
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return data if isinstance(data, dict) else {}
    form = request.form.to_dict(flat=True)
    if not form and request.data:
        try:
            parsed = json.loads(request.get_data(as_text=True))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    form["_form"] = True
    return form


def _llm_hint(settings, error: str) -> str:
    lowered = error.lower()
    if settings.news_provider == "ollama":
        if "connection" in lowered or "refused" in lowered:
            return "ollama is not answering — run `ollama serve`, then `ollama pull %s`" % settings.ollama_model
        if "not found" in lowered or "404" in lowered:
            return f"model '{settings.ollama_model}' is not pulled yet — `ollama pull {settings.ollama_model}`"
        return "check `ollama list` and the url/port in settings"
    if "connection" in lowered or "refused" in lowered:
        return f"nothing is listening on {settings.openai_base_url} — start LM Studio / vLLM / llama.cpp server"
    if "401" in lowered or "api key" in lowered:
        return "the endpoint refused the api key — set openai_api_key (or AI_TRADER_OPENAI_API_KEY)"
    return "check base url, model name and api key"


__all__ = ["create_app", "normalize_symbol", "safe_payload"]
