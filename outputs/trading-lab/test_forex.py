import os,tempfile,unittest
from forex_risk import FXRisk,RiskConfig
from forex_paper import ForexPaperBroker
class ForexTests(unittest.TestCase):
 def test_limits(self):
  r=FXRisk(RiskConfig(max_trade_notional=100,max_exposure=200,max_positions=2))
  r.validate_entry(1000,0,[],100)
  with self.assertRaises(ValueError):r.validate_entry(1000,0,[],101)
 def test_long_and_short_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
   p=b.open("EUR/USD",1.10,500,"buy");s=b.snapshot({"EUR/USD":{"price":1.12}})
   self.assertAlmostEqual(s["equity"],10000+(500/1.10)*(1.12-1.10)/1.0,places=6)
   c=b.close(p["id"],1.12);self.assertGreater(c["pnl"],0)
   p=b.open("GBP/USD",1.30,500,"sell");c=b.close(p["id"],1.28);self.assertGreater(c["pnl"],0)
 def test_short_unrealized_pnl(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"));b.open("USD/JPY",150,500,"sell")
   s=b.snapshot({"USD/JPY":{"price":149}});self.assertGreater(s["positions"][0]["unrealized_pnl"],0);self.assertAlmostEqual(s["positions"][0]["unrealized_pnl"],500*(150-149)/149,places=6)
 def test_daily_loss_and_exit_logic(self):
  r=FXRisk(RiskConfig(max_daily_loss=50));
  with self.assertRaises(ValueError):r.validate_daily_loss(-50)
  p={"side":"sell","entry_price":100,"opened":0};self.assertTrue(r.exits(p,102,1))
if __name__=="__main__":unittest.main()
