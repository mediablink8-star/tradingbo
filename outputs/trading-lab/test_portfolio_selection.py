import unittest

from backtest import Candle
from portfolio_selection import select_portfolio_strategies


class PortfolioSelectionTests(unittest.TestCase):
    def test_selection_uses_shared_capital_training_result(self):
        candles = {
            "EUR/USD": [Candle(i, 1 + i * .01, 1 + i * .01, 1 + i * .01, 1 + i * .01) for i in range(12)],
            "GBP/USD": [Candle(i, 1.2 + i * .01, 1.2 + i * .01, 1.2 + i * .01, 1.2 + i * .01) for i in range(12)],
        }
        candidates = {
            pair: [
                ("flat", lambda: (lambda history: "flat")),
                ("buy", lambda: (lambda history: "buy")),
            ]
            for pair in candles
        }
        result = select_portfolio_strategies(candles, candidates, max_iterations=2)
        self.assertIn(result["selected"]["EUR/USD"], {"flat", "buy"})
        self.assertIn(result["selected"]["GBP/USD"], {"flat", "buy"})
        self.assertIn("ending_cash", result["training_result"])


if __name__ == "__main__":
    unittest.main()
