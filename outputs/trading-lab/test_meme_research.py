import io
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch
import meme_research
from meme_research import MemeCoinResearchEngine, MemeResearchConfig, BASE_URL


def good_pair(address="TOKEN1", liquidity=50000, volume=100000, buys=180, sells=80,
              age_minutes=60, change_1h=8):
    now_ms = 1_800_000_000_000
    return {
        "chainId": "solana",
        "dexId": "raydium",
        "url": "https://dexscreener.com/solana/pair1",
        "pairAddress": "PAIR1",
        "baseToken": {"address": address, "name": "Example Meme", "symbol": "MEME"},
        "priceUsd": "0.001",
        "liquidity": {"usd": liquidity},
        "volume": {"h24": volume},
        "txns": {"h24": {"buys": buys, "sells": sells}},
        "priceChange": {"h1": change_1h, "h24": 24},
        "pairCreatedAt": now_ms - age_minutes * 60_000,
    }


class DexScreenerFetchTests(unittest.TestCase):
    def setUp(self):
        with meme_research._RESPONSE_CACHE_LOCK:
            meme_research._RESPONSE_CACHE.clear()

    def test_429_retries_and_honours_retry_after(self):
        headers = Message()
        headers["Retry-After"] = "2"
        rate_limited = urllib.error.HTTPError(
            "https://example.test/data", 429, "Too Many Requests", headers, None
        )

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with patch.object(meme_research.urllib.request, "urlopen",
                          side_effect=[rate_limited, Response(b'{"ok": true}')]) as fetch, \
             patch.object(meme_research.time, "sleep") as sleep:
            result = meme_research._fetch_json("https://example.test/data")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_successful_response_is_cached_briefly(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with patch.object(meme_research.urllib.request, "urlopen",
                          return_value=Response(b'{"price": 1}')) as fetch:
            first = meme_research._fetch_json("https://example.test/price")
            second = meme_research._fetch_json("https://example.test/price")
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)


class MemeResearchTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.profile_url = BASE_URL + "/token-profiles/latest/v1"
        self.boost_url = BASE_URL + "/token-boosts/latest/v1"
        self.pair_prefix = BASE_URL + "/token-pairs/v1/solana/"

    def engine(self, data, config=None):
        def fake_fetch(url):
            if url == self.profile_url:
                return data.get("profiles", [])
            if url == self.boost_url:
                return data.get("boosts", [])
            address = url.removeprefix(self.pair_prefix)
            return data.get("pairs", {}).get(address, [])
        return MemeCoinResearchEngine(fetch_json=fake_fetch, config=config, clock=lambda: self.now)

    def test_only_discovers_solana_and_deduplicates_sources(self):
        engine = self.engine({
            "profiles": [
                {"chainId": "solana", "tokenAddress": "TOKEN1"},
                {"chainId": "ethereum", "tokenAddress": "ETH1"},
            ],
            "boosts": [{"chainId": "solana", "tokenAddress": "TOKEN1"}],
            "pairs": {"TOKEN1": [good_pair("TOKEN1")]},
        })
        result = engine.run()
        self.assertEqual(result["discovered_tokens"], 1)
        self.assertEqual(result["candidates"][0]["discovery_sources"], ["profile", "boost"])
        self.assertFalse(result["execution_enabled"])

    def test_market_candidate_is_watchlisted_but_never_trade_enabled(self):
        engine = self.engine({
            "profiles": [{"chainId": "solana", "tokenAddress": "TOKEN1"}],
            "pairs": {"TOKEN1": [good_pair("TOKEN1")]},
        })
        result = engine.run()
        candidate = result["candidates"][0]
        self.assertEqual(candidate["decision"], "WATCH")
        self.assertEqual(candidate["security_checks"], "not_checked")
        self.assertFalse(candidate["execution_enabled"])
        components = candidate["score_components"]
        self.assertEqual(set(components), {"liquidity", "turnover", "activity", "buy_balance", "momentum"})
        self.assertEqual(candidate["score"], round(sum(components.values()), 2))
        self.assertAlmostEqual(components["turnover"], 20.0)
        self.assertAlmostEqual(components["activity"], 10.4)
        self.assertAlmostEqual(components["momentum"], 2.4)

    def test_low_liquidity_and_extreme_pump_are_rejected(self):
        config = MemeResearchConfig(min_liquidity_usd=10000, max_1h_pump_pct=80)
        engine = self.engine({
            "profiles": [
                {"chainId": "solana", "tokenAddress": "LOW"},
                {"chainId": "solana", "tokenAddress": "PUMP"},
            ],
            "pairs": {
                "LOW": [good_pair("LOW", liquidity=1000)],
                "PUMP": [good_pair("PUMP", change_1h=120)],
            },
        }, config=config)
        result = engine.run()
        by_address = {c["token_address"]: c for c in result["candidates"]}
        self.assertIn("liquidity_below_minimum", by_address["LOW"]["rejection_reasons"])
        self.assertIn("one_hour_pump_chase_filter", by_address["PUMP"]["rejection_reasons"])
        self.assertTrue(all(c["decision"] == "REJECT" for c in result["candidates"]))

    def test_missing_pair_data_fails_closed(self):
        engine = self.engine({
            "profiles": [{"chainId": "solana", "tokenAddress": "TOKEN1"}],
            "pairs": {"TOKEN1": []},
        })
        result = engine.run()
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["errors"][0]["error"], "no_matching_solana_pairs")

    def test_limit_is_bounded(self):
        engine = self.engine({})
        with self.assertRaises(ValueError):
            engine.run(limit=31)

    def test_invalid_provider_response_is_recorded_without_crash(self):
        def fetch(url):
            if url.endswith("latest/v1"):
                return []
            return {"unexpected": "shape"}
        engine = MemeCoinResearchEngine(fetch_json=fetch, clock=lambda: self.now)
        result = engine.run()
        self.assertEqual(result["scored_candidates"], 0)
        self.assertEqual(result["errors"], [])

if __name__ == "__main__":
    unittest.main()
