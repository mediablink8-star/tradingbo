import unittest
from research_report import summarize_walk_forward, build_research_report


class ResearchReportTests(unittest.TestCase):
    def test_compounds_oos_returns_and_counts_selections(self):
        result = summarize_walk_forward({
            "windows": [
                {"oos_return_pct": 10, "oos_sharpe": 1, "oos_max_drawdown": 2, "selected_strategy": "ema"},
                {"oos_return_pct": -5, "oos_sharpe": 0, "oos_max_drawdown": 4, "selected_strategy": "breakout"},
                {"oos_return_pct": 10, "oos_sharpe": 2, "oos_max_drawdown": 3, "selected_strategy": "ema"},
            ]
        })
        self.assertAlmostEqual(result["compounded_oos_return_pct"], 14.95)
        self.assertEqual(result["profitable_oos_windows"], 2)
        self.assertEqual(result["strategy_selection_frequency"]["ema"], 2)
        self.assertEqual(result["worst_oos_drawdown"], 4)

    def test_build_report_preserves_windows_and_holdout(self):
        wf = {"windows": [{"selected_strategy": "ema", "oos_return_pct": 1,
                           "oos_sharpe": 1, "oos_max_drawdown": 1}]}
        holdout = {"return_pct": 2}
        report = build_research_report("EUR/USD", wf, holdout)
        self.assertEqual(report["pair"], "EUR/USD")
        self.assertEqual(report["final_holdout"], holdout)
        self.assertEqual(len(report["windows"]), 1)


if __name__ == "__main__":
    unittest.main()
