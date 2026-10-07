import unittest

from backtest import Candle
from portfolio_backtest import MultiPairPortfolioBacktester


class PortfolioBacktestTests(unittest.TestCase):
    def test_shared_capital_limits_exposure_and_positions(self):
        candles = {
            "EUR/USD": [Candle(i, 1 + i * .01, 1 + i * .01, 1 + i * .01, 1 + i * .01) for i in range(6)],
            "GBP/USD": [Candle(i, 1.2 + i * .01, 1.2 + i * .01, 1.2 + i * .01, 1.2 + i * .01) for i in range(6)],
            "USD/JPY": [Candle(i, 150 - i, 150 - i, 150 - i, 150 - i) for i in range(6)],
            "AUD/USD": [Candle(i, .7 + i * .01, .7 + i * .01, .7 + i * .01, .7 + i * .01) for i in range(6)],
        }
        signals = {pair: (lambda h: "buy") for pair in candles}
        result = MultiPairPortfolioBacktester(
            starting_cash=10000,
            per_position_notional=1000,
            max_exposure=2000,
            max_positions=2,
            spread_bps=0,
            slippage_bps=0,
        ).run(candles, signals)

        self.assertLessEqual(max(row["open_positions"] for row in result["history"]), 2)
        self.assertLessEqual(max(row["exposure"] for row in result["history"]), 2000)
        self.assertGreater(result["ending_cash"], result["starting_cash"])
        self.assertEqual(len(result["trades"]), 2)

    def test_flat_closes_position(self):
        candles = {
            "EUR/USD": [Candle(i, 1 + i * .01, 1 + i * .01, 1 + i * .01, 1 + i * .01) for i in range(4)]
        }
        def signal(history):
            return "buy" if len(history) < 3 else "flat"

        result = MultiPairPortfolioBacktester(
            per_position_notional=1000,
            max_exposure=1000,
            spread_bps=0,
            slippage_bps=0,
        ).run(candles, {"EUR/USD": signal})

        self.assertEqual(len(result["trades"]), 1)
        self.assertGreater(result["trades"][0]["pnl"], 0)


if __name__ == "__main__":
    unittest.main()
