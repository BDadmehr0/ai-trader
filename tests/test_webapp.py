"""Web panel: pages, JSON APIs, the settings round-trip and CSV upload.

Everything here runs against a temporary settings file and the offline demo
source — no exchange, no news network, no Ollama.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tests.support import isolated_cache

BASE_SETTINGS = {
    "data_source": "demo",
    "news_enabled": False,
    "derivatives_enabled": False,
    "cross_asset_enabled": False,
    "journal_enabled": False,
    "cache_minutes": 0,
    "candle_limit": 200,
    "chart_candle_limit": 120,
    "backtest_candles": 300,
    "symbol": "BTC/USDT",
    "ui_refresh_seconds": 0,
}


@contextmanager
def panel(settings=None):
    """A Flask test client wired to a throw-away settings file."""
    import importlib

    folder = Path(tempfile.mkdtemp(prefix="aitrader-web-"))
    payload = {**BASE_SETTINGS, **(settings or {})}
    (folder / "settings.json").write_text(json.dumps(payload), encoding="utf-8")

    saved = os.environ.get("AITRADER_SETTINGS_FILE")
    os.environ["AITRADER_SETTINGS_FILE"] = str(folder / "settings.json")
    try:
        from config.store import STORE, reload_settings

        reload_settings()
        webapp = importlib.import_module("webapp.app")
        app = webapp.create_app()
        app.config["TESTING"] = True
        yield app.test_client(), folder
    finally:
        if saved is None:
            os.environ.pop("AITRADER_SETTINGS_FILE", None)
        else:
            os.environ["AITRADER_SETTINGS_FILE"] = saved
        try:
            STORE.reload()
        except Exception:  # noqa: BLE001
            pass


def _drop_upload(relative: str) -> None:
    """Remove a CSV a test uploaded into the repo's data/uploads folder."""
    from config.store import REPO_ROOT

    try:
        (REPO_ROOT / relative).unlink()
    except OSError:
        pass


def values_of(client) -> dict:
    return client.get("/api/settings?schema=0").get_json()["values"]


def demo_csv(rows: int = 200) -> bytes:
    rng = np.random.default_rng(2)
    close = 50 + np.cumsum(rng.normal(0.02, 0.3, rows))
    open_ = np.concatenate([[50.0], close[:-1]])
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2026-03-01", periods=rows, freq="15min", tz="UTC")
        .strftime("%Y-%m-%d %H:%M:%S"),
        "open": open_,
        "high": np.maximum(open_, close) + 0.2,
        "low": np.minimum(open_, close) - 0.2,
        "close": close,
        "volume": np.abs(rng.normal(700, 90, rows)),
    })
    return frame.to_csv(index=False).encode("utf-8")


