import unittest
import tempfile
import os

from backtest import Candle
from historical import save_json
from research_runner import run_pair, run_dataset


class ResearchRunnerTests(unittest.TestCase):
    def _candles(self, n=40):
        return [Candle(i, 100 + i, 100 + i, 100 + i, 100 + i) for i in range(n)]

    def test_run_pair_keeps_holdout_separate(self):
        report = run_pair(
            "EUR/USD",
            self._candles(),
            train_size=10,
            test_size=5,
            holdout_size=5,
        )
        self.assertEqual(report["pair"], "EUR/USD")
        self.assertEqual(report["final_holdout"]["holdout_start"], 35)
        self.assertIn("selected_strategy", report["final_holdout"])

    def test_run_dataset_reads_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            save_json(self._candles(), os.path.join(directory, "EUR_USD.json"))
            report = run_dataset(directory, pairs=("EUR/USD",), train_size=10, test_size=5, holdout_size=5)
            self.assertEqual(list(report["pairs"]), ["EUR/USD"])


if __name__ == "__main__":
    unittest.main()
