import unittest
from portfolio_report import aggregate_pair_reports


class PortfolioReportTests(unittest.TestCase):
    def test_equal_weight_and_cross_pair_aggregation(self):
        reports = {
            "EUR/USD": {
                "walk_forward": {
                    "compounded_oos_return_pct": 10,
                    "average_oos_sharpe": 1,
                    "worst_oos_drawdown": 2,
                    "profitable_oos_pct": 100,
                    "window_count": 1,
                },
                "windows": [{
                    "oos_return_pct": 10,
                    "selected_strategy": "ema",
                }],
            },
            "USD/JPY": {
                "walk_forward": {
                    "compounded_oos_return_pct": -5,
                    "average_oos_sharpe": 0,
                    "worst_oos_drawdown": 4,
                    "profitable_oos_pct": 0,
                    "window_count": 1,
                },
                "windows": [{
                    "oos_return_pct": -5,
                    "selected_strategy": "breakout",
                }],
            },
        }
        result = aggregate_pair_reports(reports)
        self.assertAlmostEqual(result["equal_weight_pair_return_pct"], 2.5)
        self.assertAlmostEqual(result["all_window_compounded_return_pct"], 4.5)
        self.assertEqual(result["all_window_profitable_pct"], 50)
        self.assertEqual(result["strategy_selection_frequency"]["ema"], 1)


if __name__ == "__main__":
    unittest.main()
