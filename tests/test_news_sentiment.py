"""News sentiment: lexicon scoring, local-LLM path, fallbacks, veto, caching.

Nothing here touches the network — RSS/LLM calls are stubbed, and the cache is
pointed at a temporary folder.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.support import isolated_cache

from analysis.news import analyze_news, config_fingerprint, llm_config
from analysis.news.lexicon import explain, score_text
from analysis.news.llm import LlmError, parse_scores
from analysis.news.sources import NewsItem
from config.store import get_settings, override_settings


def feat_score(result):
    """The number the scorer actually consumes."""
    return result.score


def item(headline, *, source="test-feed", hours_ago=1.0, summary="", url=None):
    return NewsItem(
        headline=headline,
        source=source,
        url=url or f"https://example.com/{abs(hash(headline)) % 10_000}",
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        summary=summary,
    )


BULLISH = [
    "Bitcoin ETF sees record inflows as institutional demand surges",
    "BlackRock increases bitcoin holdings, biggest accumulation this year",
]
BEARISH = [
    "SEC sues exchange over fraud charges, bitcoin crashes as liquidations spike",
    "Massive hack drains billions from lending protocol, market panics and sells off",
]
NEUTRAL = [
    "How to set up a hardware wallet in five steps",
    "Developer publishes open-source charting library",
]


class LexiconTests(unittest.TestCase):
    def test_bullish_words_score_positive(self):
        score, hits, label = score_text("Bitcoin ETF inflows surge, record accumulation")
        self.assertGreater(score, 0.1)
        self.assertTrue(hits)
        self.assertEqual(label, "BULLISH")

    def test_bearish_words_score_negative(self):
        score, hits, _ = score_text("Exchange hacked, billions drained, panic selling and liquidations")
        self.assertLess(score, -0.1)
        self.assertTrue(hits)

    def test_negation_is_understood(self):
        positive, _, _ = score_text("infl surge and record gains")
        dampened, _, _ = score_text("no infl surge, gains fail and stall")
        self.assertLess(dampened, positive)

    def test_neutral_text_is_not_forced_into_a_direction(self):
        score, hits, _ = score_text("Weekly newsletter about community events")
        self.assertAlmostEqual(score, 0.0, places=6)
        self.assertEqual(hits, [])

    def test_extra_aliases_extend_the_symbol_filter(self):
        from analysis.news.sources import symbol_keywords

        keywords = symbol_keywords("SOL", {"SOL": ["zk rollup"], "BTC": ["ignored"]})
        self.assertIn("zk rollup", keywords)
        self.assertNotIn("ignored", keywords)
        self.assertIn("solana", keywords)                    # built-in alias kept
        self.assertEqual(sorted(symbol_keywords("SOL", ["plain", "list"])), ["list", "plain", "sol", "solana"])

    def test_explain_is_human_readable(self):
        self.assertIn("+", explain("bitcoin etf inflow record"))


class NewsPipelineTests(unittest.TestCase):
    def setUp(self):
        self.cache = self.enterContext(isolated_cache())
        self.base = {
            "news_enabled": True,
            "news_provider": "lexicon",
            "rss_feeds": ["https://example.com/feed"],
            "cryptopanic_enabled": False,
            "fear_greed_enabled": False,
            "symbol_relevance_only": False,
            "news_min_items": 1,
            "news_cache_ttl": 900,
            "news_veto_mode": "ignore",
        }

    def analyze(self, items, *, overrides=None, symbol="BTC", **kwargs):
        notes = []

        def fake_fetch(feeds, timeout=8.0, proxy=None):
            notes.append(len(feeds))
            return list(items), []

        settings_values = {**self.base, **(overrides or {})}
        with override_settings(**settings_values), \
                mock.patch("analysis.news.fetch_rss", side_effect=fake_fetch):
            kwargs.setdefault("force", True)         # one fresh fetch per call
            return analyze_news(symbol, **kwargs)

    def test_bullish_headlines_produce_a_positive_bias(self):
        result = self.analyze([item(head) for head in BULLISH])
        self.assertEqual(result.status, "OK")
        self.assertTrue(result.available)
        self.assertEqual(result.bias, "BULLISH")
        self.assertGreater(result.sentiment, 0.2)
        self.assertGreater(result.score, 0.0)
        self.assertTrue(all(entry["method"] == "lexicon" for entry in result.items))

    def test_bearish_headlines_produce_a_negative_bias(self):
        result = self.analyze([item(head) for head in BEARISH])
        self.assertEqual(result.bias, "BEARISH")
        self.assertLess(result.sentiment, -0.2)
        self.assertLess(result.score, 0.0)

    def test_mixed_noise_cancels_out(self):
        result = self.analyze([item(head) for head in BULLISH[:1] + BEARISH[:1]])
        self.assertLess(abs(result.sentiment), 0.6)
        self.assertGreaterEqual(result.bullish_count, 1)
        self.assertGreaterEqual(result.bearish_count, 1)

    def test_stale_news_is_trusted_less(self):
        old = self.analyze([item(h, hours_ago=90) for h in BULLISH])
        fresh = self.analyze([item(h, hours_ago=0.2) for h in BULLISH])
        self.assertGreater(fresh.reliability, old.reliability)
        self.assertGreater(fresh.confidence, old.confidence)
        self.assertGreater(fresh.stats["freshness"], 0.9)
        self.assertLess(old.stats["freshness"], 0.1)
        self.assertLess(abs(feat_score(old)), abs(feat_score(fresh)) + 1e9)

    def test_short_window_half_life_honours_the_setting(self):
        slow = self.analyze([item(BULLISH[0], hours_ago=30)], overrides={"recency_half_life_hours": 200})
        fast = self.analyze([item(BULLISH[0], hours_ago=30)], overrides={"recency_half_life_hours": 2})
        self.assertGreater(slow.stats["freshness"], fast.stats["freshness"])

    def test_symbol_relevance_only_keeps_asset_headlines(self):
        on_sol = self.analyze([item(h) for h in BULLISH],
                              overrides={"symbol_relevance_only": True}, symbol="SOL")
        on_btc = self.analyze([item(h) for h in BULLISH],
                              overrides={"symbol_relevance_only": True}, symbol="BTC")
        self.assertEqual(on_btc.symbol_count, len(BULLISH))     # "bitcoin" is in both headlines
        self.assertEqual(on_sol.symbol_count, 0)                # nothing here is about SOL
        # macro context is still kept (that is the documented fallback), but it
        # is not counted as symbol news
        self.assertEqual(on_sol.item_count, len(BULLISH))
        self.assertLess(abs(on_sol.sentiment), abs(on_btc.sentiment) + 1.0)

    def test_no_matching_headlines_is_reported_not_fabricated(self):
        result = self.analyze([], overrides={"symbol_relevance_only": False})
        self.assertFalse(result.available)
        self.assertIn(result.status, ("NO_DATA", "OFFLINE"))
        self.assertEqual(result.score, 0.0)

    def test_low_sample_size_lowers_confidence(self):
        single = self.analyze([item(BULLISH[0])], overrides={"news_min_items": 4})
        many = self.analyze([item(head) for head in (BULLISH + BEARISH)],
                            overrides={"news_min_items": 3})
        self.assertEqual(single.status, "LOW_SAMPLE")
        self.assertEqual(many.status, "OK")
        self.assertLess(single.confidence, many.confidence)

    def test_disabled_settings_short_circuit(self):
        with override_settings(news_enabled=False):
            result = analyze_news("BTC")
        self.assertFalse(result.enabled)
        self.assertEqual(result.status, "DISABLED")

    def test_provider_off_is_the_same_as_disabled(self):
        result = self.analyze([item(h) for h in BULLISH], overrides={"news_provider": "off"})
        self.assertFalse(result.available)

    def test_fear_and_greed_is_included_when_available(self):
        def fake_fg(limit=5, timeout=8.0, proxy=None, **kwargs):
            return {"value": 74.0, "label": "Greed", "sentiment": 0.48,
                    "trend": "RISING", "history": [{"value": 74.0, "label": "Greed"}],
                    "updated": datetime.now(timezone.utc)}, None

        with mock.patch("analysis.news.fetch_fear_greed", side_effect=fake_fg):
            result = self.analyze([item(h) for h in BULLISH], overrides={"fear_greed_enabled": True})
        self.assertEqual(result.fear_greed["value"], 74.0)

    def test_payload_is_json_serialisable(self):
        payload = self.analyze([item(h) for h in BULLISH]).to_dict()
        text = json.dumps(payload)
        for key in ("sentiment", "bias", "items", "veto", "status", "provider"):
            self.assertIn(key, payload, text[:200])

    def test_impact_scales_with_strength(self):
        weak = self.analyze([item("Weekly community newsletter")])
        strong = self.analyze([item(head) for head in BEARISH])
        self.assertEqual(weak.impact, "NONE")
        self.assertLess(strong.sentiment, weak.sentiment)
        self.assertIn(strong.impact, ("WEAK", "MODERATE", "STRONG"))


class VetoTests(unittest.TestCase):
    def setUp(self):
        self.cache = self.enterContext(isolated_cache())

    def run_case(self, mode, headlines):
        items = [item(head) for head in headlines]
        values = {
            "news_enabled": True, "news_provider": "lexicon", "rss_feeds": ["f"],
            "cryptopanic_enabled": False, "fear_greed_enabled": False,
            "symbol_relevance_only": False, "news_min_items": 1, "news_cache_ttl": 900,
            "news_veto_mode": mode, "news_veto_threshold": 0.3,
        }
        with override_settings(**values), mock.patch("analysis.news.fetch_rss", return_value=(items, [])):
            return analyze_news("BTC")

    def test_extreme_bearish_news_vetoes_longs_in_every_active_mode(self):
        for mode in ("downgrade", "block"):
            result = self.run_case(mode, BEARISH)
            self.assertEqual(result.veto["mode"], mode)
            self.assertTrue(result.veto["triggered"], mode)
            self.assertEqual(result.veto["opposes"], "LONG", mode)   # bearish news opposes longs
            self.assertEqual(result.veto["blocking"], mode == "block", mode)
            self.assertEqual(result.veto["threshold_bonus"], 0 if mode == "block" else 12.0, mode)

    def test_off_mode_never_vetoes(self):
        result = self.run_case("off", BEARISH)
        self.assertFalse(result.veto["triggered"])
        self.assertEqual(result.veto["note"], "news guard off")

    def test_quiet_news_leaves_the_guard_alone(self):
        result = self.run_case("block", NEUTRAL)
        self.assertFalse(result.veto["triggered"])
        self.assertEqual(result.veto["opposes"], None)

    def test_single_headline_is_still_reported_with_its_sample_size(self):
        result = self.run_case("block", BEARISH[:1])
        self.assertGreaterEqual(result.item_count, 1)

    def test_bullish_news_vetoes_shorts_instead(self):
        result = self.run_case("block", BULLISH)
        self.assertTrue(result.veto["triggered"])
        self.assertEqual(result.veto["opposes"], "SHORT")


class LlmTests(unittest.TestCase):
    def setUp(self):
        self.cache = self.enterContext(isolated_cache())
        self.values = {
            "news_enabled": True, "rss_feeds": ["f"], "cryptopanic_enabled": False,
            "fear_greed_enabled": False, "symbol_relevance_only": False, "news_min_items": 1,
            "news_cache_ttl": 900, "news_veto_mode": "downgrade",
            "news_provider": "ollama", "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "llama3.1", "llm_timeout": 5.0, "llm_batch_size": 12,
        }

    def test_config_for_ollama_and_openai_compatible_endpoints(self):
        with override_settings(news_provider="ollama", ollama_url="http://box:11434", ollama_model="qwen2.5:3b"):
            cfg = llm_config(get_settings(), "BTC")
            self.assertEqual(cfg.provider, "ollama")
            self.assertEqual(cfg.base_url.rstrip("/"), "http://box:11434")
            self.assertEqual(cfg.model, "qwen2.5:3b")
        with override_settings(news_provider="openai", openai_base_url="http://localhost:1234/v1",
                               openai_model="lmstudio", openai_api_key="abc"):
            cfg = llm_config(get_settings(), "BTC")
            self.assertEqual(cfg.provider, "openai")
            self.assertEqual(cfg.api_key, "abc")
            self.assertNotIn("api_key", cfg.to_dict())   # never leaked to the UI/logs

    def test_model_scores_are_used_when_the_reply_is_valid(self):
        reply = json.dumps({"scores": [{"i": 1, "s": -0.9, "t": "regulatory crackdown"},
                                       {"i": 2, "s": -0.8, "t": "lawsuit risk"}]})
        with override_settings(**self.values), \
                mock.patch("analysis.news.fetch_rss", return_value=([item(h) for h in BEARISH], [])), \
                mock.patch("analysis.news.llm._chat", return_value=reply):
            result = analyze_news("BTC")
        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.model, "llama3.1")
        self.assertTrue(all(entry["method"] == "llm" for entry in result.items))
        self.assertLess(result.sentiment, -0.5)

    def test_llm_can_flip_a_lexicon_read_if_it_disagrees(self):
        # lexicon sees "record"/"surge" (positive); the model says it is hype (0.0)
        reply = json.dumps({"scores": [{"i": 1, "s": 0.0, "t": "promotional"}, {"i": 2, "s": 0.0, "t": "no impact"}]})
        items = [item(h) for h in BULLISH]
        with self.enterContext(isolated_cache()), override_settings(**self.values), \
                mock.patch("analysis.news.fetch_rss", return_value=(items, [])), \
                mock.patch("analysis.news.llm._chat", return_value=reply):
            llm_result = analyze_news("BTC", force=True)
        with self.enterContext(isolated_cache()), \
                override_settings(**{**self.values, "news_provider": "lexicon"}), \
                mock.patch("analysis.news.fetch_rss", return_value=(items, [])):
            lexicon_result = analyze_news("BTC", force=True)
        self.assertAlmostEqual(llm_result.sentiment, 0.0, places=2)
        self.assertGreater(lexicon_result.sentiment, 0.2)

    def test_unreachable_model_falls_back_to_the_lexicon(self):
        with override_settings(**{**self.values, "llm_timeout": 0.05,
                                  "ollama_url": "http://127.0.0.1:9"}), \
                mock.patch("analysis.news.fetch_rss", return_value=([item(h) for h in BEARISH], [])):
            result = analyze_news("BTC", force=True)
        self.assertTrue(result.available)
        self.assertEqual(result.stats.get("engine"), "lexicon")
        self.assertTrue(any("lexicon" in note for note in result.notes), result.notes)
        self.assertLess(result.sentiment, 0)

    def test_unparsable_reply_is_a_fallback_not_a_crash(self):
        with override_settings(**self.values), \
                mock.patch("analysis.news.fetch_rss", return_value=([item(h) for h in BEARISH], [])), \
                mock.patch("analysis.news.llm._chat", return_value="sorry, I cannot analyse markets"):
            result = analyze_news("BTC", force=True)
        self.assertTrue(result.available)
        self.assertLess(result.sentiment, 0)

    def test_ping_reports_a_clear_error(self):
        from analysis.news.llm import ping

        with override_settings(**{**self.values, "llm_timeout": 0.05, "ollama_url": "http://127.0.0.1:9"}):
            outcome = ping(llm_config(get_settings(), "BTC"))
        self.assertFalse(outcome["ok"])
        self.assertIn("127.0.0.1:9", outcome["detail"])
        self.assertIn("connection", outcome["detail"].lower())

    def test_partial_replies_keep_the_scored_headlines(self):
        reply = json.dumps({"scores": [{"i": 1, "s": 0.7, "t": "adoption"}]})  # second headline missing
        with override_settings(**self.values), \
                mock.patch("analysis.news.fetch_rss", return_value=([item(h) for h in BULLISH], [])), \
                mock.patch("analysis.news.llm._chat", return_value=reply):
            result = analyze_news("BTC", force=True)
        methods = {entry["method"] for entry in result.items}
        self.assertIn("llm", methods)
        self.assertGreater(result.sentiment, 0)

    def test_score_headlines_reports_stats(self):
        from analysis.news.llm import LlmConfig, score_headlines

        reply = "\n".join(f"{index}: -0.5 because risk" for index in (1, 2))
        with self.enterContext(isolated_cache()), mock.patch("analysis.news.llm._chat", return_value=reply):
            scored, stats = score_headlines(["a", "b"], LlmConfig(provider="ollama", model="m", base_url="u"))
        self.assertEqual(len(scored), 2)
        self.assertAlmostEqual(scored[0][0], -0.5, places=3)
        self.assertEqual(stats["requested"], 2)
        self.assertEqual(stats["fallbacks"], 0)
        self.assertEqual(stats["scoring"], "llm")
        self.assertEqual(stats["provider"], "ollama")

    def test_lexicon_fill_ins_is_counted_as_fallbacks(self):
        from analysis.news.llm import LlmConfig, score_headlines

        with self.enterContext(isolated_cache()), \
                mock.patch("analysis.news.llm._chat", return_value=json.dumps({"scores": [{"i": 1, "s": 0.3}]})):
            scored, stats = score_headlines(["bullish headline", "another headline"],
                                           LlmConfig(provider="ollama", model="m", base_url="u"))
        self.assertEqual(stats["fallbacks"], 1)
        self.assertEqual(stats["scoring"], "mixed")
        self.assertEqual(scored[1][2], "lexicon")

    def test_llm_error_type_is_used_for_bad_json(self):
        with mock.patch("analysis.news.llm._chat", return_value=""):
            from analysis.news.llm import LlmConfig, score_headlines

            with self.assertRaises(LlmError):
                score_headlines(["headline"], LlmConfig(provider="ollama", model="m", base_url="u"))


class ParseScoreTests(unittest.TestCase):
    def test_accepts_fenced_json(self):
        text = 'Here you go:\n```json\n{"scores":[{"i":1,"s":0.4,"t":"inflow"}]}\n```'
        self.assertEqual(parse_scores(text, 1)[1][0], 0.4)

    def test_accepts_plain_numbered_lines(self):
        parsed = parse_scores("1: -0.3 regulatory fear\n2: 0.6 adoption", 2)
        self.assertAlmostEqual(parsed[1][0], -0.3)
        self.assertAlmostEqual(parsed[2][0], 0.6)

    def test_scales_a_hundred_point_answer(self):
        parsed = parse_scores(json.dumps([{"i": 1, "s": -60}]), 1)
        self.assertAlmostEqual(parsed[1][0], -0.6)

    def test_clamps_out_of_range_values(self):
        parsed = parse_scores(json.dumps([{"i": 1, "s": 12.0}]), 1)
        self.assertLessEqual(parsed[1][0], 1.0)

    def test_garbage_yields_nothing(self):
        self.assertEqual(parse_scores("", 3), {})
        self.assertEqual(parse_scores("no numbers here", 3), {})


class CacheKeyTests(unittest.TestCase):
    def test_fingerprint_changes_with_everything_that_affects_the_answer(self):
        def fp(**values):
            with override_settings(**values):
                from config.store import get_settings

                return config_fingerprint(get_settings(), "BTC")

        base = fp(news_provider="lexicon", rss_feeds=["a"])
        self.assertNotEqual(base, fp(news_provider="lexicon", rss_feeds=["b"]))
        self.assertNotEqual(base, fp(news_provider="ollama", rss_feeds=["a"], ollama_model="llama3.1"))
        self.assertNotEqual(base, fp(news_provider="lexicon", rss_feeds=["a"], news_extra_keywords={"BTC": ["x"]}))
        # the guard changes the verdict, so it must change the cache key too
        self.assertNotEqual(base, fp(news_provider="lexicon", rss_feeds=["a"], news_veto_mode="block"))
        self.assertNotEqual(base, fp(news_provider="lexicon", rss_feeds=["a"], news_veto_threshold=0.2))

    def test_cached_result_is_reused_until_ttl_or_config_changes(self):
        calls = []

        def fake_fetch(feeds, timeout=8.0, proxy=None):
            calls.append(1)
            return [item(head) for head in BULLISH], []

        values = {"news_enabled": True, "news_provider": "lexicon", "rss_feeds": ["f"],
                  "cryptopanic_enabled": False, "fear_greed_enabled": False,
                  "symbol_relevance_only": False, "news_min_items": 1, "news_cache_ttl": 900}
        with self.enterContext(isolated_cache()), override_settings(**values), \
                mock.patch("analysis.news.fetch_rss", side_effect=fake_fetch):
            first = analyze_news("BTC")
            second = analyze_news("BTC")
            third = analyze_news("SOL")            # other symbol -> its own key
            forced = analyze_news("BTC", force=True)

        self.assertEqual(first.cache_state, "fetched")
        self.assertEqual(second.cache_state, "cache")
        self.assertEqual(len(calls), 3)             # BTC, SOL, then the forced refresh
        self.assertEqual(third.symbol, "SOL")
        self.assertEqual(forced.cache_state, "fetched")


if __name__ == "__main__":
    unittest.main()
