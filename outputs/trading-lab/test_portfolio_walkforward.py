import unittest

from backtest import Candle
from portfolio_walkforward import portfolio_true_walk_forward
from portfolio_backtest import MultiPairPortfolioBacktester


class PortfolioWalkForwardTests(unittest.TestCase):
    def test_joint_selection_is_oos_and_carries_capital(self):
        candles = {
            "EUR/USD": [Candle(i, 1 + i * .01, 1 + i * .01, 1 + i * .01, 1 + i * .01) for i in range(30)],
            "GBP/USD": [Candle(i, 1.2 + i * .005, 1.2 + i * .005, 1.2 + i * .005, 1.2 + i * .005) for i in range(30)],
        }
        candidates = {
            pair: [
                ("flat", lambda: (lambda history: "flat")),
                ("buy", lambda: (lambda history: "buy"),
                ),
            ]
            for pair in candles
        }
        result = portfolio_true_walk_forward(
            candles,
            candidates,
            train_size=10,
            test_size=5,
            starting_cash=10000,
            portfolio_backtester_factory=lambda cash: MultiPairPortfolioBacktester(
                starting_cash=cash,
                per_position_notional=1000,
                max_positions=1,
                max_exposure=1000,
                spread_bps=0,
                slippage_bps=0,
            ),
        )
        self.assertEqual(result["window_count"], 4)
        self.assertGreater(result["ending_cash"], result["starting_cash"])
        self.assertEqual(result["windows"][0]["oos_starting_cash"], 10000)
        self.assertEqual(
            result["windows"][1]["oos_starting_cash"],
            result["windows"][0]["oos_ending_cash"],
        )


if __name__ == "__main__":
    unittest.main()
