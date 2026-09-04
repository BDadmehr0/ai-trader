"""Backtest service, metrics, journal and the walk-forward optimiser.

Runs on the deterministic offline demo data, so the numbers are reproducible.
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timezone

from backtesting.metrics import calculate_metrics
from backtesting.models import Trade
from backtesting.optimizer import (
    DEFAULT_SPACE,
    apply_best,
    build_trials,
    composite_score,
    objective_value,
    parse_ranges,
)
from backtesting.service import run_backtest, serialize_trade
from config.store import override_settings
from tests.support import isolated_cache


DEMO = {"data_source": "demo", "news_enabled": False, "derivatives_enabled": False,
        "cross_asset_enabled": False, "journal_enabled": False, "cache_minutes": 0,
        "backtest_candles": 400}


def run_demo(**settings):
    with override_settings(**{**DEMO, **settings}):
        return run_backtest("BTC")


class MetricsTests(unittest.TestCase):
    def trade(self, net, holding=4, direction="LONG", reason="TAKE_PROFIT_1", margin=100.0):
        return Trade(
            entry_time="2026-01-01T00:00:00+00:00", exit_time="2026-01-01T01:00:00+00:00",
            direction=direction, entry_price=100.0, exit_price=100.0 + net, initial_stop=95.0,
            final_stop=95.0, take_profit=110.0, position_size=1.0, leverage=2.0, margin_used=margin,
            entry_fee=0.5, exit_fee=0.5, funding_fee=0.0, slippage_cost=0.1,
            gross_pnl=net + 1.1, net_pnl=net, return_on_margin=net / margin * 100.0,
            exit_reason=reason, holding_candles=holding,
        )

    def test_empty_trade_list_returns_nothing(self):
        self.assertEqual(calculate_metrics([], [], 1000.0), {})

    def test_core_metrics_are_computed(self):
        trades = [self.trade(50.0), self.trade(-20.0), self.trade(30.0), self.trade(-10.0)]
        equity = [1000.0, 1050.0, 1030.0, 1060.0, 1050.0]
        metrics = calculate_metrics(trades, equity, 1000.0)
        self.assertEqual(metrics["total_trades"], 4)
        self.assertEqual(metrics["wins"], 2)
        self.assertEqual(metrics["losses"], 2)
        self.assertAlmostEqual(metrics["win_rate"], 50.0)
        self.assertAlmostEqual(metrics["profit_factor"], 80.0 / 30.0, places=4)
        self.assertAlmostEqual(metrics["total_return"], 5.0, places=2)
        self.assertGreater(metrics["max_drawdown"], 0)
        self.assertEqual(metrics["average_pnl"], 12.5)
        self.assertEqual(metrics["avg_holding_candles"], 4.0)
        self.assertIn("sharpe", metrics)
        self.assertIn("sortino", metrics)
        self.assertIn("recovery_factor", metrics)
        self.assertEqual(metrics["exit_reasons"], {"TAKE_PROFIT_1": 4})
        self.assertAlmostEqual(metrics["net_profit"], 50.0)

    def test_drawdown_tracks_the_equity_curve(self):
        trades = [self.trade(100.0), self.trade(-60.0)]
        metrics = calculate_metrics(trades, [1000.0, 1100.0, 1040.0], 1000.0)
        self.assertAlmostEqual(metrics["max_drawdown"], 5.4545, places=3)

    def test_all_wins_has_no_loss_division_crash(self):
        metrics = calculate_metrics([self.trade(10.0)], [1000.0, 1010.0], 1000.0)
        self.assertEqual(metrics["win_rate"], 100.0)
        self.assertTrue(math.isinf(metrics["profit_factor"]) or metrics["profit_factor"] >= 1.0)

    def test_trade_serialisation_is_json_safe(self):
        payload = serialize_trade(self.trade(12.3456))
        json.dumps(payload)
        for key in ("entry_time", "exit_time", "direction", "entry_price", "net_pnl",
                    "fees", "position_size", "leverage", "take_profit", "exit_reason"):
            self.assertIn(key, payload)


class ServiceTests(unittest.TestCase):
    def test_demo_backtest_produces_a_full_result(self):
        with self.enterContext(isolated_cache()):
            result = run_demo()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.source, "demo")
        self.assertFalse(result.live)
        self.assertGreater(result.duration_ms, 0)
        self.assertIn("total_trades", result.metrics)
        for row in result.equity:
            self.assertIsInstance(row["time"], int)
            self.assertGreater(row["equity"], 0)
        self.assertGreater(result.coverage["rows"], 100)
        payload = result.to_dict()
        json.dumps(payload)                                   # the web layer depends on this

    def test_parameters_from_settings_change_the_run(self):
        with self.enterContext(isolated_cache()):
            strict = run_demo(entry_threshold=90.0, min_confidence=95)
            loose = run_demo(entry_threshold=5.0, min_confidence=0, min_volume_ratio=0.1,
                             adx_trend_min=0, require_macd_cross=False,
                             require_volume_confirm=False, require_structure_agreement=False,
                             min_risk_reward=0.0, max_overextension_pct=100.0)
        self.assertLessEqual(strict.metrics.get("total_trades", 0), loose.metrics.get("total_trades", 0))
        self.assertGreater(loose.metrics.get("total_trades", 0), 0)
        self.assertTrue(strict.ok and loose.ok)
        self.assertNotEqual(strict.params["entry_threshold"], loose.params["entry_threshold"])
        self.assertEqual(strict.params["entry_threshold"], 90.0)

    def test_fees_and_leverage_are_applied(self):
        with self.enterContext(isolated_cache()):
            free = run_demo(taker_fee=0.0, slippage=0.0, funding_rate=0.0, entry_threshold=5.0,
                            min_confidence=0, min_volume_ratio=0.1, adx_trend_min=0,
                            require_macd_cross=False, require_volume_confirm=False,
                            require_structure_agreement=False, min_risk_reward=0.0,
                            max_overextension_pct=100.0)
            costly = run_demo(taker_fee=0.002, slippage=0.001, funding_rate=0.001,
                              entry_threshold=5.0, min_confidence=0, min_volume_ratio=0.1,
                              adx_trend_min=0, require_macd_cross=False,
                              require_volume_confirm=False, require_structure_agreement=False,
                              min_risk_reward=0.0, max_overextension_pct=100.0)
        self.assertLess(costly.metrics["total_return"], free.metrics["total_return"])

    def test_risk_manager_sizing_is_used(self):
        with self.enterContext(isolated_cache()):
            tiny = run_demo(risk_per_trade=0.1, initial_balance=500.0)
            big = run_demo(risk_per_trade=2.0, initial_balance=50_000.0)
        if tiny.trades and big.trades:
            self.assertLess(abs(tiny.trades[0]["position_size"]), abs(big.trades[0]["position_size"]))
        for row in (tiny.trades[:1] + big.trades[:1]):
            self.assertLessEqual(row["notional"] if "notional" in row else row["margin_used"] * 10,
                                 50_000 * 50 + 1)

    def test_shorts_can_be_switched_off(self):
        with self.enterContext(isolated_cache()):
            both = run_demo(allow_shorts=True, allow_longs=True)
            long_only = run_demo(allow_shorts=False, allow_longs=True)
        directions = {trade["direction"] for trade in both.trades}
        if directions:
            self.assertTrue(directions <= {"LONG", "SHORT"})
        self.assertTrue(all(trade["direction"] == "LONG" for trade in long_only.trades))


class MixedResolutionTests(unittest.TestCase):
    """Regression: `merge_asof` dies when the frames disagree on the unit.

    pandas 3 raises `MergeError: incompatible merge keys [0] datetime64[ms, UTC]
    and datetime64[s, UTC], must be the same type` — which is exactly what the
    panel hit when one timeframe came from the disk cache (epoch seconds) while
    its neighbours were fetched live (milliseconds) or read from the demo CSVs
    (microseconds).
    """

    def frames(self):
        """Raw (no indicators) demo frames for the three default timeframes."""
        from data.market_data import MarketData

        with isolated_cache(), override_settings(**{**DEMO, "backtest_candles": 400}):
            market = MarketData()
            return {tf: market.get_ohlcv("BTC", tf, 400) for tf in ("15m", "1h", "4h")}

    def test_mtf_merge_survives_mixed_timestamp_resolutions(self):
        from analysis.indicators import add_indicators
        from backtesting.mtf import prepare_mtf_data
        from utils.timeutils import TIMESTAMP_DTYPE

        with override_settings(**DEMO):
            frames = {tf: add_indicators(frame) for tf, frame in self.frames().items()}
        frames["1h"]["timestamp"] = frames["1h"]["timestamp"].astype("datetime64[s, UTC]")
        frames["4h"]["timestamp"] = frames["4h"]["timestamp"].astype("datetime64[us, UTC]")

        merged = prepare_mtf_data(frames["15m"], frames["1h"], frames["4h"])
        self.assertGreater(len(merged), 60)
        self.assertEqual(str(merged["timestamp"].dtype), TIMESTAMP_DTYPE)
        self.assertTrue(merged["timestamp"].is_monotonic_increasing)

    def test_backtest_runs_on_frames_from_mixed_sources(self):
        from analysis.indicators import add_indicators

        with override_settings(**DEMO):
            frames = {tf: add_indicators(frame) for tf, frame in self.frames().items()}
        frames["1h"]["timestamp"] = frames["1h"]["timestamp"].astype("datetime64[s, UTC]")

        with isolated_cache(), override_settings(**{**DEMO, "backtest_candles": 400}):
            result = run_backtest("BTC", frames=frames)
        self.assertTrue(result.ok, result.error)
        self.assertGreaterEqual(result.coverage["rows"], 60)

    def test_optimizer_survives_mixed_resolutions(self):
        from backtesting.optimizer import run as optimize

        class MixedMarket:
            """Hands out the 4h frame at second resolution, like a cached one."""

            source, is_live = "demo", False

            def __init__(self, frames):
                self._frames = frames

            def get_ohlcv(self, symbol, timeframe, limit=None):
                frame = self._frames[timeframe].copy()
                if timeframe == "4h":
                    frame["timestamp"] = frame["timestamp"].astype("datetime64[s, UTC]")
                return frame

        market = MixedMarket(self.frames())
        with isolated_cache(), override_settings(**{**DEMO, "backtest_candles": 400,
                                                    "optimizer_trials": 2}):
            payload = optimize("BTC", market=market)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertIsNone(payload["error"])
        self.assertIn("trials", payload)


class OptimizerSpaceTests(unittest.TestCase):
    def test_default_space_only_touches_real_settings(self):
        from config.definition import ITEMS

        for key in DEFAULT_SPACE:
            self.assertIn(key, ITEMS, key)

    def test_ranges_are_parsed_from_every_ui_shape(self):
        parsed = parse_ranges({
            "entry_threshold": [20, 30, 40],
            "atr_stop_multiplier": "1.0, 1.5, 2.0",
            "min_confidence": {"min": 30, "max": 60, "step": 15},
            "max_holding_candles": {"min": 24, "max": 96, "count": 4},
            "cooldown_candles": 4,
        })
        self.assertEqual(parsed["entry_threshold"], [20.0, 30.0, 40.0])
        self.assertEqual(parsed["atr_stop_multiplier"], [1.0, 1.5, 2.0])
        self.assertEqual(parsed["min_confidence"], [30.0, 45.0, 60.0])
        self.assertEqual(parsed["max_holding_candles"], [24.0, 48.0, 72.0, 96.0])
        self.assertEqual(parsed["cooldown_candles"], [4.0])

    def test_ranges_accept_json_text_and_reversed_windows(self):
        from_json = parse_ranges('{"entry_threshold": [20, 40]}')
        self.assertEqual(from_json, {"entry_threshold": [20.0, 40.0]})
        self.assertEqual(parse_ranges({"entry_threshold": {"min": 40, "max": 20, "step": 20}}),
                         {"entry_threshold": [20.0, 40.0]})

    def test_garbage_ranges_are_dropped_without_breaking_the_run(self):
        # the search space is a convenience: a stray key or bad JSON must never
        # abort an optimization, it just falls back to the default space
        self.assertEqual(parse_ranges("this is not json"), {})
        self.assertEqual(parse_ranges(None), {})
        self.assertEqual(parse_ranges([1, 2, 3]), {})
        self.assertEqual(parse_ranges({"not_a_setting": [1, 2]}), {})
        self.assertEqual(parse_ranges({"entry_threshold": []}), {})
        self.assertEqual(parse_ranges({"min_confidence": {"max": 3}}), {})

    def test_dropped_values_survive_as_strings_only_if_unparseable(self):
        parsed = parse_ranges({"entry_threshold": ["20", "abc"]})
        self.assertEqual(parsed["entry_threshold"][0], 20.0)
        self.assertEqual(parsed["entry_threshold"][1], "abc")   # coerce happens per trial

    def test_trials_are_deterministic_for_a_seed(self):
        from config.store import get_settings

        with override_settings(optimizer_seed=5, optimizer_mode="random"):
            first = build_trials(get_settings(), DEFAULT_SPACE, 8)
        with override_settings(optimizer_seed=5, optimizer_mode="random"):
            second = build_trials(get_settings(), DEFAULT_SPACE, 8)
        with override_settings(optimizer_seed=99, optimizer_mode="random"):
            other = build_trials(get_settings(), DEFAULT_SPACE, 8)
        self.assertNotEqual(first, other)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        for combo in first:
            self.assertTrue(set(combo) <= set(DEFAULT_SPACE))

    def test_grid_mode_enumerates_the_product(self):
        space = {"entry_threshold": [20, 40], "cooldown_candles": [2, 8]}
        with override_settings(optimizer_mode="grid"):
            from config.store import get_settings

            trials = build_trials(get_settings(), space, 50)
        self.assertEqual(len(trials), 4)
        self.assertEqual({(row["entry_threshold"], row["cooldown_candles"]) for row in trials},
                         {(20, 2), (20, 8), (40, 2), (40, 8)})


class ObjectiveTests(unittest.TestCase):
    metrics = {"total_trades": 20, "win_rate": 55.0, "profit_factor": 1.6, "total_return": 12.0,
               "max_drawdown": 5.0, "sharpe": 1.4, "final_balance": 1120.0, "expectancy": 6.0}

    def test_named_objectives_all_work(self):
        for name in ("score", "sharpe", "profit_factor", "total_return", "win_rate"):
            self.assertIsInstance(objective_value(self.metrics, name), float)
        self.assertAlmostEqual(objective_value(self.metrics, "win_rate"), 55.0)

    def test_an_unusable_objective_is_penalised_not_forgotten(self):
        # a typo must not turn into "this combo looks great"; -1e9 always loses
        self.assertEqual(objective_value(self.metrics, "made_up"), -1e9)
        self.assertEqual(objective_value({}, "score"), -1e9)

    def test_no_trades_can_never_win(self):
        active = composite_score(self.metrics)
        empty = composite_score({"total_trades": 0, "win_rate": 0, "profit_factor": 0,
                                 "total_return": 0, "max_drawdown": 0, "sharpe": 0,
                                 "final_balance": 1000, "expectancy": 0})
        self.assertGreater(active, empty)
        self.assertLess(empty, -1e8)

    def test_thin_sample_is_penalised(self):
        few = dict(self.metrics, total_trades=2, win_rate=100.0, total_return=6.0)
        self.assertLess(composite_score(few), composite_score(self.metrics))

    def test_deep_drawdown_is_penalised(self):
        risky = dict(self.metrics, max_drawdown=45.0)
        self.assertLess(composite_score(risky), composite_score(self.metrics))


class OptimizerRunTests(unittest.TestCase):
    def test_walk_forward_run_and_apply(self):
        with self.enterContext(isolated_cache()), tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["AITRADER_SETTINGS_FILE"] = str(Path(tmp) / "settings.json")
            try:
                with override_settings(**DEMO, optimizer_trials=4, optimizer_seed=3,
                                        optimizer_ranges={"entry_threshold": [15, 25],
                                                          "cooldown_candles": [2, 12]}):
                    from backtesting.optimizer import run as run_optimizer
                    from config.store import get_settings

                    result = run_optimizer("BTC", get_settings())
                self.assertTrue(result["ok"], result.get("error"))
                self.assertEqual(result["trials"], sorted(result["trials"],
                                                          key=lambda row: row["train_objective"], reverse=True))
                self.assertGreater(result["train_rows"], result["test_rows"])
                self.assertEqual(len(result["trials"]), 4)
                best = result["best"]
                self.assertIn("params", best)

                saved, errors = apply_best(best["params"])
                self.assertEqual(errors, {})
                self.assertTrue(saved)
                written = json.loads((Path(tmp) / "settings.json").read_text(encoding="utf-8"))
                for key, value in best["params"].items():
                    self.assertAlmostEqual(written[key], value, places=6)
            finally:
                del os.environ["AITRADER_SETTINGS_FILE"]

    def test_apply_best_validates_every_key(self):
        saved, errors = apply_best({"entry_threshold": 9999, "made_up": 1})
        self.assertFalse(saved)
        self.assertIn("entry_threshold", errors)
        self.assertIn("made_up", errors)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "signals.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_evaluate_and_summary_roundtrip(self):
        from analysis import journal

        report = {
            "symbol": "BTC", "signal": "LONG", "confidence": 62, "price": 100.0,
            "setup": {"entry": 100.0, "stop_loss": 95.0, "take_profit_1": 110.0,
                      "take_profit_2": 115.0, "risk_reward_1": 2.0},
            "scores": {"combined": 40.0, "breakdown": [
                {"name": "trend", "score": 60.0, "weight": 30.0, "available": True},
                {"name": "momentum", "score": 20.0, "weight": 20.0, "available": True},
                {"name": "news", "score": None, "weight": 0.0, "available": False}]},
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        fresh = dict(report, updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with override_settings(journal_path=self.path, journal_enabled=True,
                               journal_eval_after_candles=1, journal_touch_tolerance="strict"):
            self.assertIsNotNone(journal.record_signal(fresh))
            # the same unchanged signal one minute later must not stack up in the
            # accuracy stats — that is what the dashboard auto-refresh would do
            self.assertIsNone(journal.record_signal(fresh))
            records = journal.read_records()
            self.assertEqual(len(records), 1)
            # a different direction is always worth recording
            self.assertIsNotNone(journal.record_signal(dict(fresh, signal="SHORT", confidence=55)))
            self.assertEqual(len(journal.read_records()), 2)
            # ...and an old (already judgeable) signal is not a repeat
            self.assertIsNotNone(journal.record_signal(report))
            self.assertEqual(records[0]["signal"], "LONG")
            self.assertIn("fingerprint", records[0])

            summary = journal.summary()
            self.assertEqual(summary["records"], 3)     # fresh + SHORT + the old one
            self.assertEqual(summary["pending"], 3)

            outcome = journal.evaluate_open_signals(force=True)
            # two of them are older than the demo window's end, one was written
            # "now": the young one stays pending instead of blowing up
            self.assertGreaterEqual(outcome["evaluated"], 1)
            self.assertEqual(outcome["total"], 3)
            after = journal.summary()
            self.assertGreaterEqual(after["evaluated"], 1)
            self.assertEqual(after["records"], 3)
            self.assertIsInstance(after["win_rate"], float)
            self.assertIsInstance(after["avg_r"], float)
            self.assertIn("by_confidence", after)
            self.assertIn("by_symbol", after)

    def test_disabled_journal_writes_nothing(self):
        from analysis import journal

        with override_settings(journal_path=self.path, journal_enabled=False):
            self.assertIsNone(journal.record_signal({"symbol": "BTC", "signal": "LONG"}))
            self.assertEqual(journal.read_records(), [])

    def test_summary_of_an_empty_journal_is_honest(self):
        from analysis import journal

        with override_settings(journal_path=self.path, journal_enabled=True):
            summary = journal.summary()
        self.assertEqual(summary["records"], 0)
        self.assertIsNone(summary["win_rate"])
        self.assertIsNone(summary["avg_r"])

    def test_calibration_report_shape(self):
        from analysis.calibration import report

        with override_settings(journal_path=self.path, weight_mode="manual"):
            payload = report(force=True)
        for key in ("mode", "meta", "multipliers", "components", "base_weights", "effective_weights"):
            self.assertIn(key, payload)
        self.assertFalse(payload["meta"]["active"])       # 0 samples
        self.assertEqual(payload["multipliers"], {})
        self.assertEqual(payload["base_weights"], payload["effective_weights"])

    def test_adaptive_weights_need_samples(self):
        from analysis.calibration import weight_multipliers

        with override_settings(journal_path=self.path, weight_mode="adaptive", adaptive_min_samples=5):
            self.assertEqual(weight_multipliers(), {})


if __name__ == "__main__":
    unittest.main()
