import os,tempfile,unittest,time
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
 def test_snapshot_marks_positions_at_executable_exit_side(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
   long=b.open("EUR/USD",1.10,500,"buy")
   marks={"EUR/USD":{"bid":1.09,"ask":1.0902,"observed":time.time(),"provider_date":time.strftime("%Y-%m-%d",time.gmtime())},"GBP/USD":{"bid":1.3098,"ask":1.31}}
   short=b.open("GBP/USD",1.30,500,"sell",prices=marks)
   snap=b.snapshot(marks)
   pnl={p["id"]:p["unrealized_pnl"] for p in snap["positions"]}
   self.assertAlmostEqual(pnl[long["id"]],long["units"]*(1.09-1.10),places=6)
   self.assertAlmostEqual(pnl[short["id"]],short["units"]*(1.30-1.31),places=6)
   self.assertAlmostEqual(snap["daily_pnl"],snap["realized_pnl"]+snap["unrealized_pnl"],places=6)
 def test_short_unrealized_pnl(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"));b.open("USD/JPY",150,500,"sell")
   s=b.snapshot({"USD/JPY":{"price":149}});self.assertGreater(s["positions"][0]["unrealized_pnl"],0);self.assertAlmostEqual(s["positions"][0]["unrealized_pnl"],500*(150-149)/149,places=6)
 def test_unrealized_loss_blocks_new_paper_position(self):
  with tempfile.TemporaryDirectory() as d:
   risk=FXRisk(RiskConfig(max_daily_loss=5,stop_loss_pct=0.5))
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"),risk)
   b.open("EUR/USD",1.10,500,"buy")
   marks={"EUR/USD":{"bid":1.08,"ask":1.0801,"observed":time.time(),"provider_date":time.strftime("%Y-%m-%d",time.gmtime())}}
   with self.assertRaisesRegex(ValueError,"Daily FX loss limit reached"):
    b.open("GBP/USD",1.30,500,"buy",prices=marks)
   self.assertEqual(len(b.snapshot({"EUR/USD":{"price":1.08}})["positions"]),1)
 def test_daily_loss_halt_is_latched_until_next_utc_day(self):
  # Regression specification: a breached daily loss limit must remain latched
  # even if marked PnL later recovers, rather than permitting a new entry.
  with tempfile.TemporaryDirectory() as d:
   risk=FXRisk(RiskConfig(max_daily_loss=5,stop_loss_pct=0.5))
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"),risk)
   b.open("EUR/USD",1.10,500,"buy")
   today=time.strftime("%Y-%m-%d",time.gmtime())
   losing={"EUR/USD":{"bid":1.08,"ask":1.0801,"observed":time.time(),"provider_date":today}}
   with self.assertRaisesRegex(ValueError,"Daily FX loss limit reached"):
    b.open("GBP/USD",1.30,500,"buy",prices=losing)
   recovered={"EUR/USD":{"bid":1.10,"ask":1.1001,"observed":time.time(),"provider_date":today}}
   with self.assertRaisesRegex(ValueError,"remains halted"):
    b.open("GBP/USD",1.30,500,"buy",prices=recovered)
   import sqlite3,datetime
   db=sqlite3.connect(os.path.join(d,"fx.sqlite"))
   yesterday=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
   db.execute("UPDATE fx_account SET day=? WHERE id=1",(yesterday,));db.commit();db.close()
   self.assertFalse(b.snapshot(recovered)["daily_halted"])
   b.open("GBP/USD",1.30,500,"buy",prices=recovered)
 def test_stale_mark_fails_closed_for_new_entry(self):
  with tempfile.TemporaryDirectory() as d:
   risk=FXRisk(RiskConfig(max_daily_loss=50))
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"),risk)
   b.open("EUR/USD",1.10,500,"buy")
   stale={"EUR/USD":{"bid":1.08,"ask":1.0801,"observed":time.time()-301,"provider_date":time.strftime("%Y-%m-%d",time.gmtime())}}
   with self.assertRaisesRegex(ValueError,"Stale quote"):
    b.open("GBP/USD",1.30,500,"buy",prices=stale)
 def test_missing_mark_fails_closed_for_new_entry(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
   b.open("EUR/USD",1.10,500,"buy")
   with self.assertRaisesRegex(ValueError,"Missing current price"):
    b.open("GBP/USD",1.30,500,"buy",prices={})
 def test_daily_loss_and_exit_logic(self):
  r=FXRisk(RiskConfig(max_daily_loss=50));
  with self.assertRaises(ValueError):r.validate_daily_loss(-50)
  p={"side":"sell","entry_price":100,"opened":0};self.assertTrue(r.exits(p,102,1))
if __name__=="__main__":unittest.main()
