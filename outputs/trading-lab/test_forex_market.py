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


if __name__ == "__main__":
    unittest.main()
