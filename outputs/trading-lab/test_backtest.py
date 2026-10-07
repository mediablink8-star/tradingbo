import unittest
from backtest import Candle,FXBacktester
class BacktestTests(unittest.TestCase):
 def test_costs_make_roundtrip_negative(self):
  candles=[Candle(1,1,1,1,1),Candle(2,1,1,1,1)]
  r=FXBacktester(spread_bps=2,slippage_bps=1).run(candles,lambda h:"buy" if len(h)==1 else "flat")
  self.assertLess(r["ending_cash"],r["starting_cash"])
 def test_buy_then_sell_profit(self):
  candles=[Candle(1,1,1,1,1),Candle(2,1.02,1.02,1.02,1.02)]
  r=FXBacktester(spread_bps=0,slippage_bps=0).run(candles,lambda h:"buy" if len(h)==1 else "flat")
  self.assertGreater(r["ending_cash"],r["starting_cash"])
if __name__=="__main__":unittest.main()