class PageTests(unittest.TestCase):
    def test_every_page_renders(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            for path, marker in (("/", "priceChart"), ("/settings", "settingsForm"),
                                 ("/backtest", "Backtest"), ("/journal", "journal")):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn(marker, response.get_data(as_text=True), path)

    def test_unknown_path_gets_the_styled_page(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.get("/definitely-not-a-route")
            self.assertEqual(response.status_code, 404)
            self.assertIn("Not found", response.get_data(as_text=True))
            api = client.get("/api/nope")
            self.assertEqual(api.status_code, 404)
            self.assertFalse(api.get_json()["ok"])

    def test_globals_reach_the_templates(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            html = client.get("/").get_data(as_text=True)
        self.assertIn("AI_TRADER_COINS", html)          # coin switcher list
        self.assertIn("AI_TRADER_CHART", html)          # chart payload
        self.assertIn("DEMO", html.upper())             # data-mode badge
        self.assertIn("engine-", html)                  # news engine badge

    def test_symbol_and_timeframe_query_parameters_work(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            html = client.get("/?symbol=SOL&tf=4h").get_data(as_text=True)
        payload = embedded_chart(html)
        self.assertEqual(payload["symbol"], "SOL/USDT")      # normalized with the quote
        self.assertEqual(payload["tf"], "4h")                 # requested window used
        self.assertEqual(payload["source"], "demo")
        times = [row["time"] for row in payload["candles"]]
        self.assertGreater(times[-1] - times[-2], 3600)       # bars really are 4h apart

    def test_dashboard_embeds_the_overlay_payload_the_chart_needs(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            html = client.get("/").get_data(as_text=True)
        payload = embedded_chart(html)
        for key in ("candles", "overlays", "levels", "setup", "signal", "verdict", "timeframes",
                    "symbol", "tf", "source", "live"):
            self.assertIn(key, payload, key)
        self.assertTrue(payload["candles"])
        for candle in payload["candles"]:
            self.assertEqual(sorted(candle), ["close", "high", "low", "open", "time", "volume"])
        for series in ("emaFast", "rsi", "vwap", "adx", "macdHist", "bbUpper"):
            self.assertIn(series, payload["overlays"])
        self.assertTrue(all(isinstance(point["time"], int) for point in payload["overlays"]["rsi"]))
        for marker in payload["overlays"]["markers"]:
            self.assertEqual(sorted(marker), ["color", "position", "shape", "text", "time"])
        self.assertGreater(abs(payload["overlays"]["summary"]["rsi"]), 0)


def embedded_chart(html: str) -> dict:
    start = html.index("window.AI_TRADER_CHART = ") + len("window.AI_TRADER_CHART = ")
    return json.loads(html[start:html.index(";</script>", start)])


class ApiTests(unittest.TestCase):
    def test_health(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            data = client.get("/api/health").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "demo")
        self.assertFalse(data["live"])
        self.assertGreaterEqual(data["rows"], 100)
        self.assertEqual(data["timeframes"], ["15m", "1h", "4h"])
        self.assertFalse(data["news"]["enabled"])
        self.assertEqual(data["settings_file"], str(folder / "settings.json"))

    def test_signal_endpoint_returns_the_full_report(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/signal?symbol=ETH").get_json()
        for key in ("symbol", "signal", "verdict", "confidence", "price", "explanation", "reasons",
                    "factors", "timeframes", "levels", "setup", "scores", "gates", "news",
                    "derivatives", "cross_asset", "data", "settings", "updated_at"):
            self.assertIn(key, data, key)
        self.assertEqual(data["symbol"], "ETH/USDT")
        self.assertIn(data["signal"], ("LONG", "SHORT", "WAIT", "NO_TRADE"))
        self.assertIn(data["verdict"], ("BUY", "SELL", "HOLD"))
        self.assertGreater(data["price"], 0)
        self.assertTrue(data["explanation"])
        self.assertEqual(data["data"]["source"], "demo")
        self.assertIn("fetch_errors", data["data"])
        self.assertTrue(data["chart"])
        self.assertTrue(data["settings"])

        breakdown = data["scores"]["breakdown"]
        self.assertTrue(breakdown)
        for component in breakdown:
            self.assertEqual(sorted(component), ["available", "base_weight", "contribution",
                                                 "direction", "label", "name", "note", "score",
                                                 "weight"])
        self.assertTrue(any(row["name"] == "news" and not row["available"] for row in breakdown))
        self.assertEqual(data["news"]["status"], "DISABLED")
        self.assertFalse(data["derivatives"]["available"])
        gates = data["gates"]["gates"]
        if data["proposal"] not in ("LONG", "SHORT"):
            self.assertEqual(gates, [])                          # nothing to check on the fence
        else:
            self.assertEqual(gates[0]["key"], "confidence")
        for gate in gates:
            self.assertIn(gate["status"], ("PASS", "FAIL", "SKIP"))
        self.assertEqual(len(data["timeframes"]), 3)
        for row in data["timeframes"].values():
            self.assertIn("trend", row)
            self.assertIn("rsi", row)

    def test_signal_endpoint_can_be_asked_for_the_slim_version(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/signal?full=0").get_json()
        self.assertNotIn("explanation", data)
        self.assertNotIn("chart", data)
        self.assertIn("signal", data)
        self.assertIn("scores", data)
        self.assertIn("updated_at", data)

    def test_multi_timeframe_analysis_endpoint(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/analysis?symbol=ETH").get_json()
        self.assertEqual(data["symbol"], "ETH/USDT")
        self.assertFalse(data["live"])
        self.assertEqual([k.upper() for k in data["timeframes"]], ["15M", "1H", "4H"])
        for summary in data["timeframes"].values():
            for key in ("rsi", "adx", "atr_pct", "volume_ratio", "candles"):
                self.assertIn(key, summary)
            self.assertGreaterEqual(summary["candles"], 60)

    def test_candles_endpoint_shape(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/candles?symbol=SOL&tf=1h").get_json()
        self.assertEqual(data["tf"], "1h")
        self.assertEqual(data["source"], "demo")
        self.assertGreater(len(data["candles"]), 20)
        self.assertLessEqual(len(data["candles"]), 120)          # chart_candle_limit
        self.assertIn("emaFast", data["overlays"])
        self.assertTrue(all(point["time"] >= data["candles"][0]["time"]
                            for point in data["overlays"]["rsi"]))
        json.dumps(data)

    def test_candles_rejects_an_unknown_timeframe_gently(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/candles?symbol=SOL&tf=7y").get_json()
        self.assertGreater(len(data["candles"]), 0)              # snapped to a supported window
        self.assertIn(data["tf"], data["timeframes"])

    def test_news_endpoint_reports_the_disabled_state(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/news?symbol=BTC").get_json()
        self.assertEqual(data["status"], "DISABLED")
        self.assertFalse(data["available"])
        self.assertEqual(data["items"], [])
        self.assertIn("veto", data)

    def test_derivatives_endpoint_degrades_instead_of_failing(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.get("/api/derivatives?symbol=BTC")
            data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["available"])
        self.assertIn(data["status"], ("DISABLED", "NO_DATA", "OFFLINE", "ERROR"))
        self.assertIn("score", data)

    def test_backtest_endpoint_and_trades(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            full = client.get("/api/backtest?symbol=BTC").get_json()
            slim = client.get("/api/backtest?symbol=BTC&trades=0").get_json()
        self.assertTrue(full["ok"], full.get("error"))
        self.assertEqual(full["source"], "demo")
        self.assertIn("total_trades", full["metrics"])
        self.assertIsInstance(full["trades"], list)
        for trade in full["trades"]:
            self.assertIn("entry_time", trade)
        self.assertTrue(all(isinstance(row["time"], int) for row in full["equity"]))
        self.assertEqual(slim["trades"], [])                  # ?trades=0 skips the payload
        self.assertGreater(len(full["trades"]), 0)
        self.assertIn("metrics", slim)
        self.assertEqual(slim["metrics"]["total_trades"], full["metrics"]["total_trades"])

    def test_journal_endpoint(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/journal").get_json()
        self.assertEqual(data["summary"]["records"], 0)          # journaling off in these tests
        self.assertIsNone(data["summary"]["win_rate"])
        self.assertIn("meta", data["calibration"])
        self.assertIn("effective_weights", data["calibration"])

    def test_journal_evaluate_endpoint(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.post("/api/journal/evaluate?force=1").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["evaluated"], 0)
        self.assertIn("summary", data)


class SettingsApiTests(unittest.TestCase):
    def test_get_returns_the_schema_for_every_group(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/settings").get_json()
        groups = {group["id"] for group in data["groups"]}
        for expected in ("data", "indicators", "strategy", "scoring", "news", "derivatives",
                         "risk", "journal", "backtest", "ui"):
            self.assertIn(expected, groups)
        news = next(g for g in data["groups"] if g["id"] == "news")
        keys = {item["key"] for item in news["items"]}
        self.assertIn("news_provider", keys)
        self.assertIn("ollama_model", keys)
        provider = next(i for i in news["items"] if i["key"] == "news_provider")
        self.assertEqual(provider["type"], "enum")
        self.assertIn("lexicon", provider["choices"])
        self.assertIn("ollama", provider["choices"])
        self.assertTrue(provider["help"])                        # Persian help text for every field
        self.assertIn("rsi_period", data["widgets"])
        self.assertTrue(data["file_exists"])
        self.assertTrue(data["file"].endswith("settings.json"))
        self.assertEqual(data["errors"], {})
        self.assertIn("timeframes", {i["key"] for g in data["groups"] for i in g["items"]})

    def test_every_setting_is_editable_from_the_page(self):
        from config.definition import ITEMS, ui_groups

        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.get("/api/settings").get_json()
        shown = {item["key"] for group in data["groups"] for item in group["items"]}
        self.assertEqual(shown, set(ITEMS))
        self.assertEqual(len(ui_groups()), len(data["groups"]))

    def test_post_saves_and_the_value_is_used_by_the_pipeline(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            response = client.post("/api/settings", json={"rsi_period": 7, "entry_threshold": 21.0})
            saved = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(saved["ok"])
            self.assertEqual(set(saved["changed"]), {"rsi_period", "entry_threshold"})

            written = json.loads((folder / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(written["rsi_period"], 7)
            self.assertEqual(written["entry_threshold"], 21.0)

            # the running pipeline uses it, and the page marks the field as changed
            signal = client.get("/api/signal").get_json()
            self.assertAlmostEqual(sum(signal["scores"]["weights"].values()), 100.0, places=6)
            self.assertEqual(values_of(client)["entry_threshold"], 21.0)
            schema = client.get("/api/settings").get_json()
            self.assertEqual(schema["widgets"]["rsi_period"], 7)
            flags = {item["key"]: item["is_default"]
                     for group in schema["groups"] for item in group["items"]}
            self.assertFalse(flags["rsi_period"], "changed field must not look like the default")
            self.assertTrue(flags["ema_fast"])

            reset = client.post("/api/settings/reset", json={}).get_json()
            self.assertEqual(reset["values"]["rsi_period"], 14)
            self.assertFalse((folder / "settings.json").exists())

    def test_invalid_values_are_refused_with_field_errors(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            response = client.post("/api/settings", json={"rsi_period": 9999, "news_provider": "gpt-9"})
            data = response.get_json()
            self.assertEqual(response.status_code, 422)
            self.assertFalse(data["ok"])
            self.assertIn("rsi_period", data["errors"])
            self.assertIn("news_provider", data["errors"])
            self.assertTrue(data["message"])
            written = json.loads((folder / "settings.json").read_text(encoding="utf-8"))
            self.assertNotIn("rsi_period", written)                   # nothing partially written

    def test_unknown_keys_are_reported_rather_than_stored(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/settings", json={"made_up_setting": 3})
            data = response.get_json()
        self.assertEqual(response.status_code, 422)
        self.assertIn("made_up_setting", data["errors"])

    def test_cross_field_rules_are_enforced(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/settings", json={"rsi_overbought": 20, "rsi_oversold": 80})
            data = response.get_json()
        self.assertEqual(response.status_code, 422)
        self.assertTrue(data["errors"])

    def test_form_encoding_is_accepted_and_empty_checkbox_means_off(self):
        # the settings page posts one full form, so booleans that are absent from
        # it mean "unchecked" — that is how the page can turn a feature off
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/settings", data={
                "news_enabled": "", "ui_refresh_seconds": "45", "symbol": "SOL/USDT",
            })
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            data = response.get_json()
            self.assertTrue(data["ok"])
            values = values_of(client)
            self.assertFalse(values["news_enabled"])
            self.assertEqual(values["ui_refresh_seconds"], 45)
            self.assertEqual(values["symbol"], "SOL/USDT")
            self.assertFalse(values["derivatives_enabled"])         # absent from a form = off

    def test_list_and_dict_fields_round_trip(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            saved = client.post("/api/settings", json={
                "supported_coins": "BTC\nETH\nSOL",
                "optimizer_ranges": {"entry_threshold": [20, 40]},
            }).get_json()
            self.assertEqual(saved["values"]["supported_coins"], ["BTC", "ETH", "SOL"])
            self.assertEqual(saved["values"]["optimizer_ranges"], {"entry_threshold": [20, 40]})
            schema = client.get("/api/settings").get_json()
            self.assertEqual(schema["widgets"]["supported_coins"], "BTC\nETH\nSOL")
            self.assertEqual(json.loads(schema["widgets"]["optimizer_ranges"]),
                             {"entry_threshold": [20, 40]})

    def test_export_and_import(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            client.post("/api/settings", json={"risk_per_trade": 0.025})
            exported = client.get("/api/settings/export")
            self.assertEqual(exported.status_code, 200)
            self.assertIn("attachment", exported.headers.get("Content-Disposition", ""))
            payload = json.loads(exported.get_data(as_text=True))
            self.assertEqual(payload["risk_per_trade"], 0.025)
            self.assertEqual(payload["symbol"], "BTC/USDT")

            client.post("/api/settings/reset", json={})
            self.assertEqual(values_of(client)["risk_per_trade"], 0.01)   # back to the default

            imported = client.post("/api/settings/import", json={"json": json.dumps(payload)}).get_json()
            self.assertTrue(imported["ok"])
            self.assertGreaterEqual(imported["applied"], 1)
            self.assertEqual(values_of(client)["risk_per_trade"], 0.025)

    def test_import_reports_unrecognised_keys_instead_of_failing(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.post("/api/settings/import", json={
                "json": json.dumps({"rsi_period": 9, "nonsense": 1, "news_provider": "lexicon"}),
            }).get_json()
            self.assertTrue(data["ok"])
            self.assertIn("nonsense", data["ignored"])
            self.assertEqual(values_of(client)["rsi_period"], 9)
            client.post("/api/settings/reset", json={})

    def test_import_rejects_a_non_object(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            for body in ({"json": "[1,2,3]"}, {"json": "not json"}):
                response = client.post("/api/settings/import", json=body)
                self.assertEqual(response.status_code, 400, body)
                self.assertIn("json", response.get_json()["errors"])
            empty = client.post("/api/settings/import", json={})
            self.assertEqual(empty.status_code, 422)
            self.assertIn("json", empty.get_json()["errors"])

    def test_reset_removes_the_file(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            client.post("/api/settings", json={"atr_period": 9})
            self.assertTrue((folder / "settings.json").exists())
            client.post("/api/settings/reset", json={})
            self.assertFalse((folder / "settings.json").exists())
            self.assertEqual(values_of(client)["atr_period"], 14)

    def test_data_probe_answers_without_a_network(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.post("/api/settings/test/data", json={}).get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "demo")
        self.assertFalse(data["live"])
        self.assertEqual(len(data["timeframes"]), 3)
        self.assertGreaterEqual(min(row["rows"] for row in data["timeframes"].values()), 60)
        self.assertIn("15m", data["supported_timeframes"])

    def test_llm_probe_reports_an_unreachable_local_model_with_advice(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/settings/test/llm", json={"values": {
                "news_provider": "ollama", "ollama_url": "http://127.0.0.1:9",
                "ollama_model": "nobody-home", "llm_timeout": 0.05,
            }})
            data = response.get_json()
        self.assertEqual(response.status_code, 502)
        self.assertFalse(data["ok"])
        self.assertEqual(data["provider"], "ollama")
        self.assertEqual(data["model"], "nobody-home")
        self.assertFalse(data["ping"]["reachable"])
        self.assertIn("ollama", data["hint"].lower())
        self.assertEqual(data["fallback"], "lexicon")             # analysis still works

    def test_llm_probe_says_no_model_is_needed_for_the_lexicon(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.post("/api/settings/test/llm", json={"values": {"news_provider": "lexicon"}}).get_json()
        self.assertTrue(data["ok"])
        self.assertIsNone(data["reachable"])
        self.assertIn("lexicon", data["detail"])

    def test_news_probe_runs_the_offline_engine(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            data = client.post("/api/settings/test/news", json={"values": {
                "news_enabled": True, "news_provider": "lexicon", "rss_feeds": [],
                "cryptopanic_enabled": False, "fear_greed_enabled": False,
            }}).get_json()
        self.assertIn(data["news"]["status"], ("NO_DATA", "OFFLINE"))
        self.assertFalse(data["ok"])                              # nothing to score offline
        self.assertTrue(data["applied"])                          # the settings it tried are echoed
        self.assertIn("summary", data["news"])


class OwnDataTests(unittest.TestCase):
    def test_upload_profile_activate_and_switch_back(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            response = client.post("/api/data/upload", data={
                "file": (io.BytesIO(demo_csv(200)), "my-solana-data.csv"),
                "timeframe": "15m",
                "activate": "1",
            }, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            uploaded = response.get_json()
            self.addCleanup(_drop_upload, uploaded["file"])
            self.assertTrue(uploaded["ok"])
            self.assertEqual(uploaded["errors"], {})
            self.assertEqual(uploaded["profile"]["rows"], 200)
            self.assertEqual(uploaded["profile"]["timeframe"], "15m")
            self.assertTrue(uploaded["file"].startswith("data/uploads/"))
            self.assertIn("CSV", uploaded["activate_message"])
            self.assertTrue(Path(uploaded["file"]).is_file() or Path(uploaded["file"]).name)

            settings = values_of(client)
            self.assertEqual(settings["data_source"], "csv")
            self.assertEqual(settings["csv_path"], uploaded["file"])
            self.assertEqual(settings["csv_timeframe"], "15m")

            # the panel now serves *my* candles
            candles = client.get("/api/candles?symbol=SOL&tf=15m").get_json()
            self.assertEqual(candles["source"], "csv")
            self.assertEqual(candles["live"], False)
            self.assertGreater(len(candles["candles"]), 50)
            self.assertLess(max(row["close"] for row in candles["candles"]), 1000)   # my prices, not demo's

            # a 200-row file cannot fill every timeframe, so the panel must say
            # "no verdict" instead of crashing on the missing scores
            signal = client.get("/api/signal?symbol=SOL").get_json()
            self.assertEqual(signal["data"]["source"], "csv")
            self.assertGreater(signal["price"], 0)
            self.assertIn(signal["signal"], ("WAIT", "NO_TRADE", "LONG", "SHORT"))
            self.assertIn(signal["verdict"], ("HOLD", "BUY", "SELL"))
            json.dumps(signal)
            slim = client.get("/api/signal?symbol=SOL&full=0").get_json()
            self.assertEqual(slim["signal"], signal["signal"])

            backtest = client.get("/api/backtest?symbol=SOL").get_json()
            self.assertEqual(backtest["source"], "csv")

            files = client.get("/api/data/files").get_json()
            mine = [row for row in files["files"] if row["name"] == Path(uploaded["file"]).name]
            self.assertEqual(len(mine), 1)
            self.assertIn("my-solana-data.csv", mine[0]["name"])     # timestamp-prefixed name kept
            self.assertEqual(files["current"], uploaded["file"])
            self.assertEqual(files["profile"]["rows"], 200)

            listing = client.get("/settings").get_data(as_text=True)
            self.assertIn("my-solana-data.csv", listing)

            _drop_upload(uploaded["file"])
            cleared = client.post("/api/data/use", json={"clear": True}).get_json()
            self.assertTrue(cleared["ok"])
            self.assertEqual(values_of(client)["data_source"], "auto")
            self.assertEqual(client.get("/api/candles?symbol=SOL&tf=15m").get_json()["source"], "demo")

    def test_upload_without_activate_keeps_the_current_source(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            uploaded = client.post("/api/data/upload", data={
                "file": (io.BytesIO(demo_csv(150)), "quiet.csv"),
            }, content_type="multipart/form-data").get_json()
            self.addCleanup(_drop_upload, uploaded["file"])
            self.assertTrue(uploaded["ok"])
            settings = values_of(client)
            self.assertEqual(settings["data_source"], "demo")
            self.assertEqual(settings["csv_path"], uploaded["file"])
            self.assertIn("Data source", uploaded["activate_message"])
            self.assertEqual(client.get("/api/candles?symbol=BTC&tf=15m").get_json()["source"], "demo")

    def test_upload_rejects_a_file_without_ohlcv_columns(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            response = client.post("/api/data/upload", data={
                "file": (io.BytesIO(b"a,b,c\n1,2,3\n"), "junk.csv"),
            }, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 422)
            data = response.get_json()
            self.assertFalse(data["ok"])
            self.assertIn("missing required columns", data["error"])
            # nothing was remembered as the active source
            self.assertEqual(client.get("/api/candles?symbol=BTC&tf=15m").get_json()["source"], "demo")

    def test_upload_requires_a_file(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/data/upload", data={}, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 400)
            self.assertIn("no file", response.get_json()["error"])

    def test_use_path_can_switch_sources(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            upload = client.post("/api/data/upload", data={
                "file": (io.BytesIO(demo_csv(120)), "pickme.csv"), "activate": "0",
            }, content_type="multipart/form-data").get_json()
            self.addCleanup(_drop_upload, upload["file"])
            used = client.post("/api/data/use", json={"path": upload["file"],
                                                     "timeframe": "15m"}).get_json()
            self.assertTrue(used["ok"])
            self.assertEqual(used["applied"]["data_source"], "csv")
            self.assertEqual(client.get("/api/candles?symbol=BTC&tf=15m").get_json()["source"], "csv")

            switched = client.post("/api/data/use", json={"data_source": "exchange"}).get_json()
            self.assertTrue(switched["ok"])
            # no network here: the exchange attempt falls back, it never 500s
            candles = client.get("/api/candles?symbol=BTC&tf=15m").get_json()
            self.assertIn(candles["source"], ("demo", "exchange"))
            client.post("/api/settings/reset", json={})

    def test_use_refers_to_missing_and_outside_files(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            missing = client.post("/api/data/use", json={"path": "data/uploads/nope.csv"})
            self.assertEqual(missing.status_code, 400)
            self.assertIn("no such file", missing.get_json()["error"])

            # the settings file is read on every analysis run, so a path outside
            # the project is refused unless the operator opts in explicitly
            outside = client.post("/api/data/use", json={"path": "/etc/passwd"})
            self.assertEqual(outside.status_code, 400)
            self.assertIn("outside the project folder", outside.get_json()["error"])

            sneaky = client.post("/api/data/use", json={"path": "../outside.csv"})
            self.assertIn("no such file", sneaky.get_json()["error"])


class OptimizationEndpointTests(unittest.TestCase):
    def test_optimize_then_apply_changes_the_live_settings(self):
        with self.enterContext(isolated_cache()), panel() as (client, folder):
            response = client.post("/api/backtest/optimize", json={
                "symbol": "BTC", "trials": 3, "mode": "grid", "objective": "score",
                "ranges": {"entry_threshold": [20.0, 30.0], "cooldown_candles": [4.0]},
            })
            data = response.get_json()
            self.assertTrue(data["ok"], data.get("error"))
            self.assertEqual(data["mode"], "grid")
            self.assertEqual(len(data["trials"]), 2)     # 2 x 1 combinations, "trials" is a cap
            self.assertEqual(data["trials"][0]["params"]["cooldown_candles"], 4.0)
            self.assertIn("overfit_gap", data)
            self.assertGreater(data["train_rows"], 0)
            self.assertLess(data["test_rows"], data["train_rows"])
            json.dumps(data)

            applied = client.post("/api/backtest/apply", json={"params": data["best"]["params"]})
            self.assertEqual(applied.status_code, 200)
            saved = json.loads((folder / "settings.json").read_text(encoding="utf-8"))
            self.assertIn("entry_threshold", saved)
            client.post("/api/settings/reset", json={})

    def test_optimize_reports_a_clear_error_for_impossible_ranges(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/backtest/optimize", json={"data_source": "telepathy"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("data_source", response.get_json()["errors"])

    def test_apply_refuses_invalid_params(self):
        with self.enterContext(isolated_cache()), panel() as (client, _folder):
            response = client.post("/api/backtest/apply", json={"params": {"entry_threshold": 9999}})
            self.assertEqual(response.status_code, 422)
            self.assertIn("entry_threshold", response.get_json()["errors"])


if __name__ == "__main__":
    unittest.main()
