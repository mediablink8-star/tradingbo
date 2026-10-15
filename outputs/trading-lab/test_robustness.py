import unittest
from backtest import Candle,FXBacktester
from robustness import sensitivity,robustness_summary

class RobustnessTests(unittest.TestCase):
 def test_sensitivity_runs_same_cost_model(self):
  candles=[Candle(i,1+i*.001,1+i*.001,1+i*.001,1+i*.001) for i in range(20)]
  def buy_once(history): return "buy" if len(history)==1 else "flat"
  r=sensitivity(candles,lambda:FXBacktester(spread_bps=1,slippage_bps=.5),{"buy_once":buy_once})
  self.assertEqual(r["buy_once"]["trades"],1)
  self.assertIn("sharpe",r["buy_once"])
 def test_summary_is_deterministic(self):
  r=robustness_summary({"a":{"sharpe":1,"return_pct":2,"max_drawdown":3},"b":{"sharpe":3,"return_pct":4,"max_drawdown":1}})
  self.assertEqual(r["median_sharpe"],2)
  self.assertEqual(r["median_return_pct"],3)

if __name__=="__main__":unittest.main()
