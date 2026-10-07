import unittest
from backtest import Candle, FXBacktester
from research_selection import grid_candidates, filter_candidates, select_candidate, final_holdout


class ResearchSelectionTests(unittest.TestCase):
    def test_grid_candidates(self):
        candidates = grid_candidates("ema", lambda fast, slow: lambda h: "flat", {
            "fast": [5, 10], "slow": [20, 30]
        })
        self.assertEqual(len(candidates), 4)
        self.assertIn("fast=5", candidates[0][0])

    def test_constraints(self):
        rows = [
            {"trades": 0, "max_drawdown": 1, "return_pct": 10, "sharpe": 9},
            {"trades": 4, "max_drawdown": 8, "return_pct": 5, "sharpe": 2},
            {"trades": 5, "max_drawdown": 3, "return_pct": 2, "sharpe": 1},
        ]
        self.assertEqual(select_candidate(rows, min_trades=2, max_drawdown=5)["sharpe"], 1)
        self.assertEqual(len(filter_candidates(rows, min_trades=2, max_drawdown=5)), 1)

    def test_holdout_is_final_slice(self):
        candles = [Candle(i, 100+i, 100+i, 100+i, 100+i) for i in range(10)]
        result = final_holdout(
            candles, FXBacktester(spread_bps=0, slippage_bps=0),
            lambda h: "flat", train_size=7, holdout_size=3
        )
        self.assertEqual(result["holdout_start"], 7)
        self.assertEqual(result["holdout_end"], 9)


if __name__ == "__main__":
    unittest.main()
