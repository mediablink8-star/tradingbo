import unittest

from backtest import Candle
from equity_backtest import EquityBacktester
from true_walkforward import true_walk_forward


class EquityBacktesterTests(unittest.TestCase):
    def setUp(self):
        self.candles = [
            Candle(1, 100, 100, 100, 100),
            Candle(2, 110, 112, 109, 111),
            Candle(3, 120, 121, 119, 120),
            Candle(4, 115, 116, 114, 115),
        ]

    def test_signal_fills_next_open_and_closes_at_next_open(self):
        result = EquityBacktester(
            starting_cash=10000, notional=1000,
            spread_bps=0, slippage_bps=0, commission_bps=0,
        ).run(self.candles, lambda history: "buy" if len(history) == 1 else "flat")
        trade = result["trades"][0]
        self.assertEqual(trade["entry_price"], 110)
        self.assertEqual(trade["exit_price"], 120)
        self.assertAlmostEqual(trade["pnl"], 1000 / 110 * 10)
        self.assertEqual(trade["reason"], "signal")

    def test_round_trip_costs_make_flat_market_lose(self):
        candles = [Candle(i, 100, 100, 100, 100) for i in range(4)]
        result = EquityBacktester(
            starting_cash=10000, notional=1000,
            spread_bps=4, slippage_bps=3, commission_bps=5,
        ).run(candles, lambda history: "buy" if len(history) == 1 else "flat")
        self.assertLess(result["ending_cash"], result["starting_cash"])
        self.assertLess(result["trades"][0]["pnl"], 0)

    def test_end_of_data_closes_open_position(self):
        result = EquityBacktester(
            starting_cash=10000, notional=1000,
            spread_bps=0, slippage_bps=0, commission_bps=0,
        ).run(self.candles[:2], lambda history: "buy" if len(history) == 1 else None)
        self.assertEqual(result["trades"][0]["reason"], "end_of_data")
        self.assertFalse(result["history"][-1]["open_position"])

    def test_rejects_bad_candles_and_non_cash_sizing(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            EquityBacktester().run(
                [Candle(1, 100, 100, 100, 100), Candle(1, 100, 100, 100, 100)],
                lambda history: None,
            )
        with self.assertRaisesRegex(ValueError, "notional"):
            EquityBacktester(starting_cash=1000, notional=1001)

    def test_stock_engine_uses_existing_walk_forward_selection(self):
        candles = [Candle(i, 100 + i, 100 + i, 100 + i, 100 + i) for i in range(40)]
        candidates = [
            ("buy_once", lambda: (lambda history: "buy" if len(history) == 1 else "flat")),
            ("hold", lambda: (lambda history: "buy" if len(history) == 1 else None)),
        ]
        result = true_walk_forward(
            candles,
            lambda: EquityBacktester(spread_bps=0, slippage_bps=0, symbol="TEST"),
            candidates,
            train_size=12, test_size=5, gap=1, metric="return_pct", min_trades=0,
        )
        self.assertGreater(result["window_count"], 0)
        self.assertIn("oos_return_pct", result["windows"][0])


if __name__ == "__main__":
    unittest.main()
