"""Indicator maths and the server-side chart overlays (offline, synthetic data)."""

import unittest

import numpy as np
import pandas as pd

from analysis.indicators import add_indicators, latest, overlay_series
from analysis.signal import analyze_timeframe
from config.store import override_settings


def synthetic(count: int = 300, start: float = 100.0, drift: float = 0.15, seed: int = 3) -> pd.DataFrame:
    """A gentle uptrend with noise — enough for every indicator to settle."""
    rng = np.random.default_rng(seed)
    closes = start + np.cumsum(rng.normal(drift, 0.6, count))
    opens = np.concatenate([[start], closes[:-1]])
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 0.25, count))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 0.25, count))
    volumes = np.abs(rng.normal(1000, 250, count))
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=count, freq="15min", tz="UTC"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


class IndicatorContractTests(unittest.TestCase):
    def setUp(self):
        self.frame = add_indicators(synthetic())

    def test_canonical_columns_exist(self):
        """The column set is the contract with analysis/signal.py — renaming one
        there without adding it here must fail here first."""
        for column in ("timestamp", "open", "high", "low", "close", "volume",
                       "ema_fast", "ema_mid", "ema_slow", "ema20", "ema50", "ema200", "ema_fast_slope",
                       "rsi", "rsi_stoch_k", "roc", "macd", "macd_signal", "macd_histogram", "macd_hist_pct",
                       "tr", "atr", "atr_pct", "atr_ratio", "plus_di", "minus_di", "adx", "di_spread",
                       "bb_upper", "bb_mid", "bb_lower", "bb_pct_b", "bb_bandwidth", "bb_squeeze",
                       "vwap", "vwap_dist_pct", "supertrend", "supertrend_dir",
                       "volume_ma", "volume_ratio", "vol_zscore", "obv", "obv_slope", "mfi", "cci"):
            self.assertIn(column, self.frame.columns, column)

    def test_windows_are_partial_tolerant(self):
        """Rolling windows use min_periods=1 on purpose: a freshly listed coin or
        a short CSV must still get values instead of a NaN column."""
        for column in ("ema_fast", "bb_mid", "vwap", "atr", "volume_ratio", "mfi", "rsi"):
            self.assertTrue(self.frame[column].notna().all(), column)
        # only derived ratios are undefined during their seeding
        self.assertTrue(self.frame["roc"].isna().any())
        self.assertTrue(self.frame["ema_fast_slope"].isna().any())
        tail = self.frame.tail(60)
        for column in ("rsi", "adx", "atr", "volume_ratio", "bb_pct_b", "supertrend_dir", "vwap"):
            values = tail[column].to_numpy(dtype=float)
            self.assertTrue(np.isfinite(values).all(), f"{column} still has NaN after warmup")

    def test_rsi_and_bands_stay_in_range(self):
        tail = self.frame.tail(100)
        self.assertTrue(tail["rsi"].between(0, 100).all())
        self.assertTrue(tail["bb_pct_b"].between(-0.5, 1.5).all())
        self.assertTrue((tail["bb_upper"] >= tail["bb_lower"]).all())
        self.assertTrue((tail["supertrend_dir"].isin([-1.0, 1.0])).all())

    def test_clean_uptrend_reads_as_uptrend(self):
        analysis = analyze_timeframe(self.frame, "15m")
        last = latest(self.frame)
        self.assertEqual(int(last["supertrend_dir"]), 1)
        self.assertEqual(analysis["trend"], "BULLISH")
        self.assertEqual(analysis["structure_trend"], "BULLISH")
        self.assertGreater(analysis["supertrend"], 0)
        self.assertGreater(last["ema_fast"], last["ema_slow"])
        self.assertGreater(analysis["score"], 0)

    def test_clean_downtrend_reads_as_downtrend(self):
        frame = add_indicators(synthetic(300, drift=-0.15))
        analysis = analyze_timeframe(frame, "15m")
        self.assertEqual(int(latest(frame)["supertrend_dir"]), -1)
        self.assertLess(analysis["score"], 0)

    def test_settings_are_actually_used(self):
        frame = synthetic()
        with override_settings(rsi_period=5, ema_fast=3, ema_mid=6, ema_slow=9):
            fast = add_indicators(frame)
        with override_settings(rsi_period=40, ema_fast=60, ema_mid=90, ema_slow=120):
            slow = add_indicators(frame)
        self.assertFalse(np.allclose(fast["rsi"].tail(20).to_numpy(), slow["rsi"].tail(20).to_numpy()))
        self.assertFalse(np.allclose(fast["ema_fast"].tail(20).to_numpy(), slow["ema_fast"].tail(20).to_numpy()))
        # a longer EMA window is a smoother curve
        self.assertLess(float(slow["ema_fast"].diff().abs().mean()),
                        float(fast["ema_fast"].diff().abs().mean()))

    def test_indicator_periods_change_the_warmup(self):
        frame = synthetic(120)
        with override_settings(supertrend_period=3, supertrend_multiplier=1.5):
            short_st = add_indicators(frame)
        with override_settings(supertrend_period=40, supertrend_multiplier=1.5):
            long_st = add_indicators(frame)
        self.assertGreater(int(long_st["supertrend"].isna().sum()), int(short_st["supertrend"].isna().sum()))

    def test_volume_spike_is_flagged(self):
        frame = synthetic(120)
        frame.loc[frame.index[-3], "volume"] = float(frame["volume"].median()) * 8
        analysed = add_indicators(frame)
        self.assertGreater(float(analysed["volume_ratio"].iloc[-3]), 3.0)
        self.assertGreater(float(analysed["vol_zscore"].iloc[-3]), 1.0)
        self.assertEqual(analysed["volume_analysis" if False else "volume_ratio"].notna().sum(), len(frame))


