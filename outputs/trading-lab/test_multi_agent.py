"""Tests for the six-agent deliberation engine (no live model calls)."""
import unittest
from multi_agent import (
    AGENT_SPECS,
    build_market_context,
    _validate_agent_output,
    _parse_json_loose,
    apply_decision_to_paper,
)


class MultiAgentUnitTests(unittest.TestCase):
    def test_six_agents_defined(self):
        self.assertEqual(len(AGENT_SPECS), 6)
        keys = [a["key"] for a in AGENT_SPECS]
        self.assertEqual(
            keys,
            ["market", "technical", "macro", "strategy", "risk", "coordinator"],
        )

    def test_build_context_filters_invalid_prices(self):
        market = {
            "pairs": {
                "EUR/USD": {"price": 1.08, "observed": 1e9, "source": "test"},
                "BAD": {"price": 0, "observed": 1e9},
                "NONE": {"price": "nan", "observed": 1e9},
            }
        }
        ctx = build_market_context(market, {}, {}, {}, [])
        self.assertIn("EUR/USD", ctx["observed_instruments"])
        self.assertNotIn("BAD", ctx["observed_instruments"])
        self.assertNotIn("NONE", ctx["observed_instruments"])
        self.assertEqual(ctx["mode"], "paper_only")

    def test_validate_agent_output_coerces(self):
        raw = {
            "decision": "BUY",
            "side": "long",
            "pair_or_token": "EUR/USD",
            "rationale": "momentum",
            "size_hint": "100",
            "concerns": ["thin data", 123, None],
        }
        out = _validate_agent_output(
            raw,
            ["decision", "side", "pair_or_token", "rationale", "size_hint", "concerns"],
        )
        self.assertEqual(out["decision"], "buy")
        self.assertEqual(out["side"], "long")
        self.assertEqual(out["size_hint"], 100.0)
        self.assertEqual(out["concerns"], ["thin data", "123"])

    def test_parse_json_loose_recovers_fenced(self):
        text = '```json\n{"decision": "hold", "concerns": []}\n```'
        obj = _parse_json_loose(text)
        self.assertEqual(obj["decision"], "hold")

    def test_parse_json_loose_recovers_prose(self):
        text = 'Here is my view:\n{"decision": "sell", "side": "sell", "concerns": ["risk"]}\nThanks.'
        obj = _parse_json_loose(text)
        self.assertEqual(obj["decision"], "sell")

    def test_apply_decision_hold(self):
        result = apply_decision_to_paper(
            {"side": "hold"}, lambda *a: None, lambda *a: None, {"positions": []}
        )
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["executed"], [])

    def test_apply_decision_already_held(self):
        def open_fn(pair, side, notional):
            raise AssertionError("should not open")

        result = apply_decision_to_paper(
            {"side": "buy", "pair_or_token": "EUR/USD", "size_hint": 100},
            open_fn,
            lambda *a: None,
            {"positions": [{"pair": "EUR/USD"}]},
        )
        self.assertEqual(result["action"], "abstain")


if __name__ == "__main__":
    unittest.main()
