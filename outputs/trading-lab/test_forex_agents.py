import os
import tempfile
import time
import unittest
from datetime import datetime, timezone

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

    def open(self, pair, side, notional):
        self.orders.append((pair, side, notional))
        position = {"id": "paper-1", "pair": pair, "side": side, "notional": notional}
        self.positions.append(position)
        return {"position": position}

    def status(self):
        return {"account": {"positions": list(self.positions), "equity": 10000.0}}


class ForexAgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "agents.sqlite")
        self.lab = FakeLab()
        self.runtime = ForexAgentRuntime(self.path, self.lab)

    def tearDown(self):
        # forex_agents opens sqlite connections via `with` blocks, which
        # commit but never close; on Windows the lingering lock breaks
        # TemporaryDirectory cleanup, so collect first and retry briefly.
        import gc
        gc.collect()
        for _ in range(50):
            try:
                self.tmp.cleanup()
                return
            except PermissionError:
                time.sleep(0.02)
                gc.collect()
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


if __name__ == "__main__":
    unittest.main()
