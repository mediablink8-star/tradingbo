import os,tempfile,unittest,time
from forex_risk import FXRisk,RiskConfig
from forex_paper import ForexPaperBroker
from forex_market import ALL_PAIRS,STOCKS,_spread,_yahoo_symbol,is_metal,is_stock
class ForexTests(unittest.TestCase):
 def test_risk_config_rejects_non_finite_limits(self):
  with self.assertRaisesRegex(ValueError,"max_exposure"):
   RiskConfig(max_exposure=float("nan"))
  with self.assertRaisesRegex(ValueError,"max_leverage"):
   RiskConfig(max_leverage=float("inf"))
 def test_risk_config_rejects_invalid_position_count(self):
  with self.assertRaisesRegex(ValueError,"max_positions"):
   RiskConfig(max_positions=0)
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
 def test_snapshot_flags_missing_marks_instead_of_implying_complete_equity(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
   opened=b.open("EUR/USD",1.10,500,"buy")
   snap=b.snapshot({})
   self.assertFalse(snap["mark_data_complete"])
   self.assertFalse(snap["mark_data_fresh"])
   self.assertEqual(snap["unmarked_positions"],[opened["id"]])
   self.assertFalse(snap["positions"][0]["mark_valid"])
 def test_snapshot_flags_stale_marks_as_not_fresh(self):
  with tempfile.TemporaryDirectory() as d:
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
   opened=b.open("EUR/USD",1.10,500,"buy")
   stale={"EUR/USD":{"bid":1.09,"ask":1.0902,"observed":time.time()-301,"provider_date":time.strftime("%Y-%m-%d",time.gmtime())}}
   snap=b.snapshot(stale)
   self.assertTrue(snap["mark_data_complete"])
   self.assertFalse(snap["mark_data_fresh"])
   self.assertTrue(snap["positions"][0]["mark_valid"])
   self.assertFalse(snap["positions"][0]["mark_fresh"])
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
 def test_currency_concentration_blocks_shared_currency_overload(self):
  with tempfile.TemporaryDirectory() as d:
   risk=FXRisk(RiskConfig(max_currency_exposure=750,max_trade_notional=1000))
   b=ForexPaperBroker(os.path.join(d,"fx.sqlite"),risk)
   b.open("EUR/USD",1.10,500,"buy")
   marks={"EUR/USD":{"bid":1.0999,"ask":1.1001,"observed":time.time(),"provider_date":time.strftime("%Y-%m-%d",time.gmtime())}}
   with self.assertRaisesRegex(ValueError,"currency concentration.*USD"):
    b.open("GBP/USD",1.30,300,"buy",prices=marks)
   self.assertEqual(len(b.snapshot({})["positions"]),1)
  def test_currency_exposure_counts_opposing_positions_gross(self):
   r=FXRisk(RiskConfig(max_currency_exposure=750))
   positions=[("id","EUR/USD","buy",0,1.1,0,500)]
   with self.assertRaisesRegex(ValueError,"currency concentration.*EUR"):
    r.validate_entry(10000,500,positions,300,pair="EUR/USD",side="sell")
class StockTests(unittest.TestCase):
  def test_stock_universe_uses_bare_yahoo_tickers(self):
   for pair,sym in (("AAPL/USD","AAPL"),("MSFT/USD","MSFT"),("NVDA/USD","NVDA"),
                    ("TSLA/USD","TSLA"),("AMZN/USD","AMZN"),("META/USD","META")):
    self.assertEqual(_yahoo_symbol(pair),sym)
    self.assertTrue(is_stock(pair))
    self.assertFalse(is_metal(pair))
   self.assertIn("AAPL/USD",ALL_PAIRS)
   self.assertFalse(is_stock("EUR/USD"))
  def test_fx_and_metal_paths_unchanged(self):
   self.assertEqual(_yahoo_symbol("EUR/USD"),"EURUSD=X")
   self.assertEqual(_yahoo_symbol("XAU/USD"),"GC=F")
   self.assertTrue(is_metal("XAU/USD"))
   self.assertFalse(is_stock("XAU/USD"))
   self.assertEqual(_spread("EUR/USD"),1.0)
   self.assertEqual(_spread("AAPL/USD"),2.0)
   self.assertEqual(_spread("UNKNOWN/USD"),1.5)
  def test_stock_legs_convert_to_usd_at_par(self):
   r=FXRisk(RiskConfig())
   self.assertEqual(r._currency_legs("AAPL/USD","buy"),(("AAPL",1.0),("USD",-1.0)))
   with tempfile.TemporaryDirectory() as d:
    b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
    self.assertEqual(b._base_to_usd("AAPL/USD",300),300)
    self.assertEqual(b._quote_to_usd("AAPL/USD",300),1.0)
  def test_invalid_codes_rejected(self):
   r=FXRisk(RiskConfig())
   for bad in ("A/B","TOOLONGNAME/USD","BRK.B/USD","AAPL/AAPL","AAPL","USD/"):
    with self.assertRaises(ValueError,msg=bad):
     r._currency_legs(bad,"buy")
   with tempfile.TemporaryDirectory() as d:
    b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
    with self.assertRaises(ValueError):b.open("A/B",1.0,100,"buy")
    with self.assertRaises(ValueError):b.open("TOOLONGNAME/USD",1.0,100,"buy")
  def test_stock_concentration_caps_single_name(self):
   r=FXRisk(RiskConfig(max_currency_exposure=750))
   positions=[("id","AAPL/USD","buy",0,300,0,500)]
   with self.assertRaisesRegex(ValueError,"currency concentration.*AAPL"):
    r.validate_entry(10000,500,positions,300,pair="AAPL/USD",side="sell")
  def test_stock_concentration_caps_shared_usd_leg(self):
   with tempfile.TemporaryDirectory() as d:
    risk=FXRisk(RiskConfig(max_currency_exposure=750,max_trade_notional=1000))
    b=ForexPaperBroker(os.path.join(d,"fx.sqlite"),risk)
    b.open("AAPL/USD",300,500,"buy")
    marks={"AAPL/USD":{"bid":299.9,"ask":300.1,"observed":time.time(),"provider_date":time.strftime("%Y-%m-%d",time.gmtime())}}
    with self.assertRaisesRegex(ValueError,"currency concentration.*USD"):
     b.open("MSFT/USD",500,300,"buy",prices=marks)
    self.assertEqual(len(b.snapshot({})["positions"]),1)
  def test_stock_roundtrip_marks_to_usd(self):
   with tempfile.TemporaryDirectory() as d:
    b=ForexPaperBroker(os.path.join(d,"fx.sqlite"))
    p=b.open("NVDA/USD",200,500,"buy")
    self.assertAlmostEqual(p["units"],500/200,places=9)
    s=b.snapshot({"NVDA/USD":{"price":203}})
    self.assertAlmostEqual(s["positions"][0]["unrealized_pnl"],(500/200)*(203-200),places=6)
    c=b.close(p["id"],203);self.assertAlmostEqual(c["pnl"],(500/200)*3,places=6)
if __name__=="__main__":unittest.main()
