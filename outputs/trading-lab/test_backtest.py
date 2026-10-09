import unittest

from backtest import Candle, FXBacktester


class BacktestTests(unittest.TestCase):
    def test_costs_make_roundtrip_negative(self):
        candles = [Candle(1, 1, 1, 1, 1), Candle(2, 1, 1, 1, 1)]
        result = FXBacktester(spread_bps=2, slippage_bps=1).run(
            candles, lambda history: "buy" if len(history) == 1 else "flat"
        )
        self.assertLess(result["ending_cash"], result["starting_cash"])

    def test_buy_then_sell_profit(self):
        candles = [
            Candle(1, 1, 1, 1, 1),
            Candle(2, 1, 1.02, 1, 1.02),
        ]
        result = FXBacktester(spread_bps=0, slippage_bps=0).run(
            candles, lambda history: "buy" if len(history) == 1 else "flat"
        )
        self.assertGreater(result["ending_cash"], result["starting_cash"])

    def test_signal_fills_at_next_candle_open(self):
        candles = [
            Candle(1, 1.0, 1.0, 1.0, 1.0),
            Candle(2, 1.1, 1.1, 1.1, 1.1),
            Candle(3, 1.2, 1.2, 1.2, 1.2),
        ]
        result = FXBacktester(spread_bps=0, slippage_bps=0).run(
            candles, lambda history: "buy" if len(history) == 1 else "flat"
        )
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["entry_price"], 1.1)
        self.assertAlmostEqual(trade["exit_price"], 1.2)

    def test_usd_jpy_pnl_is_converted_to_usd(self):
        candles = [Candle(1, 100, 100, 100, 100), Candle(2, 100, 101, 100, 101)]
        result = FXBacktester(
            spread_bps=0, slippage_bps=0, notional=1000, pair="USD/JPY"
        ).run(candles, lambda history: "buy" if len(history) == 1 else "flat")
        self.assertAlmostEqual(result["trades"][0]["pnl"], 1000 * (1 - 100 / 101), places=8)

    def test_eur_usd_position_sizing_is_not_double_divided(self):
        candles = [
            Candle(1, 1.1, 1.1, 1.1, 1.1),
            Candle(2, 1.1, 1.11, 1.1, 1.11),
        ]
        result = FXBacktester(
            spread_bps=0, slippage_bps=0, notional=1000, pair="EUR/USD"
        ).run(candles, lambda history: "buy" if len(history) == 1 else "flat")
        self.assertAlmostEqual(result["trades"][0]["pnl"], 1000 * (1.11 / 1.1 - 1), places=8)


if __name__ == "__main__":
    unittest.main()
