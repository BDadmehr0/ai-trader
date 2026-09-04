"""Quality gates, trade construction and level detection."""

import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from analysis.gates import evaluate_gates
from analysis.levels import find_market_levels, nearest_zone_info
from analysis.risk import create_trade_setup, liquidation_distance, stop_is_safe
from config.store import override_settings


def snapshot(**values):
    base = dict(rsi=52.0, macd_histogram=1.0, macd_cross="BULLISH", volume_ratio=1.6,
                structure_trend="BULLISH", adx=28.0, bb_squeeze=False, overextension_pct=0.4,
                volatility_regime="NORMAL", atr=10.0, atr_pct=1.0, atr_ratio=1.0,
                volume_zscore=1.2, price=1000.0, trend="BULLISH", trend_strength="STRONG",
                supertrend_dir=1.0, ema_fast=995.0, ema_mid=990.0, vwap=998.0,
                vwap_dist_pct=0.2, mfi=60.0, cci=40.0, alignment=2)
    base.update(values)
    return base


def news_stub(*, available=True, veto=None, sentiment=0.0):
    return SimpleNamespace(available=available, veto=veto or {}, sentiment=sentiment,
                           bias="NEUTRAL", score=0.0, reliability=0.8, status="OK")


def derivs_stub(**values):
    base = dict(available=True, liquidity_ok=True, gates=[], score=0.0, funding_rate=0.0,
                ls_bias=0.0, crowd_state="BALANCED", oi_change_pct=0.0, funding_crowded=0.0)
    base.update(values)
    return SimpleNamespace(**base)


def cross_stub(**values):
    base = dict(available=True, opposes_long=False, opposes_short=False, btc_regime="BULLISH",
                correlation=0.8, relaxation=1.0, score=0.0)
    base.update(values)
    return SimpleNamespace(**base)


def setup_stub(**values):
    base = dict(risk_reward_1=2.0, status="LONG SETUP", take_profit_1=1020.0, entry=1000.0,
                stop_loss=990.0)
    base.update(values)
    return SimpleNamespace(**base)


