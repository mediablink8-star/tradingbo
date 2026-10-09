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
            starting_cash=10000, per_position_notional=1000,
            max_exposure=2000, max_positions=2, spread_bps=0, slippage_bps=0,
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
            per_position_notional=1000, max_exposure=1000,
            spread_bps=0, slippage_bps=0,
        ).run(candles, {"EUR/USD": signal})
        self.assertEqual(len(result["trades"]), 1)
        self.assertGreater(result["trades"][0]["pnl"], 0)


    def test_intrabar_stop_precedes_target_when_both_are_touched(self):
        candles = {
            "EUR/USD": [
                Candle(0, 1.0, 1.0, 1.0, 1.0),
                Candle(1, 1.0, 1.0, 1.0, 1.0),
                Candle(2, 1.004, 1.03, .985, 1.01),
            ]
        }
        result = MultiPairPortfolioBacktester(
            per_position_notional=1000, max_exposure=1000,
            stop_loss_pct=.01, take_profit_pct=.02,
            spread_bps=0, slippage_bps=0,
        ).run(candles, {"EUR/USD": lambda history: "buy"})
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "stop_loss")
        self.assertAlmostEqual(trade["exit_price"], .99)
        self.assertLess(trade["pnl"], 0)

    def test_gap_through_stop_fills_at_worse_open(self):
        candles = {
            "EUR/USD": [
                Candle(0, 1.0, 1.0, 1.0, 1.0),
                Candle(1, 1.0, 1.0, 1.0, 1.0),
                Candle(2, .97, .98, .96, .975),
            ]
        }
        result = MultiPairPortfolioBacktester(
            per_position_notional=1000, max_exposure=1000,
            stop_loss_pct=.01, spread_bps=0, slippage_bps=0,
        ).run(candles, {"EUR/USD": lambda history: "buy"})
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "stop_loss")
        self.assertAlmostEqual(trade["exit_price"], .97)


    def test_rejects_non_monotonic_candles(self):
        candles = {
            "EUR/USD": [
                Candle(1, 1.0, 1.0, 1.0, 1.0),
                Candle(1, 1.1, 1.1, 1.1, 1.1),
            ]
        }
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MultiPairPortfolioBacktester().run(candles, {"EUR/USD": lambda h: "buy"})

    def test_rejects_impossible_ohlc(self):
        candles = {"EUR/USD": [Candle(1, 1.0, .9, .95, 1.0)]}
        with self.assertRaisesRegex(ValueError, "invalid candle high"):
            MultiPairPortfolioBacktester().run(candles, {"EUR/USD": lambda h: "buy"})

    def test_currency_concentration_limit_blocks_new_position(self):
        candles = {
            "EUR/USD": [Candle(i, 1 + i * .01, 1 + i * .01, 1 + i * .01, 1 + i * .01) for i in range(4)],
            "GBP/USD": [Candle(i, 1.2 + i * .01, 1.2 + i * .01, 1.2 + i * .01, 1.2 + i * .01) for i in range(4)],
        }
        signals = {pair: (lambda h: "buy") for pair in candles}
        result = MultiPairPortfolioBacktester(
            per_position_notional=1000, max_exposure=2000, max_positions=2,
            max_currency_exposure=1200, spread_bps=0, slippage_bps=0,
        ).run(candles, signals)
        self.assertLessEqual(max(row["open_positions"] for row in result["history"]), 1)

    def test_stop_loss_and_daily_loss_halt_are_recorded(self):
        candles = {
            "EUR/USD": [
                Candle(0, 1.0, 1.0, 1.0, 1.0),
                Candle(1, .98, .98, .98, .98),
                Candle(2, .97, .97, .97, .97),
            ],
            "GBP/USD": [
                Candle(0, 1.2, 1.2, 1.2, 1.2),
                Candle(1, 1.19, 1.19, 1.19, 1.19),
                Candle(2, 1.18, 1.18, 1.18, 1.18),
            ],
        }
        signals = {pair: (lambda h: "buy") for pair in candles}
        result = MultiPairPortfolioBacktester(
            per_position_notional=1000, max_exposure=2000, max_positions=2,
            stop_loss_pct=.01, max_daily_loss=5, spread_bps=0, slippage_bps=0,
        ).run(candles, signals)
        self.assertTrue(any(t["reason"] == "stop_loss" for t in result["trades"]))
        self.assertTrue(any(row["daily_loss_halted"] for row in result["history"]))


if __name__ == "__main__":
    unittest.main()
