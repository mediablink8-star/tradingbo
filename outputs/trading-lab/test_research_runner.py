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
            "EUR/USD", self._candles(), train_size=12, test_size=5, holdout_size=5,
        )
        self.assertEqual(report["pair"], "EUR/USD")
        self.assertEqual(report["final_holdout"]["holdout_start"], 35)
        self.assertIn("selected_strategy", report["final_holdout"])


    def test_final_portfolio_holdout_starts_with_fresh_cash(self):
        with tempfile.TemporaryDirectory() as directory:
            for pair in ("EUR/USD", "GBP/USD"):
                save_json(self._candles(), os.path.join(directory, pair.replace("/", "_") + ".json"))
            report = run_dataset(
                directory, pairs=("EUR/USD", "GBP/USD"),
                train_size=12, test_size=5, holdout_size=5,
            )
            self.assertEqual(report["portfolio"]["final_holdout"]["starting_cash"], 10000.0)

    def test_run_dataset_includes_joint_portfolio_research(self):
        with tempfile.TemporaryDirectory() as directory:
            for pair in ("EUR/USD", "GBP/USD"):
                save_json(self._candles(), os.path.join(directory, pair.replace("/", "_") + ".json"))
            report = run_dataset(
                directory,
                pairs=("EUR/USD", "GBP/USD"),
                train_size=12,
                test_size=5,
                holdout_size=5,
            )
            self.assertEqual(sorted(report["pairs"]), ["EUR/USD", "GBP/USD"])
            self.assertIn("walk_forward", report["portfolio"])
            self.assertIn("final_holdout", report["portfolio"])
            self.assertGreater(report["portfolio"]["walk_forward"]["window_count"], 0)


if __name__ == "__main__":
    unittest.main()
