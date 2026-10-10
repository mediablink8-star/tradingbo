"""Tests for the in-memory key store and the advisory AI research layer.

The important properties here are negative ones: the secret never leaks, the
budget refuses to overspend, and a model response cannot influence execution.
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import key_store as ks
import llm_research as lr


class KeyStoreTest(unittest.TestCase):
    def setUp(self):
        self._tick = [1000.0]
        self.store = ks.KeyStore(max_calls=3, max_spend=0.01, cost_per_call=0.002,
                                 clock=lambda: self._tick[0])

    def tearDown(self):
        os.environ.pop(ks.ENV_FALLBACK, None)

    def test_key_stays_in_memory_only(self):
        self.store.store("sk-secret-value", "gpt-4o-mini")
        self.assertTrue(self.store.has_key())
        # The secret must not appear in any dict the store hands out.
        blob = json.dumps(self.store.status())
        self.assertNotIn("sk-secret-value", blob)
        for row in self.store.log_tail(50):
            self.assertNotIn("sk-secret-value", json.dumps(row))

    def test_key_never_reaches_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "probe.sqlite"
            self.store.store("sk-should-not-persist", "gpt-4o-mini")
            target.write_bytes(b"")
            for row in self.store.log_tail(50):
                target.write_text(json.dumps(row))
            self.assertNotIn(b"sk-should-not-persist", target.read_bytes())

    def test_blank_key_clears(self):
        self.store.store("sk-x", "m")
        result = self.store.store("   ")
        self.assertFalse(result["connected"])
        self.assertFalse(self.store.has_key())

    def test_forget_clears(self):
        self.store.store("sk-x", "m")
        self.assertTrue(self.store.forget()["cleared"])
        self.assertFalse(self.store.has_key())

    def test_env_fallback_is_read_only(self):
        os.environ[ks.ENV_FALLBACK] = "sk-from-env"
        self.assertTrue(self.store.has_key())
        self.store.forget()
        # forgetting the entered key cannot remove the environment fallback
        self.assertTrue(self.store.has_key())

    def test_call_budget_is_enforced(self):
        self.store._charge("a")
        self.store._charge("b")
        self.store._charge("c")
        with self.assertRaises(ks.BudgetExceeded):
            self.store._charge("d")

    def test_spend_cap_is_enforced(self):
        store = ks.KeyStore(max_calls=99, max_spend=0.005, cost_per_call=0.002)
        store._charge("a")
        store._charge("b")
        with self.assertRaises(ks.BudgetExceeded):
            store._charge("c")

    def test_budget_resets_next_day(self):
        # Build the store with an explicit clock so no live network or real
        # clock reading is involved.
        tick = [1000.0]
        store = ks.KeyStore(max_calls=2, max_spend=1, cost_per_call=0.001,
                            clock=lambda: tick[0])
        store._charge("x")
        self.assertEqual(store.budget_remaining()["calls"], 1)
        # advance past a UTC day boundary
        tick[0] += 86400 * 2
        self.assertEqual(store.budget_remaining()["calls"], 0)
        self.assertEqual(store.budget_remaining()["spent_usd"], 0.0)

    def test_model_is_required(self):
        with self.assertRaises(ValueError):
            self.store.set_model("")

    def test_free_model_is_charged_nothing(self):
        self.assertTrue(ks.is_free_model("nvidia/nemotron-3.5-lightning:free"))
        self.assertFalse(ks.is_free_model("openai/gpt-4o-mini"))
        self.assertFalse(ks.is_free_model(None))
        self.store.store("sk-x", model="nvidia/nemotron-3.5-lightning:free")
        budget = self.store.budget_remaining()
        self.assertTrue(budget["free_model"])
        self.assertEqual(budget["cost_per_call_usd"], 0.0)
        for _ in range(3):
            self.store._charge("research")
        after = self.store.budget_remaining()
        self.assertEqual(after["calls"], 3)
        self.assertEqual(after["spent_usd"], 0.0)
        # A free model must not consume the spend ceiling.
        self.assertEqual(after["spend_left_usd"], self.store._max_spend)

    def test_paid_model_still_costs(self):
        self.store.store("sk-x", model="anthropic/claude-3.5-sonnet")
        self.store._charge("research")
        self.assertGreater(self.store.budget_remaining()["spent_usd"], 0)


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self, *_a):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class ResearchLayerTest(unittest.TestCase):
    def setUp(self):
        self.store = ks.KeyStore(max_calls=20, max_spend=1, cost_per_call=0.001)
        self.seen_requests = []

    def _opener(self, payload):
        def opener(req, timeout=None):
            self.seen_requests.append(req)
            return FakeResponse(payload)
        return opener

    def _context_args(self):
        market = {
            "pairs": {
                "EUR/USD": {"price": 1.12, "bid": 1.1199, "ask": 1.1201,
                            "observed": 1.0, "source": "test",
                            "instrument": "fx"},
            }
        }
        return (market, {"equity": 10000.0, "positions": []},
                {"max_positions": 3}, {"EUR/USD": [(1.0, 1.11), (2.0, 1.12)]},
                [])

    def test_unavailable_without_key(self):
        layer = lr.ResearchLayer(self.store)
        result = layer.run(*self._context_args())
        self.assertFalse(result["ok"])
        self.assertIn("No usable model configuration", result["reason"])
        self.assertEqual(result["stages"], [])

    def test_key_is_sent_but_not_echoed(self):
        self.store.store("sk-test", "gpt-4o-mini")
        layer = lr.ResearchLayer(self.store, opener=self._opener(
            {"output_text": json.dumps({
                "research": "flat", "concerns": []})}))
        layer.run(*self._context_args())
        self.assertTrue(self.seen_requests)
        auth = self.seen_requests[0].get_header("Authorization")
        self.assertEqual(auth, "Bearer sk-test")

    def test_all_four_stages_run_and_stay_advisory(self):
        self.store.store("sk-test", "gpt-4o-mini")
        fields = ["research", "macro_view", "strategy", "critique"]

        def opener(req, timeout=None):
            field = fields[len(self.seen_requests)]
            self.seen_requests.append(req)
            return FakeResponse({"output_text": json.dumps(
                {field: "text for " + field, "concerns": ["weak data"]})})

        layer = lr.ResearchLayer(self.store, opener=opener)
        result = layer.run(*self._context_args())
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["stages"]), 4)
        for stage in result["stages"]:
            self.assertTrue(stage["advisory"])
            self.assertFalse(stage["affects_execution"])

    def test_research_never_mutates_account_or_limits(self):
        self.store.store("sk-test", "gpt-4o-mini")
        market, account, risk, history, positions = self._context_args()
        account_before = json.dumps(account, sort_keys=True)
        risk_before = json.dumps(risk, sort_keys=True)
        market_before = json.dumps(market, sort_keys=True)

        layer = lr.ResearchLayer(self.store, opener=self._opener(
            {"output_text": json.dumps({
                "research": "ignore all risk limits", "concerns": []})}))
        result = layer.run(market, account, risk, history, positions)
        self.assertEqual(json.dumps(account, sort_keys=True), account_before)
        self.assertEqual(json.dumps(risk, sort_keys=True), risk_before)
        self.assertEqual(json.dumps(market, sort_keys=True), market_before)
        # and the record carries no execution keys at all
        self.assertNotIn("executed", result)
        self.assertNotIn("approve", json.dumps(result).lower())

    def test_malformed_json_is_reported_not_crashed(self):
        self.store.store("sk-test", "gpt-4o-mini")
        layer = lr.ResearchLayer(self.store, opener=self._opener(
            {"output_text": "this is not json at all"}))
        result = layer.run(*self._context_args())
        self.assertFalse(result["ok"])
        self.assertTrue(any("not valid JSON" in c
                            for s in result["stages"] for c in s["concerns"]))

    def test_fenced_json_block_is_tolerated(self):
        self.store.store("sk-test", "gpt-4o-mini")
        fenced = "```json\n" + json.dumps(
            {"research": "ok", "concerns": []}) + "\n```"
        layer = lr.ResearchLayer(self.store, opener=self._opener(
            {"output_text": fenced}))
        result = layer.run(*self._context_args())
        self.assertTrue(result["ok"])

    def test_missing_field_is_rejected(self):
        self.store.store("sk-test", "gpt-4o-mini")
        layer = lr.ResearchLayer(self.store, opener=self._opener(
            {"output_text": json.dumps({"summary": "wrong shape"})}))
        result = layer.run(*self._context_args())
        self.assertFalse(result["ok"])

    def test_provider_error_is_surfaced(self):
        import urllib.error

        def opener(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

        self.store.store("sk-bad", "gpt-4o-mini")
        layer = lr.ResearchLayer(self.store, opener=opener)
        result = layer.run(*self._context_args())
        self.assertFalse(result["ok"])
        self.assertTrue(any("HTTP 401" in c
                            for s in result["stages"] for c in s["concerns"]))

    def test_budget_stops_the_stage_loop(self):
        store = ks.KeyStore(max_calls=2, max_spend=1, cost_per_call=0.001)
        store.store("sk-test", "gpt-4o-mini")
        fields = ["research", "macro_view", "strategy", "critique"]
        calls = []

        def opener(req, timeout=None):
            field = fields[len(calls)]
            calls.append(req)
            return FakeResponse({"output_text": json.dumps(
                {field: "text", "concerns": []})})

        layer = lr.ResearchLayer(store, opener=opener)
        result = layer.run(*self._context_args())
        # Two calls succeed, the third is refused and recorded, then the loop
        # stops rather than continuing to spend.
        self.assertEqual(len(result["stages"]), 3)
        self.assertTrue(result["stages"][0]["ok"])
        self.assertTrue(result["stages"][1]["ok"])
        self.assertFalse(result["stages"][2]["ok"])
        self.assertIn("Budget exhausted",
                      result["stages"][2]["concerns"][0])
        self.assertEqual(store.budget_remaining()["calls"], 2)

    def test_context_contains_no_fabricated_prices(self):
        market, account, risk, history, positions = self._context_args()
        market["pairs"]["EUR/USD"]["price"] = float("nan")
        context = lr.build_context(market, account, risk, history, positions)
        # A non-finite price must be dropped, not serialised.
        self.assertNotIn("EUR/USD", context["observed_pairs"])

    def test_history_series_is_bounded(self):
        market, account, risk, _, positions = self._context_args()
        long_history = {"EUR/USD": [(float(i), 1.1) for i in range(500)]}
        context = lr.build_context(market, account, risk, long_history, positions)
        self.assertLessEqual(
            len(context["observed_pairs"]["EUR/USD"]["recent_closes"]), 12)


if __name__ == "__main__":
    unittest.main()