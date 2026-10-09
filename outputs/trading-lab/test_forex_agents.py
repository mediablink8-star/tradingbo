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
        self.assertTrue(all(e["kind"] == "live_agent_report" for e in result["events"]))

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


if __name__ == "__main__":
    unittest.main()
