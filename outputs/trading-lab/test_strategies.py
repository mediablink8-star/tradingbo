import unittest
from backtest import Candle,FXBacktester
from strategies import momentum_ema,mean_reversion,breakout
class StrategyTests(unittest.TestCase):
 def setUp(self):
  self.c=[Candle(i,1+i*.001,1+i*.001,1+i*.001,1+i*.001) for i in range(80)]
 def test_metrics_and_strategies(self):
  b=FXBacktester(spread_bps=1,slippage_bps=.5)
  for factory in (lambda:momentum_ema(5,10),lambda:mean_reversion(10,1),lambda:breakout(10)):
   r=b.run(self.c,factory());self.assertIn("sharpe",r);self.assertIn("profit_factor",r)
 def test_costs(self):
  c=[Candle(1,1,1,1,1),Candle(2,1,1,1,1)]
  r=FXBacktester(spread_bps=2,slippage_bps=1).run(c,lambda h:"buy" if len(h)==1 else "flat")
  self.assertLess(r["ending_cash"],r["starting_cash"])
if __name__=="__main__":unittest.main()
