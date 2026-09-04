"""Own-data support: CSV sniffing, resampling, profiles, and MarketData sources."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from data import csv_source
from data.csv_source import (
    guess_timeframe,
    list_csvs,
    load_csv,
    normalize_columns,
    profile,
    resample,
    timeframe_minutes,
)


def make_csv(rows: int = 240, freq: str = "15min", *, columns=None, start="2026-01-05",
             header_case=str.lower, with_volume=True) -> Path:
    """A synthetic 15m export in a typical exchange layout."""
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0.01, 0.4, rows))
    open_ = np.concatenate([[100.0], close[:-1]])
    frame = pd.DataFrame({
        "timestamp": pd.date_range(start, periods=rows, freq=freq, tz="UTC").strftime("%Y-%m-%d %H:%M:%S"),
        "open": open_,
        "high": np.maximum(open_, close) + 0.3,
        "low": np.minimum(open_, close) - 0.3,
        "close": close,
    })
    if with_volume:
        frame["volume"] = np.abs(rng.normal(900, 120, rows))
    if columns:
        frame.columns = columns
    else:
        frame.columns = [header_case(c) for c in frame.columns]
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    frame.to_csv(tmp.name, index=False)
    tmp.close()
    return Path(tmp.name)


@contextmanager
def clean_csv_cache():
    saved = dict(csv_source._CACHE)
    csv_source._CACHE.clear()
    try:
        yield
    finally:
        csv_source._CACHE.clear()
        csv_source._CACHE.update(saved)


class ColumnSniffingTests(unittest.TestCase):
    def test_common_exchange_headers_are_mapped(self):
        for names in (
            ["timestamp", "open", "high", "low", "close", "volume"],
            ["time", "Open", "High", "Low", "Close", "Vol"],
            ["Date", "o", "h", "l", "c", "v"],
            ["Gunclosed Time", "Open", "High", "Low", "Close", "Volume"],
        ):
            frame = pd.DataFrame(np.arange(6 * 5, dtype=float).reshape(5, 6), columns=names)
            normalised, mapping = normalize_columns(frame)
            for column in ("open", "high", "low", "close", "volume"):
                self.assertIn(column, normalised.columns, names)
            self.assertTrue(mapping)

    def test_milliseconds_are_understood(self):
        frame = pd.DataFrame({
            "timestamp": [1_700_000_000_000 + i * 900_000 for i in range(40)],
            "open": range(40), "high": range(40), "low": range(40), "close": range(40),
        })
        normalised, _ = normalize_columns(frame)
        parsed = csv_source._parse_timestamps(normalised, "15m")
        self.assertEqual(parsed["timestamp"].iloc[0].year, 2023)
        self.assertLess(abs((parsed["timestamp"].iloc[1] - parsed["timestamp"].iloc[0]).total_seconds() - 900), 1)

    def test_missing_ohlc_is_a_clear_error(self):
        frame = pd.DataFrame({"timestamp": range(10), "close": range(10), "volume": range(10)})
        with self.assertRaises(ValueError) as caught:
            normalize_columns(frame)
        self.assertIn("open", str(caught.exception))

    def test_missing_volume_is_tolerated(self):
        path = make_csv(60, with_volume=False)
        try:
            with clean_csv_cache():
                frame = load_csv(path, "15m", use_cache=False)
            self.assertIn("volume", frame.columns)
            self.assertEqual(float(frame["volume"].sum()), 0.0)
        finally:
            path.unlink(missing_ok=True)


class LoadAndResampleTests(unittest.TestCase):
    def setUp(self):
        self.path = make_csv(240, "15min")

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_load_returns_a_canonical_frame(self):
        with clean_csv_cache():
            frame = load_csv(self.path, use_cache=False)
        self.assertEqual(list(frame.columns[:6]), ["timestamp", "open", "high", "low", "close", "volume"])
        self.assertEqual(len(frame), 240)
        self.assertTrue(frame["timestamp"].is_monotonic_increasing)
        self.assertEqual(frame.attrs["timeframe"], "15m")
        self.assertTrue((frame["high"] >= frame["low"]).all())

    def test_timeframe_is_guessed_from_the_gaps(self):
        with clean_csv_cache():
            frame = load_csv(self.path, use_cache=False)
        self.assertEqual(guess_timeframe(frame), "15m")
        hourly = resample(frame, "1h", "15m")
        self.assertEqual(guess_timeframe(hourly), "1h")

    def test_textual_dates_are_understood_without_being_told_the_timeframe(self):
        # regression: guessing used to diff raw strings and blow up
        with clean_csv_cache():
            frame = load_csv(self.path, use_cache=False)
        self.assertEqual(frame.attrs["timeframe"], "15m")
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(frame["timestamp"]))

    def test_coarser_resample_aggregates_correctly(self):
        with clean_csv_cache():
            frame = load_csv(self.path, use_cache=False)
        hourly = resample(frame, "1h", "15m")
        self.assertEqual(len(hourly), 60)                        # 240 × 15m = 60h
        block = frame.iloc[:4]
        row = hourly.iloc[0]
        self.assertAlmostEqual(row["open"], float(block["open"].iloc[0]))
        self.assertAlmostEqual(row["close"], float(block["close"].iloc[-1]))
        self.assertAlmostEqual(row["high"], float(block["high"].max()))
        self.assertAlmostEqual(row["low"], float(block["low"].min()))
        self.assertAlmostEqual(row["volume"], float(block["volume"].sum()), places=4)

    def test_resampling_to_a_finer_frame_is_refused(self):
        with clean_csv_cache():
            frame = load_csv(self.path, use_cache=False)
        with self.assertRaises(ValueError):
            resample(frame, "5m", "15m")

    def test_too_few_rows_is_an_actionable_error(self):
        tiny = make_csv(12)
        try:
            with clean_csv_cache():
                with self.assertRaises(ValueError) as caught:
                    load_csv(tiny, "15m", use_cache=False)
            self.assertIn("at least 30", str(caught.exception))
        finally:
            tiny.unlink(missing_ok=True)

    def test_missing_file_says_so(self):
        with self.assertRaises(FileNotFoundError):
            load_csv("/nope/nothing.csv", use_cache=False)

    def test_profile_summarises_the_file(self):
        info = profile(self.path)
        self.assertTrue(info["ok"], info)
        self.assertEqual(info["rows"], 240)
        self.assertEqual(info["timeframe"], "15m")
        self.assertIn("start", info)
        self.assertIn("end", info)
        self.assertIn("change_pct", info)

    def test_profile_of_a_broken_file_explains_the_problem(self):
        bad = Path(tempfile.mkstemp(suffix=".csv")[1])
        bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        try:
            info = profile(bad)
            self.assertFalse(info["ok"])
            self.assertIn("error", info)
        finally:
            bad.unlink()

    def test_timeframe_minutes_table(self):
        for label, minutes in (("1m", 1), ("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240), ("1d", 1440)):
            self.assertEqual(timeframe_minutes(label), minutes)
        self.assertEqual(timeframe_minutes("7 minutes"), 7)   # tolerant about wording
        with self.assertRaises(ValueError):
            timeframe_minutes("weekly-ish")


class UploadFolderTests(unittest.TestCase):
    def test_list_csvs_only_returns_csv_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            keep = folder / "my-btc.csv"
            keep.write_text("timestamp,open,high,low,close,volume\n", encoding="utf-8")
            (folder / "notes.txt").write_text("ignore me", encoding="utf-8")
            (folder / "sub.csv").mkdir()
            found = list_csvs(folder)
            self.assertEqual([row["name"] for row in found], ["my-btc.csv"])
            self.assertIn("size_kb", found[0])
            keep.unlink()

    def test_missing_folder_is_not_an_error(self):
        self.assertEqual(list_csvs("/no/such/folder"), [])


class MarketDataSourceTests(unittest.TestCase):
    def setUp(self):
        from tests.support import isolated_cache

        self.enterContext(isolated_cache())
        self.path = make_csv(400, "15min")

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def market(self, **values):
        from config.store import override_settings
        from data.market_data import MarketData

        settings_values = {"data_source": "csv", "csv_path": str(self.path), "csv_timeframe": "15m",
                           "timeframes": "15m,1h,4h", "cache_minutes": 0, **values}
        cm = override_settings(**settings_values)
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        return MarketData()

    def test_csv_source_serves_every_configured_timeframe(self):
        market = self.market()
        base = market.get_ohlcv("BTC", "15m", 100)
        hour = market.get_ohlcv("BTC", "1h", 100)
        four = market.get_ohlcv("BTC", "4h", 100)
        self.assertEqual(market.source, "csv")
        self.assertFalse(market.is_live)
        self.assertGreater(len(base), 0)
        self.assertGreater(len(hour), 0)
        self.assertGreater(len(four), 0)
        gap = lambda frame: (pd.to_datetime(frame["timestamp"]).iloc[1]
                             - pd.to_datetime(frame["timestamp"]).iloc[0]).total_seconds()
        self.assertEqual(gap(base) / 60.0, 15)
        self.assertEqual(gap(hour) / 60.0, 60)
        self.assertEqual(gap(four) / 60.0 / 60.0, 4)
        self.assertAlmostEqual(float(base["close"].iloc[-1]), float(hour["close"].iloc[-1]), places=4)

    def test_resampled_candles_are_aligned_to_their_bucket(self):
        market = self.market()
        hour = market.get_ohlcv("BTC", "1h", 50)
        stamps = pd.to_datetime(hour["timestamp"])
        self.assertTrue(bool((stamps.dt.minute == 0).all()))

    def test_a_timeframe_the_file_cannot_produce_is_not_invented(self):
        market = self.market()
        frame = market.get_ohlcv("BTC", "1m", 50)       # 1m cannot come from 15m bars
        self.assertEqual(market.source, "demo")           # honest fallback, not fake 1m candles
        self.assertIn("1m", str(market._last_error))      # and it says why

    def test_ticker_and_book_come_from_the_file(self):
        market = self.market()
        frame = market.get_ohlcv("BTC", "15m", 100)
        ticker = market.get_ticker("BTC")
        self.assertAlmostEqual(float(ticker["last"]), float(frame["close"].iloc[-1]), places=4)
        self.assertIn("change_pct", ticker)
        self.assertEqual(ticker.get("source"), "csv")     # where the numbers came from
        # a CSV has no order book: the microstructure feed stays empty instead of
        # inventing one, and the liquidity gate then reports "not available"
        self.assertIsNone(market.get_order_book("BTC", 10))

    def test_auto_prefers_the_exchange_but_survives_without_one(self):
        market = self.market(data_source="auto", csv_path="")
        frame = market.get_ohlcv("BTC", "15m", 80)
        self.assertGreater(len(frame), 30)
        self.assertIn(market.source, ("demo", "exchange"))
        self.assertTrue(market.describe())

    def test_demo_source_is_deterministic_per_symbol(self):
        first = self.market(data_source="demo").get_ohlcv("BTC", "15m", 60)
        second = self.market(data_source="demo").get_ohlcv("BTC", "15m", 60)
        other = self.market(data_source="demo").get_ohlcv("ETH", "15m", 60)
        self.assertEqual(len(first), len(second))
        self.assertTrue(np.allclose(first["close"].to_numpy(), second["close"].to_numpy()))
        self.assertFalse(np.allclose(first["close"].to_numpy(), other["close"].to_numpy()))

    def test_supported_timeframes_follow_the_source(self):
        market = self.market()
        self.assertIn("15m", market.supported_timeframes())
        self.assertNotIn("1m", market.supported_timeframes())

    def test_describe_reports_the_file_behind_the_data(self):
        market = self.market()
        market.get_ohlcv("BTC", "15m", 20)
        info = market.describe()
        self.assertEqual(info["used"], "csv")
        self.assertFalse(info["live"])
        self.assertIn(self.path.name, str(info["csv_path"]))

    def test_bad_csv_path_degrades_visibly_instead_of_crashing(self):
        market = self.market(csv_path="/no/such/file.csv")
        frame = market.get_ohlcv("BTC", "15m", 60)
        self.assertGreater(len(frame), 0)                 # analysis still has data to chew on
        self.assertNotEqual(market.source, "csv")          # ...and we do not pretend it is yours
        self.assertTrue(market.describe()["csv_error"] or market._last_error)


if __name__ == "__main__":
    unittest.main()
