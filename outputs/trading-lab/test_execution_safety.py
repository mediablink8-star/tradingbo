import os
import tempfile
import unittest

from forex_paper import ForexPaperBroker
from instrument_catalog import (
    INSTRUMENTS,
    SUPPORTED_SYMBOLS,
    get_instrument,
    validate_executable_quote,
)
from local_executor_gate import LocalExecutorGate


class InstrumentCatalogTests(unittest.TestCase):
    def test_catalog_contains_only_supported_product_universe(self):
        self.assertEqual(len(SUPPORTED_SYMBOLS), 12)
        self.assertEqual(get_instrument("eur/usd").asset_class, "fx")
        self.assertEqual(get_instrument("XAU/USD").quantity_unit, "troy_ounces")
        self.assertEqual(get_instrument("AAPL/USD").quantity_unit, "shares")
        self.assertNotIn("XAG/USD", INSTRUMENTS)
        self.assertNotIn("BTC/USD", INSTRUMENTS)

    def test_unknown_instrument_rejected_by_catalog(self):
        with self.assertRaisesRegex(ValueError, "Unsupported instrument"):
            get_instrument("BTC/USD")

    def test_paper_broker_rejects_unknown_symbol(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            broker = ForexPaperBroker(os.path.join(temp_dir, "paper.sqlite3"))
            with self.assertRaisesRegex(ValueError, "Unsupported instrument"):
                broker.open("BTC/USD", 100.0, 100.0, "buy")


class ExecutableQuoteTests(unittest.TestCase):
    def setUp(self):
        self.quote = {
            "symbol": "EUR/USD",
            "source": "ibkr",
            "executable": True,
            "contract_id": 12087792,
            "bid": 1.0849,
            "ask": 1.0851,
            "observed": 1000.0,
        }

    def test_valid_fresh_ibkr_quote_is_normalized(self):
        result = validate_executable_quote("EUR/USD", self.quote, now=1002.0)
        self.assertEqual(result["source"], "ibkr")
        self.assertEqual(result["asset_class"], "fx")
        self.assertEqual(result["age_seconds"], 2.0)

    def test_reference_quote_cannot_be_promoted_to_executable(self):
        quote = dict(self.quote, source="Yahoo Finance chart endpoint (unofficial)")
        with self.assertRaisesRegex(ValueError, "directly from IBKR"):
            validate_executable_quote("EUR/USD", quote, now=1001.0)

    def test_quote_requires_broker_contract_identity(self):
        quote = dict(self.quote, contract_id=None)
        with self.assertRaisesRegex(ValueError, "contract identity"):
            validate_executable_quote("EUR/USD", quote, now=1001.0)

    def test_quote_rejects_wrong_symbol_crossed_market_and_staleness(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_executable_quote("GBP/USD", self.quote, now=1001.0)
        with self.assertRaisesRegex(ValueError, "Crossed"):
            validate_executable_quote(
                "EUR/USD", dict(self.quote, bid=1.09, ask=1.08), now=1001.0
            )
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_executable_quote("EUR/USD", self.quote, now=1006.0)


class LocalExecutorGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = LocalExecutorGate(heartbeat_ttl=10, max_arm_seconds=60)

    def test_starts_disarmed_and_cannot_arm_without_heartbeat(self):
        self.assertFalse(self.gate.permits_new_entry(now=1000.0))
        with self.assertRaisesRegex(RuntimeError, "fresh broker heartbeat"):
            self.gate.arm(30, now=1000.0)

    def test_fresh_heartbeat_and_operator_arm_allow_valid_quote(self):
        self.gate.heartbeat(connected=True, now=1000.0)
        self.gate.arm(30, now=1001.0)
        accepted = self.gate.validate_entry_quote(
            "EUR/USD",
            {
                "symbol": "EUR/USD",
                "source": "ibkr",
                "executable": True,
                "contract_id": 12087792,
                "bid": 1.0849,
                "ask": 1.0851,
                "observed": 1001.0,
            },
            now=1002.0,
        )
        self.assertEqual(accepted["source"], "ibkr")
        self.assertTrue(self.gate.permits_new_entry(now=1002.0))

    def test_lease_expiry_disconnection_and_disarm_block_entries(self):
        self.gate.heartbeat(connected=True, now=1000.0)
        self.gate.arm(5, now=1000.0)
        self.assertFalse(self.gate.permits_new_entry(now=1005.0))
        self.gate.heartbeat(connected=True, now=1010.0)
        self.gate.arm(5, now=1010.0)
        self.gate.heartbeat(connected=False, now=1011.0)
        self.assertFalse(self.gate.permits_new_entry(now=1011.0))
        self.gate.heartbeat(connected=True, now=1012.0)
        with self.assertRaisesRegex(RuntimeError, "disarmed"):
            self.gate.validate_entry_quote("EUR/USD", {}, now=1012.0)

    def test_heartbeat_expiry_blocks_even_with_unexpired_arm(self):
        self.gate.heartbeat(connected=True, now=1000.0)
        self.gate.arm(60, now=1000.0)
        self.assertFalse(self.gate.permits_new_entry(now=1011.0))

    def test_arm_lease_is_bounded(self):
        self.gate.heartbeat(connected=True, now=1000.0)
        with self.assertRaisesRegex(ValueError, "outside configured lease"):
            self.gate.arm(61, now=1000.0)


if __name__ == "__main__":
    unittest.main()
