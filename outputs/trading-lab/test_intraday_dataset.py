import unittest
from unittest.mock import patch

from backtest import Candle
from intraday_dataset import build_dataset, iter_months, merge_candles


class IntradayDatasetTests(unittest.TestCase):
    def test_iter_months(self):
        self.assertEqual(
            list(iter_months("2026-01", "2026-03")),
            ["2026-01", "2026-02", "2026-03"],
        )

    def test_merge_deduplicates_and_sorts(self):
        a = [Candle(2, 1, 1, 1, 1), Candle(1, 1, 1, 1, 1)]
        b = [Candle(2, 9, 9, 9, 9), Candle(3, 2, 2, 2, 2)]
        merged = merge_candles([a, b])
        self.assertEqual([c.timestamp for c in merged], [1, 2, 3])
        self.assertEqual(merged[1].close, 9)

    @patch("intraday_dataset.load_month")
    def test_build_writes_manifest(self, load_month, tmp_path=None):
        import tempfile
        import os
        from unittest.mock import patch

        candles = [
            Candle(0, 1, 1.1, 0.9, 1.05),
            Candle(900, 1.05, 1.1, 1.0, 1.08),
        ]
        load_month.return_value = candles
        with tempfile.TemporaryDirectory() as output:
            manifest = build_dataset(
                ["EUR/USD"], "2026-01", "2026-02", output, "15min"
            )
            self.assertEqual(manifest["pairs"]["EUR/USD"]["rows"], 2)
            self.assertTrue(os.path.exists(os.path.join(output, "manifest.json")))


if __name__ == "__main__":
    unittest.main()
