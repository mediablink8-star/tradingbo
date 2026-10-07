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
 def test_usd_jpy_pnl_is_converted_to_usd(self):
  candles=[Candle(1,100,100,100,100),Candle(2,101,101,101,101)]
  r=FXBacktester(spread_bps=0,slippage_bps=0,notional=1000,pair="USD/JPY").run(
   candles,lambda h:"buy" if len(h)==1 else "flat"
  )
  self.assertAlmostEqual(r["trades"][0]["pnl"],1000*(1-100/101),places=8)

 def test_eur_usd_position_sizing_is_not_double_divided(self):
  candles=[Candle(1,1.1,1.1,1.1,1.1),Candle(2,1.11,1.11,1.11,1.11)]
  r=FXBacktester(spread_bps=0,slippage_bps=0,notional=1000,pair="EUR/USD").run(
   candles,lambda h:"buy" if len(h)==1 else "flat"
  )
  self.assertAlmostEqual(r["trades"][0]["pnl"],1000*(1.11/1.1-1),places=8)

if __name__=="__main__":unittest.main()
