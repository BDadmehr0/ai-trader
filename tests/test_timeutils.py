"""utils.timeutils — one timestamp resolution for every frame.

pandas 3 refuses to merge `datetime64[ms, UTC]` with `datetime64[s, UTC]`
(`MergeError: incompatible merge keys ... must be the same type`), so every OHLCV
frame is normalised to `datetime64[ms, UTC]`. These tests pin that behaviour.
"""

import unittest

import pandas as pd

from utils.timeutils import TIMESTAMP_DTYPE, is_canonical, normalize_timestamps, to_utc_ms


def stamps(unit="s", n=3):
    return pd.Series(pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")).astype(
        f"datetime64[{unit}, UTC]"
    )


class ToUtcMsTests(unittest.TestCase):
    def test_every_resolution_lands_on_the_canonical_dtype(self):
        for unit in ("s", "ms", "us", "ns"):
            converted = to_utc_ms(stamps(unit))
            self.assertEqual(str(converted.dtype), TIMESTAMP_DTYPE, unit)
            pd.testing.assert_series_equal(converted, stamps("ms"))

    def test_naive_input_is_treated_as_utc(self):
        naive = pd.Series(pd.date_range("2026-01-01", periods=3, freq="15min"))
        converted = to_utc_ms(naive)
        self.assertEqual(str(converted.dtype), TIMESTAMP_DTYPE)
        self.assertEqual(str(converted.dt.tz), "UTC")
        pd.testing.assert_series_equal(converted, stamps("ms"))

    def test_garbage_becomes_nat_instead_of_raising(self):
        converted = to_utc_ms(pd.Series(["not a date", None, "2026-01-01T00:00:00Z"]))
        self.assertEqual(str(converted.dtype), TIMESTAMP_DTYPE)
        self.assertTrue(pd.isna(converted.iloc[0]))
        self.assertEqual(converted.iloc[2], pd.Timestamp("2026-01-01T00:00:00Z"))

    def test_is_canonical_only_accepts_the_canonical_dtype(self):
        self.assertTrue(is_canonical(stamps("ms")))
        self.assertFalse(is_canonical(stamps("s")))
        self.assertFalse(is_canonical(pd.Series([1, 2, 3])))


class NormalizeFrameTests(unittest.TestCase):
    def test_frames_from_different_sources_can_be_merged(self):
        left = pd.DataFrame({"timestamp": stamps("ms"), "close": [1.0, 2.0, 3.0]})
        right = pd.DataFrame({"timestamp": stamps("s"), "close": [9.0, 9.0, 9.0]})

        self.assertRaises(Exception, pd.merge_asof, left, right, on="timestamp")

        merged = pd.merge_asof(normalize_timestamps(left), normalize_timestamps(right),
                               on="timestamp", direction="backward")
        self.assertEqual(len(merged), 3)
        self.assertEqual(str(merged["timestamp"].dtype), TIMESTAMP_DTYPE)

    def test_original_frame_is_left_alone_by_default(self):
        frame = pd.DataFrame({"timestamp": stamps("us")})
        normalized = normalize_timestamps(frame)
        self.assertEqual(str(normalized["timestamp"].dtype), TIMESTAMP_DTYPE)
        self.assertEqual(str(frame["timestamp"].dtype), "datetime64[us, UTC]")

    def test_inplace_mutates_and_returns_the_same_frame(self):
        frame = pd.DataFrame({"timestamp": stamps("us")})
        self.assertIs(normalize_timestamps(frame, inplace=True), frame)
        self.assertEqual(str(frame["timestamp"].dtype), TIMESTAMP_DTYPE)

    def test_frames_without_timestamps_pass_through(self):
        frame = pd.DataFrame({"close": [1.0, 2.0]})
        self.assertIs(normalize_timestamps(frame), frame)
        self.assertIsNone(normalize_timestamps(None))


if __name__ == "__main__":
    unittest.main()