class GateTests(unittest.TestCase):
    def run_gates(self, proposal="LONG", confidence=70, *, primary=None, mid=None, news=None,
                  derivatives=None, cross_asset=None, setup=None, enable_risk_gates=True, **settings):
        values = dict(adx_trend_min=20, min_volume_ratio=1.0, min_confidence=45,
                      require_trend_alignment=2, min_risk_reward=1.0, max_overextension_pct=3.0,
                      allow_longs=True, allow_shorts=True, rsi_long_min=30, rsi_long_max=72,
                      rsi_short_min=28, rsi_short_max=70, ema_fast=20, tf_mid="1h")
        values.update(settings)
        with override_settings(**values):
            return evaluate_gates(
                proposal=proposal,
                confidence=confidence,
                primary=snapshot(**(primary or {})),
                mid=snapshot(**(mid or {})),
                news=news,
                derivatives=derivatives,
                cross_asset=cross_asset,
                setup=setup if setup is not None else setup_stub(),
                alignment={"BULLISH": 2, "BEARISH": 1, "NEUTRAL": 0, "total": 3},
                enable_risk_gates=enable_risk_gates,
            )

    def keys(self, result):
        payload = result.to_dict() if hasattr(result, "to_dict") else result
        return {gate["key"]: gate for gate in payload["gates"]}

    def test_clean_setup_passes(self):
        result = self.run_gates()
        payload = result.to_dict()
        self.assertFalse(payload["blocked"], payload["blocked_by"])
        self.assertEqual(payload["signal"], "LONG")
        self.assertGreaterEqual(payload["passed"], 8)
        self.assertEqual(payload["total"], payload["passed"])

    def test_no_gates_are_evaluated_for_a_wait(self):
        payload = self.run_gates("WAIT").to_dict()
        self.assertEqual(payload["gates"], [])
        self.assertFalse(payload["blocked"])

    def test_confidence_floor_is_a_warning_not_a_block(self):
        payload = self.run_gates(confidence=20).to_dict()
        self.assertIn("confidence", self.keys(payload))
        self.assertEqual(self.keys(payload)["confidence"]["status"], "FAIL")
        self.assertFalse(payload["blocked"])
        self.assertTrue(payload["warnings"])
        self.assertLess(payload["confidence"], 20)

    def test_low_volume_warns(self):
        gates = self.keys(self.run_gates(primary={"volume_ratio": 0.3}).to_dict())
        self.assertEqual(gates["volume"]["status"], "FAIL")
        self.assertIn("0.30x", gates["volume"]["note"])

    def test_chasing_an_overextended_move_fails_the_gate(self):
        gates = self.keys(self.run_gates(mid={"overextension_pct": 9.0}).to_dict())
        self.assertEqual(gates["overextension"]["status"], "FAIL")

    def test_overextension_in_your_favour_is_fine(self):
        gates = self.keys(self.run_gates(mid={"overextension_pct": -9.0}).to_dict())
        self.assertEqual(gates["overextension"]["status"], "PASS")

    def test_weak_trend_market_is_filtered(self):
        gates = self.keys(self.run_gates(primary={"adx": 8.0}).to_dict())
        self.assertEqual(gates["adx"]["status"], "FAIL")
        # ...but a breakout out of a squeeze is allowed through
        gates = self.keys(self.run_gates(primary={"adx": 8.0, "bb_squeeze": True}).to_dict())
        self.assertEqual(gates["adx"]["status"], "PASS")

    def test_conflicting_structure_fails(self):
        gates = self.keys(self.run_gates(primary={"structure_trend": "BEARISH"}).to_dict())
        self.assertEqual(gates["structure"]["status"], "FAIL")

    def test_disabled_direction_is_a_hard_block(self):
        payload = self.run_gates(allow_longs=False).to_dict()
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["signal"], "NO_TRADE")
        self.assertIn("direction", self.keys(payload))

    def test_extreme_volatility_blocks(self):
        payload = self.run_gates(primary={"volatility_regime": "EXTREME"}).to_dict()
        self.assertEqual(self.keys(payload)["volatility"]["status"], "FAIL")
        self.assertTrue(payload["blocked"])

    def test_bad_liquidity_blocks(self):
        payload = self.run_gates(derivatives=derivs_stub(liquidity_ok=False,
                                                          gates=["spread 0.9% too wide"])).to_dict()
        gates = self.keys(payload)
        self.assertEqual(gates["liquidity"]["status"], "FAIL")
        self.assertTrue(payload["blocked"])
        self.assertIn("spread", gates["liquidity"]["note"])

    def test_risk_gates_can_be_switched_off_for_backtesting(self):
        payload = self.run_gates(derivatives=derivs_stub(liquidity_ok=False),
                                 enable_risk_gates=False).to_dict()
        self.assertNotIn("liquidity", self.keys(payload))
        self.assertNotIn("risk_reward", self.keys(payload))
        self.assertFalse(payload["blocked"])

    def test_target_behind_a_wall_is_reported(self):
        payload = self.run_gates(setup=setup_stub(status="WAIT - RESISTANCE NEARBY")).to_dict()
        self.assertEqual(self.keys(payload)["target_clear"]["status"], "FAIL")

    def test_blocking_news_veto_kills_the_trade(self):
        news = news_stub(veto={"triggered": True, "blocking": True, "opposes": "LONG",
                              "note": "extreme bearish news"})
        payload = self.run_gates(news=news).to_dict()
        self.assertEqual(self.keys(payload)["news"]["status"], "FAIL")
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["signal"], "NO_TRADE")

    def test_non_blocking_news_only_warns(self):
        news = news_stub(veto={"triggered": True, "blocking": False, "opposes": "LONG",
                              "note": "news is bearish"})
        payload = self.run_gates(news=news).to_dict()
        self.assertEqual(self.keys(payload)["news"]["status"], "FAIL")
        self.assertFalse(payload["blocked"])
        self.assertEqual(payload["signal"], "LONG")

    def test_news_aligned_with_the_trade_passes(self):
        news = news_stub(veto={"triggered": True, "blocking": True, "opposes": "SHORT",
                              "note": "extreme bullish news"})
        payload = self.run_gates(news=news).to_dict()
        self.assertEqual(self.keys(payload)["news"]["status"], "PASS")

    def test_missing_news_is_skipped_not_failed(self):
        payload = self.run_gates(news=news_stub(available=False, veto={})).to_dict()
        self.assertEqual(self.keys(payload)["news"]["status"], "SKIP")

    def test_btc_regime_opposition_warns(self):
        payload = self.run_gates(cross_asset=cross_stub(opposes_long=True)).to_dict()
        self.assertEqual(self.keys(payload)["btc_regime"]["status"], "FAIL")
        self.assertFalse(payload["blocked"])

    def test_confidence_penalty_is_capped(self):
        # four soft warnings on a still-tradeable setup: -4 each, capped at -25
        weak = {"rsi": 95.0, "adx": 1.0, "volume_ratio": 0.1, "overextension_pct": 99.0}
        payload = self.run_gates(confidence=90, primary=weak, mid=weak).to_dict()
        self.assertEqual(len(payload["warnings"]), 4)
        self.assertEqual(payload["confidence"], 90 - 4 * 4)
        self.assertFalse(payload["blocked"])
        # ...and the cap holds even with many more warnings
        many = dict(weak, structure_trend="BEARISH")
        crowded = self.run_gates(confidence=90, primary=many, mid=many).to_dict()
        self.assertGreaterEqual(len(crowded["warnings"]), 5)
        self.assertGreaterEqual(crowded["confidence"], 90 - 25)

    def test_short_side_uses_the_short_thresholds(self):
        short = {"rsi": 90.0, "structure_trend": "BEARISH", "macd_histogram": -1.0}
        payload = self.run_gates("SHORT", primary=short, mid=short,
                                 setup=setup_stub(status="SHORT SETUP")).to_dict()
        gates = self.keys(payload)
        self.assertEqual(gates["rsi_zone"]["status"], "FAIL")   # 90 is not a short entry
        self.assertEqual(gates["direction"]["status"], "PASS")
        self.assertEqual(gates["macd"]["status"], "PASS")       # negative histogram supports a short
        ok = {"rsi": 45.0, "structure_trend": "BEARISH", "macd_histogram": -1.0}
        self.assertEqual(self.keys(self.run_gates("SHORT", primary=ok, mid=ok))[ "rsi_zone"]["status"], "PASS")

    def test_payload_shape_matches_the_ui_contract(self):
        payload = self.run_gates().to_dict()
        for key in ("gates", "signal", "proposal", "confidence", "blocked", "blocked_by",
                    "warnings", "notes", "passed", "total"):
            self.assertIn(key, payload, key)
        for gate in payload["gates"]:
            self.assertEqual(sorted(gate), ["blocking", "key", "label", "note", "status"])
            self.assertIn(gate["status"], ("PASS", "FAIL", "SKIP"))


