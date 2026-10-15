import os
import time
import unittest
from unittest.mock import patch

import forex_market


class ForexMarketTests(unittest.TestCase):
    def test_yahoo_defaults_to_one_minute_candles(self):
        now = time.time()
        seen = []

        def fake_series(pair, interval):
            seen.append(interval)
            stamp = int(now - 60)
            return [{"t": stamp, "o": 1.1, "h": 1.101, "l": 1.099, "c": 1.1005}]

        with patch.dict(os.environ, {}, clear=True), patch.object(
            forex_market, "_yahoo_series", side_effect=fake_series
        ):
            result = forex_market._yahoo(["EUR/USD"])

        self.assertEqual(seen, ["1m"])
        quote = result["pairs"]["EUR/USD"]
        self.assertEqual(quote["observed"], float(int(now - 60)))
        self.assertEqual(quote["source"], "Yahoo Finance chart endpoint (unofficial)")

    def test_yahoo_keeps_good_symbols_when_one_symbol_fails(self):
        now = time.time()

        def fake_series(pair, interval):
            if pair == "GBP/USD":
                raise ValueError("provider unavailable")
            stamp = int(now - 60)
            return [{"t": stamp, "o": 1.1, "h": 1.101, "l": 1.099, "c": 1.1005}]

        with patch.dict(os.environ, {}, clear=True), patch.object(
            forex_market, "_yahoo_series", side_effect=fake_series
        ):
            result = forex_market._yahoo(["EUR/USD", "GBP/USD"])

        self.assertIn("EUR/USD", result["pairs"])
        self.assertNotIn("GBP/USD", result["pairs"])
        self.assertIn("GBP/USD", result["errors"])

    def test_default_snapshot_fills_missing_fx_from_ecb_only(self):
        yahoo_result = {
            "pairs": {
                "AAPL/USD": {
                    "pair": "AAPL/USD", "price": 200.0, "bid": 199.98,
                    "ask": 200.02, "observed": time.time(),
                    "provider_date": "2026-10-11 12:00:00",
                    "source": "Yahoo test",
                }
            },
            "errors": {"EUR/USD": "Yahoo timed out"},
            "source": "Yahoo test",
        }
        fallback_result = {
            "pairs": {
                "EUR/USD": {
                    "pair": "EUR/USD", "price": 1.1, "bid": 1.0999,
                    "ask": 1.1001, "observed": time.time() - 86400,
                    "provider_date": "2026-10-10",
                    "source": "ECB test",
                }
            },
            "source": "ECB test",
        }
        with patch.dict(os.environ, {}, clear=True), patch.object(
            forex_market, "_yahoo", return_value=yahoo_result
        ), patch.object(
            forex_market, "_frankfurter", return_value=fallback_result
        ) as fallback:
            result = forex_market.snapshot(["EUR/USD", "AAPL/USD"])

        fallback.assert_called_once_with(["EUR/USD"])
        self.assertEqual(result["pairs"]["AAPL/USD"]["price"], 200.0)
        self.assertEqual(result["pairs"]["EUR/USD"]["price"], 1.1)
        self.assertNotIn("EUR/USD", result["errors"])

    def test_explicit_ecb_provider_never_requests_stock_symbols(self):
        fx_result = {
            "pairs": {"EUR/USD": {"pair": "EUR/USD", "price": 1.1,
                                  "observed": time.time(), "source": "ECB test"}},
            "source": "ECB test",
        }
        stock_result = {
            "pairs": {"AAPL/USD": {"pair": "AAPL/USD", "price": 200.0,
                                   "observed": time.time(), "source": "Yahoo test"}},
            "source": "Yahoo test",
        }
        with patch.dict(os.environ, {"FX_PROVIDER": "ecb"}), patch.object(
            forex_market, "_frankfurter", return_value=fx_result
        ) as fallback, patch.object(
            forex_market, "_yahoo", return_value=stock_result
        ):
            result = forex_market.snapshot(["EUR/USD", "AAPL/USD"])

        fallback.assert_called_once_with(["EUR/USD"])
        self.assertEqual(set(result["pairs"]), {"EUR/USD", "AAPL/USD"})


if __name__ == "__main__":
    unittest.main()