class OverlaySeriesTests(unittest.TestCase):
    def setUp(self):
        self.frame = add_indicators(synthetic(400))
        self.overlay = overlay_series(self.frame)

    def test_payload_shape(self):
        for key in ("emaFast", "emaMid", "emaSlow", "bbUpper", "bbMid", "bbLower", "vwap",
                    "rsi", "macd", "macdSignal", "macdHist", "adx", "superTrendUp", "superTrendDown",
                    "markers", "summary"):
            self.assertIn(key, self.overlay, key)

    def test_points_are_time_value_pairs_of_valid_numbers(self):
        for key, series in self.overlay.items():
            if not isinstance(series, list) or key == "markers" or not series:
                continue
            for point in series[:5]:
                self.assertEqual(sorted(point), ["time", "value"], key)
                self.assertIsInstance(point["time"], int)
                self.assertTrue(np.isfinite(point["value"]), f"{key} NaN leaked into the chart")

    def test_timestamps_are_seconds_not_microseconds(self):
        for key in ("emaFast", "rsi"):
            stamp = self.overlay[key][-1]["time"]
            self.assertTrue(1_600_000_000 < stamp < 2_000_000_000, f"{key}: {stamp}")

    def test_series_are_aligned_to_candles(self):
        candle_times = set(self.overlay_times())
        for point in self.overlay["rsi"]:
            self.assertIn(point["time"], candle_times)

    def overlay_times(self):
        frame = add_indicators(synthetic(400))
        return pd.to_datetime(frame["timestamp"]).values.astype("datetime64[s]").astype("int64").tolist()

    def test_supertrend_split_has_no_gaps_in_direction(self):
        up = {point["time"] for point in self.overlay["superTrendUp"]}
        down = {point["time"] for point in self.overlay["superTrendDown"]}
        self.assertFalse(up & down)
        self.assertTrue(up or down)

    def test_markers_are_sorted_and_capped(self):
        markers = self.overlay["markers"]
        self.assertLessEqual(len(markers), 60)
        times = [marker["time"] for marker in markers]
        self.assertEqual(times, sorted(times))
        for marker in markers:
            self.assertIn(marker["position"], ("aboveBar", "belowBar", "inBar"))
            self.assertTrue(marker["text"])
            self.assertTrue(marker["color"].startswith("#"))

    def test_summary_is_json_friendly(self):
        summary = self.overlay["summary"]
        for key in ("rsi", "adx", "atr", "atr_pct", "atr_ratio", "volume_ratio", "mfi", "cci",
                    "bb_pct_b", "vwap_dist_pct", "supertrend_dir", "ema_fast", "ema_mid", "ema_slow"):
            self.assertIn(key, summary, key)
            self.assertIsInstance(summary[key], float)
        import json

        json.dumps(self.overlay)  # must be serialisable as-is

    def test_downsampling_respects_max_points(self):
        small = overlay_series(self.frame, max_points=80)
        for key, series in small.items():
            if isinstance(series, list) and key not in ("markers",) and series:
                self.assertLessEqual(len(series), 80, key)

    def test_empty_frame_returns_empty_payload(self):
        self.assertEqual(overlay_series(pd.DataFrame()), {})

    def test_short_frame_does_not_crash(self):
        result = overlay_series(add_indicators(synthetic(12)))
        self.assertIsInstance(result, dict)
        self.assertIn("summary", result)


class VwapTests(unittest.TestCase):
    def test_daily_anchor_resets_each_session(self):
        frame = synthetic(200)
        with override_settings(vwap_session="daily"):
            analysed = add_indicators(frame)
        first_of_day = analysed[analysed["timestamp"].dt.strftime("%Y-%m-%d") == "2026-01-01"]["vwap"]
        self.assertGreater(first_of_day.max(), first_of_day.min())

    def test_vwap_can_be_disabled(self):
        with override_settings(vwap_session="none"):
            frame = add_indicators(synthetic(60))
        self.assertTrue(frame["vwap"].isna().all() or "vwap" not in frame)


if __name__ == "__main__":
    unittest.main()