class RiskTests(unittest.TestCase):
    BASE = dict(price=100.0, atr=2.0, support=96.0, resistance=108.0, confidence=70)

    def test_long_stop_sits_below_entry_and_targets_above(self):
        setup = create_trade_setup("LONG", **self.BASE)
        self.assertEqual(setup.signal, "LONG")
        self.assertLess(setup.stop_loss, setup.entry)
        self.assertGreater(setup.take_profit_1, setup.entry)
        self.assertGreater(setup.take_profit_2, setup.take_profit_1)
        self.assertGreater(setup.risk_reward_1, 0)
        self.assertGreater(setup.risk_reward_2, setup.risk_reward_1)

    def test_short_is_the_mirror_image(self):
        long_side = create_trade_setup("LONG", **self.BASE)
        short_side = create_trade_setup("SHORT", price=100.0, atr=2.0, support=92.0,
                                        resistance=104.0, confidence=70)
        self.assertGreater(short_side.stop_loss, short_side.entry)
        self.assertLess(short_side.take_profit_1, short_side.entry)
        self.assertAlmostEqual(long_side.stop_distance_pct, short_side.stop_distance_pct, places=1)

    def test_waiting_produces_no_numbers(self):
        setup = create_trade_setup("WAIT", **self.BASE)
        self.assertEqual(setup.status, "NO TRADE")
        self.assertEqual(setup.take_profit_1, 0.0)
        self.assertEqual(setup.position_size, 0.0)
        self.assertIn("no active setup", setup.notes)

    def test_position_size_risks_the_configured_fraction(self):
        with override_settings(risk_per_trade=1.0, initial_balance=10_000, leverage=2.0):
            setup = create_trade_setup("LONG", **self.BASE)
        self.assertAlmostEqual(setup.risk_amount, 100.0, places=2)
        self.assertGreater(setup.position_size, 0.0)
        self.assertAlmostEqual(setup.notional, setup.position_size * setup.entry, places=2)
        self.assertLessEqual(setup.notional, 10_000 * 2.0 + 1e-6)

    def test_a_wider_stop_buys_less_size(self):
        with override_settings(risk_per_trade=1.0, initial_balance=10_000):
            tight = create_trade_setup("LONG", price=100.0, atr=1.0, support=99.5,
                                       resistance=108.0, confidence=70)
            loose = create_trade_setup("LONG", price=100.0, atr=6.0, support=92.0,
                                       resistance=120.0, confidence=70)
        self.assertGreater(tight.position_size, loose.position_size)
        self.assertAlmostEqual(tight.risk_amount, loose.risk_amount, places=1)

    def test_leverage_beyond_liquidation_is_reported(self):
        with override_settings(leverage=50.0, maintenance_margin=0.005, initial_balance=10_000):
            setup = create_trade_setup("LONG", price=100.0, atr=6.0, support=94.0,
                                       resistance=110.0, confidence=70)
        self.assertTrue(setup.notes)
        self.assertGreater(liquidation_distance(100.0, 94.0, 50.0, 0.005), 0)
        self.assertFalse(stop_is_safe(100.0, 94.0, 50.0, 0.005))
        self.assertTrue(stop_is_safe(100.0, 80.0, 3.0, 0.005))

    def test_zero_sum_inputs_are_survivable(self):
        for values in (dict(price=0.0, atr=0.0, support=0.0, resistance=0.0, confidence=0),
                       dict(price=100.0, atr=-1.0, support=None, resistance=None, confidence=50)):
            setup = create_trade_setup("LONG", **values)
            self.assertIsInstance(setup.entry, float)

    def test_rounding_follows_the_price_magnitude(self):
        big = create_trade_setup("LONG", price=30_000.0, atr=400.0, support=29_000.0,
                                 resistance=31_500.0, confidence=70)
        small = create_trade_setup("LONG", price=0.0421, atr=0.0012, support=0.040,
                                   resistance=0.0455, confidence=70)
        self.assertEqual(big.entry, round(big.entry, 2))
        self.assertNotEqual(small.stop_loss, round(small.stop_loss, 2))   # more precision for pennies
        self.assertGreater(small.stop_loss, 0)

    def test_stop_modes(self):
        with override_settings(stop_mode="atr"):
            atr_stop = create_trade_setup("LONG", **self.BASE)
        with override_settings(stop_mode="structure"):
            structure_stop = create_trade_setup("LONG", **self.BASE)
        self.assertNotAlmostEqual(atr_stop.stop_loss, structure_stop.stop_loss, places=2)
        self.assertLess(structure_stop.stop_loss, atr_stop.stop_loss)   # below the swing low

    def test_liquidation_risk_is_flagged_in_the_notes(self):
        with override_settings(leverage=50.0, maintenance_margin=0.005):
            tight = create_trade_setup("LONG", price=100.0, atr=6.0, support=112.0,
                                       resistance=140.0, confidence=70)
        self.assertTrue(any("liquidated" in note for note in tight.notes), tight.notes)

    def test_setup_dict_carries_the_journal_and_ui_fields(self):
        payload = create_trade_setup("LONG", **self.BASE).to_dict()
        for key in ("signal", "status", "entry", "stop_loss", "take_profit_1", "take_profit_2",
                    "risk_reward_1", "risk_reward_2", "confidence", "stop_mode", "target_mode",
                    "stop_distance", "stop_distance_pct", "risk_amount", "position_size",
                    "notional", "margin_required", "notes"):
            self.assertIn(key, payload, key)


