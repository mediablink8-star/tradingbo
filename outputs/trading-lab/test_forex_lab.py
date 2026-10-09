"""Regression tests for quote validation and automatic paper risk exits."""
import datetime
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from forex_lab import ForexLab


class ForexLabTests(unittest.TestCase):
    def _market(self, price, provider_date=None, observed=None):
        observed = time.time() if observed is None else observed
        provider_date = provider_date or datetime.datetime.now(
            datetime.timezone.utc
        ).date().isoformat()
        row = {
            "pair": "EUR/USD",
            "price": price,
            "bid": price - 0.00005,
            "ask": price + 0.00005,
            "observed": observed,
            "fetched_at": time.time(),
            "provider_date": provider_date,
            "source": "test current quote",
        }
        return {
            "pairs": {"EUR/USD": row},
            "source": "test current quote",
            "provider_date": provider_date,
            "market_open": True,
        }

    def test_market_module_imports_and_current_quote_opens_paper_trade(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = ForexLab(os.path.join(folder, "test.sqlite"))
            with patch("forex_lab.snapshot", return_value=self._market(1.10)):
                result = lab.open("EUR/USD", "buy", 500)
            self.assertTrue(result["ok"])
            self.assertEqual(result["position"]["pair"], "EUR/USD")

    def test_stale_daily_reference_rate_rejects_new_order(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = ForexLab(os.path.join(folder, "test.sqlite"))
            yesterday = (
                datetime.datetime.now(datetime.timezone.utc).date()
                - datetime.timedelta(days=1)
            ).isoformat()
            with patch(
                "forex_lab.snapshot",
                return_value=self._market(1.10, provider_date=yesterday),
            ):
                with self.assertRaisesRegex(ValueError, "stale or not dated today"):
                    lab.open("EUR/USD", "buy", 500)

    def test_current_quote_triggers_automatic_stop_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = ForexLab(os.path.join(folder, "test.sqlite"))
            opened = lab.broker.open("EUR/USD", 1.10, 500, "buy")
            with patch("forex_lab.snapshot", return_value=self._market(1.08)):
                result = lab.tick()
            self.assertEqual(len(result["exit_events"]), 1)
            self.assertEqual(
                result["exit_events"][0]["position_id"], opened["id"]
            )
            self.assertEqual(result["account"]["positions"], [])

    def test_stale_quote_does_not_fabricate_risk_exit_fill(self):
        with tempfile.TemporaryDirectory() as folder:
            lab = ForexLab(os.path.join(folder, "test.sqlite"))
            opened = lab.broker.open("EUR/USD", 1.10, 500, "buy")
            yesterday = (
                datetime.datetime.now(datetime.timezone.utc).date()
                - datetime.timedelta(days=1)
            ).isoformat()
            with patch(
                "forex_lab.snapshot",
                return_value=self._market(1.08, provider_date=yesterday),
            ):
                result = lab.tick()
            self.assertEqual(result["exit_events"], [])
            self.assertEqual(
                [p["id"] for p in result["account"]["positions"]],
                [opened["id"]],
            )


if __name__ == "__main__":
    unittest.main()
