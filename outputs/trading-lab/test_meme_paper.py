import os
import tempfile
import unittest

from meme_paper import MemePaperTracker, HORIZONS_SECONDS
from meme_research import BASE_URL


def pair(address, price):
    return [{
        "chainId": "solana",
        "baseToken": {"address": address, "symbol": "MEME"},
        "priceUsd": str(price),
        "liquidity": {"usd": 50000},
    }]


class MemePaperTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [1_800_000_000.0]
        self.prices = {"TOKEN1": 0.001}
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            address = url.removeprefix(BASE_URL + "/token-pairs/v1/solana/")
            return pair(address, self.prices[address]) if address in self.prices else []

        self.tracker = MemePaperTracker(
            os.path.join(self.temp.name, "paper.sqlite"),
            fetch_json=fetch,
            clock=lambda: self.now[0],
            slippage_bps=50,
            fee_bps=30,
        )

    def tearDown(self):
        # MemePaperTracker holds sqlite connections via `with` blocks, which
        # commit but never close; on Windows the lingering lock breaks
        # TemporaryDirectory cleanup, so collect first and retry briefly.
        # Same workaround as test_forex_agents.py.
        import gc
        import time
        gc.collect()
        for _ in range(50):
            try:
                self.temp.cleanup()
                return
            except PermissionError:
                time.sleep(0.02)
                gc.collect()
        self.temp.cleanup()

    def test_records_only_watch_candidates_with_valid_price(self):
        result = self.tracker.record_scan([
            {"decision": "WATCH", "token_address": "TOKEN1", "price_usd": 0.001, "score": 80, "symbol": "MEME"},
            {"decision": "REJECT", "token_address": "TOKEN2", "price_usd": 1, "score": 20},
            {"decision": "WATCH", "token_address": "TOKEN3", "price_usd": None, "score": 90},
        ])
        self.assertEqual(result["recorded"], 1)
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(self.tracker.status()["snapshots"], 1)

    def test_horizon_return_is_sampled_and_cost_adjusted(self):
        self.tracker.record_scan([
            {"decision": "WATCH", "token_address": "TOKEN1", "price_usd": 0.001, "score": 80, "symbol": "MEME"},
        ])
        self.now[0] += HORIZONS_SECONDS["5m"]
        self.prices["TOKEN1"] = 0.0011
        result = self.tracker.update_due()
        self.assertEqual(result["outcomes_updated"], 1)
        status = self.tracker.status()
        self.assertEqual(status["horizons"]["5m"]["samples"], 1)
        self.assertAlmostEqual(status["horizons"]["5m"]["average_net_return_pct"], 8.4, places=4)
        self.assertEqual(status["horizons"]["15m"]["samples"], 0)

    def test_missing_price_keeps_outcome_pending(self):
        self.tracker.record_scan([
            {"decision": "WATCH", "token_address": "TOKEN1", "price_usd": 0.001, "score": 80},
        ])
        self.now[0] += HORIZONS_SECONDS["5m"]
        self.prices.clear()
        result = self.tracker.update_due()
        self.assertEqual(result["outcomes_updated"], 0)
        self.assertEqual(self.tracker.status()["pending_horizon_observations"], 5)

    def test_late_samples_are_marked_missed_not_counted_as_returns(self):
        self.tracker.record_scan([
            {"decision": "WATCH", "token_address": "TOKEN1", "price_usd": 0.001, "score": 80},
        ])
        # Twenty minutes is too late for both the 5m and 15m sampling windows.
        self.now[0] += 20 * 60
        self.prices["TOKEN1"] = 0.0011
        result = self.tracker.update_due()
        self.assertEqual(result["outcomes_updated"], 0)
        self.assertEqual(result["missed_sampling_windows"], 2)
        status = self.tracker.status()
        self.assertEqual(status["horizons"]["5m"]["samples"], 0)
        self.assertEqual(status["horizons"]["5m"]["missed_sampling_windows"], 1)
        self.assertEqual(status["horizons"]["15m"]["missed_sampling_windows"], 1)
        self.assertEqual(status["pending_horizon_observations"], 3)

    def test_invalid_cost_assumptions_are_rejected(self):
        with self.assertRaises(ValueError):
            MemePaperTracker(os.path.join(self.temp.name, "bad.sqlite"), slippage_bps=-1)


if __name__ == "__main__":
    unittest.main()
