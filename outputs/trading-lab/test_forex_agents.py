import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from forex_agents import ForexAgentRuntime
from forex_risk import FXRisk, RiskConfig


class FakeLab:
    def __init__(self):
        self.broker = type("Broker", (), {"risk": FXRisk(RiskConfig())})()
        self.price = 1.1000
        self.observed = time.time()
        self.positions = []
        self.daily_halted = False
        self.daily_pnl = 0.0
        self.orders = []

    def tick(self):
        self.observed = time.time()
        row = {
            "pair": "EUR/USD", "price": self.price, "bid": self.price - 0.00005,
            "ask": self.price + 0.00005, "observed": self.observed,
            "provider_date": datetime.now(timezone.utc).date().isoformat(),
        }
        return {"market": {"pairs": {"EUR/USD": row}},
                "account": {"positions": list(self.positions),
                            "daily_halted": self.daily_halted,
                            "daily_pnl": self.daily_pnl}}

    @staticmethod
    def _provider_date_is_today(value):
        return value == datetime.now(timezone.utc).date().isoformat()

    def open(self, pair, side, notional):
        self.orders.append((pair, side, notional))
        position = {"id": "paper-1", "pair": pair, "side": side, "notional": notional}
        self.positions.append(position)
        return {"position": position}

    def close(self, position_id):
        self.positions = [p for p in self.positions if p["id"] != position_id]
        return {"closed": position_id}

    def status(self):
        return {"account": {"positions": list(self.positions), "equity": 10000.0}}


class ForexAgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "agents.sqlite")
        self.lab = FakeLab()
        self.runtime = ForexAgentRuntime(self.path, self.lab)

    class FakeResearch:
        def __init__(self, calls_left=40, spend_left=5.0, cost_per_call=0.002):
            self.store = type("Store", (), {
                "budget_remaining": lambda _self: {
                    "calls_left": calls_left,
                    "spend_left_usd": spend_left,
                    "cost_per_call_usd": cost_per_call,
                }
            })()

        def available(self):
            return True

    @staticmethod
    def committee_result(*, side="buy", pair="EUR/USD", failed=None, vetoes=None):
        agents = [
            {"key": key, "agent": key.title(), "ok": key != failed,
             "report": ({"veto_reasons": list(vetoes or [])} if key == "risk" else {})}
            for key in ("market", "technical", "macro", "strategy", "risk", "coordinator")
        ]
        return {
            "ok": any(a["ok"] for a in agents), "cycle_id": "ai-cycle-1",
            "agents": agents,
            "final_decision": {"side": side, "decision": side, "pair_or_token": pair,
                               "rationale": "test recommendation", "size_hint": 250.0,
                               "concerns": []},
            "advisory_only": True, "execution_enabled": False,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_insufficient_distinct_observations_abstains(self):
        result = self.runtime.run_cycle()
        self.assertEqual(result["executed"], [])
        self.assertEqual(self.lab.orders, [])
        self.assertEqual(len(result["events"]), 5)

    def test_three_distinct_rising_observations_can_only_create_paper_order(self):
        results = []
        for price in (1.1000, 1.1003, 1.1008):
            self.lab.price = price
            results.append(self.runtime.run_cycle())
            time.sleep(0.002)
        self.assertTrue(any(result["executed"] for result in results))
        self.assertEqual(len(self.lab.orders), 1)
        self.assertEqual(self.lab.orders[0][0:2], ("EUR/USD", "buy"))
        self.assertEqual(self.lab.orders[0][2], 250.0)
        self.assertTrue(all(e["kind"] == "live_agent_report" for cycle in results for e in cycle["events"]))

    def test_daily_halt_prevents_paper_order(self):
        for price in (1.1000, 1.1000, 1.1000):
            self.lab.price = price
            self.runtime.run_cycle()
            time.sleep(0.002)
        self.lab.daily_halted = True
        self.lab.price = 1.1015
        result = self.runtime.run_cycle()
        self.assertEqual(result["executed"], [])
        self.assertEqual(self.lab.orders, [])

    def test_overlapping_cycle_abstains_without_duplicate_order(self):
        # Simulate a scheduler cycle already in progress when the dashboard
        # button is pressed. The concurrent request must not submit an order.
        self.runtime._cycle_lock.acquire()
        try:
            result = self.runtime.run_cycle()
        finally:
            self.runtime._cycle_lock.release()
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "cycle_in_progress")
        self.assertEqual(result["executed"], [])
        self.assertEqual(self.lab.orders, [])

    def test_stale_quote_fails_closed(self):
        original = self.lab.tick
        def stale_tick():
            result = original()
            result["market"]["pairs"]["EUR/USD"]["observed"] = time.time() - 900
            return result
        self.lab.tick = stale_tick
        result = self.runtime.run_cycle()
        self.assertEqual(result["executed"], [])
        self.assertEqual(result["events"][0]["status"], "Blocked")

    def test_fresh_quote_age_boundary(self):
        now = time.time()
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        base = {"price": 1.1, "provider_date": today}
        self.assertTrue(self.runtime._fresh({**base, "observed": now - 299}, now))
        self.assertFalse(self.runtime._fresh({**base, "observed": now - 301}, now))

    def test_events_and_samples_persist(self):
        self.runtime.run_cycle()
        second = ForexAgentRuntime(self.path, self.lab)
        state = second.status()
        self.assertEqual(len(state["events"]), 5)
        self.assertEqual(state["samples"][0]["observations"], 1)
        self.assertEqual(state["policy"]["mode"], "paper_only")

    def test_agent_config_defaults_all_enabled(self):
        config = self.runtime.get_config()
        self.assertEqual(
            config,
            {"market": True, "macro": True, "strategy": True,
             "risk": True, "portfolio": True})

    def test_agent_config_roundtrip_persists(self):
        self.runtime.set_config("strategy", False)
        second = ForexAgentRuntime(self.path, self.lab)
        self.assertFalse(second.get_config()["strategy"])
        self.assertTrue(second.get_config()["market"])
        self.assertIn("agent_config", second.status())
        self.assertFalse(second.status()["agent_config"]["strategy"])

    def test_agent_config_rejects_unknown_agent(self):
        with self.assertRaises(ValueError):
            self.runtime.set_config("janitor", True)

    def test_agent_config_risk_is_locked_on(self):
        with self.assertRaises(ValueError):
            self.runtime.set_config("risk", False)
        self.assertTrue(self.runtime.get_config()["risk"])

    def test_agent_config_macro_has_no_execution_path(self):
        with self.assertRaises(ValueError):
            self.runtime.set_config("macro", False)

    def _rising_cycle(self, runtime=None):
        runtime = runtime or self.runtime
        results = []
        for price in (1.1000, 1.1003, 1.1008):
            self.lab.price = price
            results.append(runtime.run_cycle())
            time.sleep(0.002)
        return results

    def test_disabled_strategy_blocks_proposals_but_keeps_event_count(self):
        self.runtime.set_config("strategy", False)
        results = self._rising_cycle()
        self.assertEqual(self.lab.orders, [])
        self.assertTrue(all(r["executed"] == [] for r in results))
        last = results[-1]
        self.assertEqual(len(last["events"]), 5)
        strategy = next(
            e for e in last["events"] if e["agent"] == "Strategy analyst")
        self.assertEqual(strategy["status"], "Skipped (disabled by operator)")
        self.assertEqual(strategy["approve"], [])

    def test_disabled_portfolio_holds_approved_entries(self):
        self.runtime.set_config("portfolio", False)
        results = self._rising_cycle()
        self.assertEqual(self.lab.orders, [])
        self.assertTrue(all(r["executed"] == [] for r in results))
        last = results[-1]
        coord = next(
            e for e in last["events"] if e["agent"] == "Portfolio coordinator")
        self.assertEqual(coord["status"], "Skipped (disabled by operator)")
        self.assertTrue(any(
            "disabled by operator" in c
            for e in last["events"] for c in e["concerns"]))

    def test_disabled_research_stops_sampling_and_trading(self):
        self.runtime.set_config("market", False)
        results = self._rising_cycle()
        self.assertEqual(self.lab.orders, [])
        self.assertTrue(all(r["executed"] == [] for r in results))
        research = next(
            e for e in results[-1]["events"] if e["agent"] == "Market researcher")
        self.assertEqual(research["status"], "Skipped (disabled by operator)")

    def test_reenabling_restores_trading(self):
        self.runtime.set_config("strategy", False)
        self._rising_cycle()
        self.assertEqual(self.lab.orders, [])
        self.runtime.set_config("strategy", True)
        results = self._rising_cycle()
        self.assertTrue(any(r["executed"] for r in results))
        self.assertEqual(len(self.lab.orders), 1)

    def _run_fake_ai_cycle(self, result):
        self.runtime.attach_research(self.FakeResearch())
        with patch("multi_agent.MultiAgentEngine.deliberate", return_value=result):
            return self.runtime.run_ai_cycle()

    def test_ai_paper_cycle_requires_all_six_agents_and_no_risk_veto(self):
        result = self._run_fake_ai_cycle(self.committee_result(vetoes=["spread risk"]))
        self.assertEqual(self.lab.orders, [])
        self.assertFalse(result["ai_gate"]["entry_allowed"])
        self.assertTrue(any("Risk critic veto" in x for x in result["ai_gate"]["blockers"]))

    def test_ai_paper_cycle_abstains_when_any_agent_fails(self):
        result = self._run_fake_ai_cycle(self.committee_result(failed="risk"))
        self.assertEqual(self.lab.orders, [])
        self.assertFalse(result["ai_gate"]["entry_allowed"])

    def test_ai_proposal_never_submits_until_operator_approval(self):
        result = self._run_fake_ai_cycle(self.committee_result())
        self.assertEqual(self.lab.orders, [])
        self.assertTrue(result["proposal"]["eligible"])
        approved = self.runtime.approve_paper_cycle(result["cycle_id"])
        self.assertEqual(self.lab.orders, [("EUR/USD", "buy", 250.0)])
        self.assertTrue(approved["ok"])
        self.assertFalse(result["execution_enabled"])

    def test_direct_apply_request_is_blocked(self):
        self.runtime.attach_research(self.FakeResearch())
        with patch("multi_agent.MultiAgentEngine.deliberate") as deliberate:
            result = self.runtime.run_deliberation(apply_paper=True)
        deliberate.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(self.lab.orders, [])

    def test_approval_rejects_quote_drift_and_consumes_plan(self):
        result = self._run_fake_ai_cycle(self.committee_result())
        self.lab.price = 1.102
        rejected = self.runtime.approve_paper_cycle(result["cycle_id"])
        self.assertFalse(rejected["ok"])
        self.assertIn("10 bps", rejected["reason"])
        self.assertEqual(self.lab.orders, [])
        second = self.runtime.approve_paper_cycle(result["cycle_id"])
        self.assertFalse(second["ok"])

    def test_approval_is_idempotent(self):
        result = self._run_fake_ai_cycle(self.committee_result())
        first = self.runtime.approve_paper_cycle(result["cycle_id"])
        second = self.runtime.approve_paper_cycle(result["cycle_id"])
        self.assertTrue(first["ok"])
        self.assertTrue(second["already_approved"])
        self.assertEqual(len(self.lab.orders), 1)

    def test_ai_paper_cycle_rejects_unknown_instrument(self):
        result = self._run_fake_ai_cycle(self.committee_result(pair="BTC/USD"))
        self.assertEqual(self.lab.orders, [])
        self.assertFalse(result["ai_gate"]["entry_allowed"])
        self.assertTrue(any("unsupported instrument" in x for x in result["ai_gate"]["blockers"]))

    def test_ai_proposal_reserves_six_call_budget_before_any_model_work(self):
        self.runtime.attach_research(self.FakeResearch(calls_left=5))
        with patch("multi_agent.MultiAgentEngine.deliberate") as deliberate:
            result = self.runtime.run_ai_cycle()
        deliberate.assert_not_called()
        self.assertEqual(self.lab.orders, [])
        self.assertIn("Six model calls are required", result["reason"])


if __name__ == "__main__":
    unittest.main()
