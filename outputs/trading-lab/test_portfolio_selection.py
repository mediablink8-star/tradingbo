import unittest

from backtest import Candle
from portfolio_backtest import MultiPairPortfolioBacktester
from portfolio_selection import select_portfolio_strategies


class PortfolioSelectionTests(unittest.TestCase):
    def test_selection_uses_shared_capital_and_position_constraint(self):
        candles = {
            "EUR/USD": [Candle(i, 1 + i * .01, 1 + i * .01, 1 + i * .01, 1 + i * .01) for i in range(12)],
            "GBP/USD": [Candle(i, 1.2 + i * .005, 1.2 + i * .005, 1.2 + i * .005, 1.2 + i * .005) for i in range(12)],
        }
        candidates = {
            pair: [
                ("flat", lambda: (lambda history: "flat")),
                ("buy", lambda: (lambda history: "buy")),
            ]
            for pair in candles
        }
        result = select_portfolio_strategies(
            candles,
            candidates,
            max_iterations=2,
            portfolio_backtester_factory=lambda: MultiPairPortfolioBacktester(
                starting_cash=10000,
                per_position_notional=1000,
                max_positions=1,
                max_exposure=1000,
                spread_bps=0,
                slippage_bps=0,
            ),
        )
        selected = result["selected"]
        self.assertEqual(sum(name == "buy" for name in selected.values()), 1)
        self.assertEqual(result["training_result"]["history"][-1]["open_positions"], 0)


if __name__ == "__main__":
    unittest.main()
