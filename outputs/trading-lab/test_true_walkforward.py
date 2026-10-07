import unittest
from backtest import Candle, FXBacktester
from true_walkforward import true_walk_forward


class TrueWalkForwardTests(unittest.TestCase):
    def test_selects_factory_on_train_and_evaluates_unseen_test(self):
        candles = [Candle(i, 100 + i * 0.1, 100 + i * 0.1, 100 + i * 0.1, 100 + i * 0.1) for i in range(20)]
        candidates = [
            ("fast", lambda: (lambda h: "buy")),
            ("flat", lambda: (lambda h: "flat")),
        ]
        result = true_walk_forward(
            candles,
            lambda: FXBacktester(spread_bps=0, slippage_bps=0, notional=1000),
            candidates, train_size=10, test_size=5,
        )
        self.assertEqual(result["window_count"], 2)
        self.assertEqual(result["windows"][0]["selected_strategy"], "fast")
        self.assertEqual(result["windows"][0]["test_start"], 10)
        self.assertGreater(result["windows"][0]["oos_return_pct"], 0)

    def test_gap_and_constraints(self):
        candles = [Candle(i, 100 + i, 100 + i, 100 + i, 100 + i) for i in range(20)]
        candidates = [
            ("fast", lambda: (lambda h: "buy")),
            ("flat", lambda: (lambda h: "flat")),
        ]
        result = true_walk_forward(
            candles,
            lambda: FXBacktester(spread_bps=0, slippage_bps=0, notional=1000),
            candidates, train_size=8, test_size=4, gap=2,
            min_trades=1, max_drawdown=0,
        )
        self.assertEqual(result["windows"][0]["test_start"], 10)
        self.assertEqual(result["windows"][0]["gap"], 2)


if __name__ == "__main__":
    unittest.main()
