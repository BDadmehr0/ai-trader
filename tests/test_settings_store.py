"""Settings store: coercion, validation, persistence, schema, overrides."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from config.definition import DEFAULTS, ITEMS
from config.store import (
    SettingsStore,
    coerce,
    export_settings,
    get_settings,
    override_settings,
    schema_payload,
    settings_file,
    validate,
)


class CoercionTests(unittest.TestCase):
    def test_int_type_is_strict_about_bounds(self):
        item = ITEMS["rsi_period"]
        self.assertEqual(coerce(item, "21"), 21)
        self.assertEqual(coerce(item, 21.0), 21)
        with self.assertRaises(ValueError):      # not a whole number
            coerce(item, 21.7)
        with self.assertRaises(ValueError):      # out of range — never silently clamped
            coerce(item, 9999)
        with self.assertRaises(ValueError):      # a checkbox is not a number
            coerce(item, True)

    def test_bool_accepts_ui_form_values(self):
        item = ITEMS["news_enabled"]
        for truthy in (True, "1", "true", "on", "yes"):
            self.assertIs(coerce(item, truthy), True, truthy)
        for falsy in (False, "0", "false", "off", "", None):
            self.assertIs(coerce(item, falsy), False, falsy)

    def test_list_accepts_commas_newlines_and_json(self):
        item = ITEMS["supported_coins"]
        self.assertEqual(coerce(item, "BTC, ETH\nSOL"), ["BTC", "ETH", "SOL"])
        self.assertEqual(coerce(item, '["BTC", "ETH"]'), ["BTC", "ETH"])
        self.assertEqual(coerce(item, ""), [])

    def test_dict_accepts_json(self):
        item = ITEMS["optimizer_ranges"]
        self.assertEqual(coerce(item, '{"entry_threshold": [20, 30]}'), {"entry_threshold": [20, 30]})
        self.assertEqual(coerce(item, ""), {})
        with self.assertRaises(Exception):
            coerce(item, "entry_threshold=20")   # half-written JSON is an error, not a guess

    def test_enum_rejects_unknown_choice(self):
        with self.assertRaises(ValueError):
            coerce(ITEMS["news_provider"], "gpt-9")

    def test_unknown_key_is_reported_not_clamped(self):
        clean, errors = validate({"rsi_period": 500, "made_up": 1}, strict=True)
        self.assertEqual(clean, {})
        self.assertIn("rsi_period", errors)
        self.assertIn("made_up", errors)

    def test_lenient_mode_keeps_valid_keys(self):
        clean, errors = validate({"rsi_period": 500, "atr_period": 7}, strict=False)
        self.assertEqual(clean, {"atr_period": 7})
        self.assertIn("rsi_period", errors)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.store = SettingsStore(path=self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_only_persists_differences_and_reload_picks_them_up(self):
        settings, errors = self.store.save({"rsi_period": 9, "symbol": "ETH/USDT"})
        self.assertEqual(errors, {})
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["rsi_period"], 9)
        self.assertNotIn("atr_period", payload)  # default values stay out of the file

        reloaded = self.store.reload()
        self.assertEqual(reloaded.get("rsi_period"), 9)
        self.assertEqual(reloaded.get("symbol"), "ETH/USDT")
        self.assertEqual(reloaded.get("atr_period"), DEFAULTS["atr_period"])

    def test_invalid_values_are_refused_before_writing(self):
        before = self.path.exists()
        settings, errors = self.store.save({"entry_threshold": 99999})
        self.assertIn("entry_threshold", errors)
        self.assertEqual(self.path.exists(), before)
        self.assertEqual(settings.get("entry_threshold"), DEFAULTS["entry_threshold"])

    def test_reset_removes_the_file(self):
        self.store.save({"rsi_period": 12})
        self.assertTrue(self.path.exists())
        settings = self.store.reset()
        self.assertFalse(self.path.exists())
        self.assertEqual(settings.get("rsi_period"), DEFAULTS["rsi_period"])

    def test_broken_json_falls_back_to_defaults(self):
        self.path.write_text("{not json", encoding="utf-8")
        settings = self.store.reload()
        self.assertEqual(settings.get("rsi_period"), DEFAULTS["rsi_period"])
        self.assertIn("__file__", settings.errors)

    def test_hand_edited_out_of_range_value_is_dropped_not_used(self):
        self.path.write_text(json.dumps({"rsi_period": 9999, "atr_period": 7}), encoding="utf-8")
        settings = self.store.reload()
        self.assertEqual(settings.get("rsi_period"), DEFAULTS["rsi_period"])
        self.assertEqual(settings.get("atr_period"), 7)
        self.assertIn("rsi_period", settings.errors)

    def test_env_layer_is_readable_without_a_file(self):
        os.environ["AITRADER_RSI_PERIOD"] = "17"
        try:
            store = SettingsStore(path=Path(self.tmp.name) / "missing.json")
            self.assertEqual(store.reload().get("rsi_period"), 17)
        finally:
            del os.environ["AITRADER_RSI_PERIOD"]


class OverrideTests(unittest.TestCase):
    def test_context_manager_restores_previous_values(self):
        before = get_settings().get("entry_threshold")
        with override_settings(entry_threshold=11.0):
            self.assertEqual(get_settings().get("entry_threshold"), 11.0)
            with override_settings(entry_threshold=44.0, min_confidence=90):
                self.assertEqual(get_settings().get("entry_threshold"), 44.0)
            self.assertEqual(get_settings().get("entry_threshold"), 11.0)
        self.assertEqual(get_settings().get("entry_threshold"), before)

    def test_overrides_reach_the_pipeline_then_vanish(self):
        with override_settings(entry_threshold=77.0, news_enabled=False):
            settings = get_settings()
            self.assertEqual(settings.entry_threshold, 77.0)
            self.assertFalse(settings.news_enabled)
        self.assertNotEqual(get_settings().entry_threshold, 77.0)

    def test_timeframe_helpers(self):
        with override_settings(timeframes="5m, 1h, 1d"):
            settings = get_settings()
            self.assertEqual(settings.timeframe_list(), ["5m", "1h", "1d"])
            self.assertEqual((settings.tf_base, settings.tf_mid, settings.tf_high), ("5m", "1h", "1d"))
            self.assertEqual(settings.timeframe_labels, ["5M", "1H", "1D"])


class SchemaTests(unittest.TestCase):
    def test_schema_covers_every_item_exactly_once(self):
        schema = schema_payload()
        keys = [item["key"] for group in schema["groups"] for item in group["items"]]
        self.assertEqual(sorted(keys), sorted(ITEMS))
        self.assertEqual(len(keys), len(set(keys)))

    def test_schema_carries_ui_metadata(self):
        schema = schema_payload()
        for group in schema["groups"]:
            self.assertTrue(group["label"] and group["label_fa"] and group["icon"])
            for item in group["items"]:
                for field in ("key", "label", "type", "default", "value", "text", "widget", "is_default"):
                    self.assertIn(field, item, f"{item['key']}.{field}")
        self.assertIn("rsi_period", schema["widgets"])

    def test_export_is_a_complete_importable_snapshot(self):
        payload = json.loads(export_settings())
        self.assertEqual(sorted(payload), sorted(ITEMS))
        clean, errors = validate(payload, strict=True)
        self.assertEqual(errors, {})

    def test_settings_file_points_at_the_repo_default(self):
        self.assertEqual(settings_file().name, "settings.json")


class WeightsTests(unittest.TestCase):
    #: component name -> settings key. Weights are relative points, not
    #: percentages: resolve_weights() in analysis/scoring.py normalises them to
    #: 100 after applying calibration multipliers and availability.
    KEYS = {
        "trend": "weight_trend",
        "momentum": "weight_momentum",
        "volume": "weight_volume",
        "ms": "weight_structure",
        "tf": "weight_alignment",
        "vol": "weight_volatility",
        "sr": "weight_levels",
        "news": "weight_news",
        "derivatives": "weight_derivatives",
        "micro": "weight_micro",
        "cross": "weight_cross_asset",
    }

    def test_weights_are_positive_relative_points(self):
        weights = get_settings().weights()
        self.assertEqual(set(weights), set(self.KEYS))
        self.assertTrue(all(value > 0 for value in weights.values()), weights)

    def test_scoring_normalises_the_weights(self):
        from analysis.scoring import resolve_weights

        availability = {name: True for name in self.KEYS}
        resolved = resolve_weights(get_settings(), availability)
        self.assertAlmostEqual(sum(resolved.values()), 100.0, places=6)

        # a disabled component loses its share, the rest keep their ratio
        half = {**availability, "news": False}
        resolved_off = resolve_weights(get_settings(), half)
        self.assertEqual(resolved_off["news"], 0.0)
        self.assertAlmostEqual(sum(resolved_off.values()), 100.0, places=6)
        self.assertGreater(resolved_off["trend"], resolved["trend"])

    def test_calibration_multiplier_scales_a_component(self):
        from analysis.scoring import resolve_weights

        availability = {name: True for name in self.KEYS}
        boosted = resolve_weights(get_settings(), availability, multipliers={"trend": 2.0})
        self.assertGreater(boosted["trend"], resolve_weights(get_settings(), availability)["trend"])
        self.assertAlmostEqual(sum(boosted.values()), 100.0, places=6)

    def test_every_weight_setting_is_an_item(self):
        for key in self.KEYS.values():
            self.assertIn(key, ITEMS)

    def test_weight_mode_is_configurable(self):
        self.assertIn(get_settings().get("weight_mode"), ("manual", "adaptive"))
        with override_settings(weight_mode="adaptive"):
            self.assertEqual(get_settings().get("weight_mode"), "adaptive")


if __name__ == "__main__":
    unittest.main()