class LevelsTests(unittest.TestCase):
    def frame(self, levels=(100.0, 110.0), touches=6, rows=240, noise=0.4):
        rng = np.random.default_rng(11)
        anchors = np.array(levels)
        picks = rng.integers(0, len(anchors), rows)
        close = anchors[picks] + rng.normal(0, noise, rows)
        high = close + np.abs(rng.normal(0.25, 0.1, rows))
        low = close - np.abs(rng.normal(0.25, 0.1, rows))
        return pd.DataFrame({
            "timestamp": pd.date_range("2026-02-01", periods=rows, freq="15min", tz="UTC"),
            "open": close, "high": high, "low": low, "close": close,
            "volume": np.abs(rng.normal(500, 50, rows)),
        })

    def test_levels_cluster_repeated_touches(self):
        levels = find_market_levels(self.frame(), lookback=240, order=2)
        self.assertGreater(levels.support_1, 0)
        self.assertGreater(levels.resistance_1, levels.support_1)
        self.assertGreater(levels.resistance_2, levels.resistance_1)
        self.assertLess(levels.support_2, levels.support_1)
        self.assertIn(levels.support_1_strength, ("WEAK", "MODERATE", "STRONG"))
        prices = [zone["price"] for zone in levels.zones]
        self.assertEqual(len(prices), len(set(round(p, 1) for p in prices)))  # one row per cluster
        for zone in levels.zones:
            self.assertIn(zone["type"], ("SUPPORT", "RESISTANCE"))
            self.assertGreater(zone["touches"], 0)

    def test_swing_points_are_reported_for_structural_stops(self):
        levels = find_market_levels(self.frame(), lookback=240, order=2)
        self.assertIsNotNone(levels.last_swing_low)
        self.assertIsNotNone(levels.last_swing_high)
        self.assertLess(levels.last_swing_low, levels.last_swing_high)

    def test_nearest_zone_distances_are_magnitudes(self):
        levels = find_market_levels(self.frame(levels=(96.0, 118.0)), lookback=240, order=2)
        info = nearest_zone_info(levels, 100.0)
        self.assertGreater(info["resistance_distance_pct"], 0)
        self.assertGreater(info["support_distance_pct"], 0)
        self.assertIn("resistance_strength", info)
        self.assertEqual(nearest_zone_info(None, 100.0), {})
        self.assertEqual(nearest_zone_info(levels, 0.0), {})

    def test_empty_frame_is_handled(self):
        levels = find_market_levels(pd.DataFrame())
        self.assertEqual(levels.support_1, 0.0)
        self.assertEqual(levels.resistance_1, 0.0)
        self.assertEqual(levels.zones, [])


if __name__ == "__main__":
    unittest.main()
