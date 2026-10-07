import os,tempfile,unittest
from forex_risk import FXRisk,RiskConfig
from forex_paper import ForexPaperBroker
class ForexTests(unittest.TestCase):
 def test_limits(self):
  r=FXRisk(RiskConfig(max_trade_notional=100,max_exposure=200,max_positions=2))
  r.validate_entry(1000,0,[],100)
  with self.assertRaises(ValueError):r.validate_entry(1000,0,[],101)
 def test_paper_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
   p=b.open("EUR/USD",1.10,500,"buy")
   self.assertEqual(p["side"],"buy")
   s=b.snapshot({"EUR/USD":{"price":1.12}})
   self.assertAlmostEqual(s["account"] if "account" in s else s["equity"],10000+500*(1.12-1.10)/1.10,places=6)
   c=b.close(p["id"],1.12)
   self.assertGreater(c["pnl"],0)
if __name__=="__main__":unittest.main()
