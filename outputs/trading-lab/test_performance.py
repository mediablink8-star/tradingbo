import json,sqlite3,tempfile,time,unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from dataclasses import replace
from live_trial import initial,TrialStore,process_tick,S
from research_lab import Research
from market_evidence import evidence,assess,cost_hurdle,number
from execution_audit import reconcile
from test_paper_quotes import row,TOKEN,mint,route
from paper_quotes import QuoteExecution
from test_swaps import SwapTests,W,M

class PerformanceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';store=TrialStore(self.path);store.db.close();self.lab=Research(self.path)
 def tearDown(self):self.tmp.cleanup()
 def log(self,kind,payload):
  with closing(sqlite3.connect(self.path)) as db,db:db.execute('INSERT INTO live_log(received,kind,payload) VALUES(?,?,?)',(time.time(),kind,json.dumps(payload)))
 def state(self,id):
  with closing(sqlite3.connect(self.path)) as db:return json.loads(db.execute('SELECT state FROM research_runs WHERE id=?',(id,)).fetchone()[0])
 def tick(self,t):
  r=row(t);r['activity']=evidence({'txns':{'m5':{'buys':30,'sells':20}},'volume':{'m5':3000},'liquidity':{'usd':200000}},t)
  p=initial();p['watch']=[TOKEN];p['token_risk']={TOKEN:{'allowed':True,'expires':t+90}}
  self.lab.tick([r],t,p,[],QuoteExecution([],quote=route,rpc=mint,clock=lambda:t))
 def test_fresh_matched_books_and_duplicate_frames(self):
  self.tick(360);self.tick(360);runs=self.lab.snapshot()['runs'];self.assertEqual(len(runs),1);self.assertEqual(runs[0]['cycles'],1)
  self.assertEqual([b['equity'] for b in runs[0]['books']],[100,100,100])
  with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM research_frames').fetchone()[0],1)
 def test_ai_cost_only_charged_to_ai_once(self):
  self.tick(360);self.log('ai_usage_cost',{'amount':.2});self.tick(420);self.tick(420)
  books=self.lab.snapshot()['runs'][0]['books'];self.assertAlmostEqual(books[0]['equity'],99.8);self.assertEqual(books[1]['equity'],100);self.assertEqual(books[2]['equity'],100)
 def test_no_loss_no_fabricated_review(self):self.assertEqual(self.lab.propose()['status'],'insufficient_evidence');self.assertFalse(self.lab.snapshot()['proposals'])
 def proposal(self):
  self.log('paper_sell',{'trade_pnl':-1,'portfolio':'strategy','token':TOKEN,'timestamp':time.time()});return self.lab.propose()['id']
 def test_frozen_challenger_idempotent_future_and_archive(self):
  self.tick(360);p=self.proposal();run=self.lab.test_proposal(p)['run'];self.assertEqual(self.lab.test_proposal(p)['run'],run);self.assertEqual(self.state(run)['ticks'],0)
  self.tick(420);self.assertEqual(self.state(run)['ticks'],1);self.assertEqual(self.state(run)['rules_momentum'],.05)
  self.lab.finish(p);self.tick(480);self.assertEqual(self.state(run)['ticks'],1);self.assertTrue(self.state(run)['completed'])
  p2=self.proposal();self.assertNotEqual(self.lab.test_proposal(p2)['run'],run)
 def test_briefing_attribution_and_unknown_day_change(self):
  now=time.time();self.log('paper_sell',{'portfolio':'baseline','trade_pnl':100,'token':'B','timestamp':now});self.log('paper_sell',{'portfolio':'strategy','trade_pnl':-2,'token':'A','timestamp':now})
  b=self.lab.briefing(initial(),{'checklist':[{'ok':False}],'alerts':[]},{'budget':{}});self.assertIsNone(b['capital_change_today']);self.assertEqual(b['closed_trades_today'],1);self.assertEqual(b['best_trade']['token'],'A')
  for n in [100,99]:self.log('valuation',{'timestamp':now,'strategy':n})
  self.assertEqual(self.lab.briefing(initial(),{'checklist':[],'alerts':[]},{'budget':{}})['capital_change_today'],-1)
 def test_persistent_liquidity_rejection(self):
  s=initial();s['watch']=[TOKEN];s['quality_policy_version']=1
  for t,liq in [(360,200000),(420,150000),(480,150000)]:
   r=row(t);r['liquidity']=liq;r['activity']=evidence({'txns':{'m5':{'buys':30,'sells':20}},'volume':{'m5':3000},'liquidity':{'usd':liq}},t)
   process_tick(s,[r],t,settings=replace(S,operating_cost_step=0))
  self.assertEqual(s['screening'][0]['reason'],'liquidity_deterioration');self.assertNotIn(TOKEN,s['history'])

class EvidenceTests(unittest.TestCase):
 def test_numbers_missing_invalid(self):
  for v in [None,True,float('nan'),float('inf'),-1,'bad']:self.assertIsNone(number(v))
 def test_missing_and_outlier_fail_closed(self):
  r=row(360);self.assertIn('activity_evidence_missing',assess(r,[],360)['reasons']);r['activity']=evidence({'txns':{'m5':{'buys':30,'sells':20}},'volume':{'m5':300000},'liquidity':{'usd':200000}},360);self.assertIn('volume_quality_outlier',assess(r,[],360)['reasons']);self.assertIsNone(r['activity']['unique_traders'])
 def test_stale_activity_rejected(self):
  self.assertIn('stale_activity',assess(row(360),[],451)['reasons'])
 def test_cost_margin_and_uncertainty(self):
  self.assertTrue(cost_hurdle(9.9)['allowed']);self.assertFalse(cost_hurdle(9.7)['allowed']);self.assertFalse(cost_hurdle(9.9,.2)['allowed']);self.assertIn('assumption',cost_hurdle(9.9)['basis'])

class ReconciliationTests(unittest.TestCase):
 def record(self):return {'side':'buy','wallet':W,'mint':M,'expected_output_base_units':'1000','minimum_output_base_units':'990'}
 def result(self,amount):return {'meta':{'err':None,'fee':5,'preBalances':[100],'postBalances':[90],'preTokenBalances':[],'postTokenBalances':[{'owner':W,'mint':M,'uiTokenAmount':{'amount':str(amount)}}]}}
 def test_quote_fill_and_breach(self):
  good=reconcile(self.record(),self.result(995));self.assertEqual(good['status'],'verified');self.assertEqual(good['quote_shortfall_bps'],50);self.assertEqual(reconcile(self.record(),self.result(980))['status'],'minimum_output_breach')
 def test_unknown_and_failed_never_fabricate(self):
  self.assertEqual(reconcile(self.record(),{'meta':{}})['status'],'unknown');r=self.result(995);r['meta']['err']='failed';self.assertEqual(reconcile(self.record(),r)['status'],'failed')

class RecoveryTests(SwapTests):
 def test_wallet_cost_hurdle_rejects_expensive_roundtrip(self):
  from test_swaps import routed
  def expensive(a,b,n):
   q=routed(a,b,n)
   if a==M:q['otherAmountThreshold']='48000000'
   return q
  with patch('swaps.quote',side_effect=expensive):
   with self.assertRaisesRegex(ValueError,'uncertainty'):self.prepare()
  self.assertFalse(self.service.state()['records'])
 def test_duplicate_intent_rejected_before_network(self):
  self.prepare()
  with patch('swaps.quote',side_effect=AssertionError('Must not quote')):
   with self.assertRaisesRegex(ValueError,'unresolved'):self.prepare()
 def test_recovery_read_only_matching_signature(self):
  intent=self.prepare();self.service.ready(intent['id'],W);methods=[]
  def rpc(method,args):
   methods.append(method)
   if method=='getSignaturesForAddress':return [{'signature':'1'*64,'blockTime':time.time()}]
   return self.rpc(method,args)
  with patch('swaps.rpc',side_effect=rpc):r=self.service.recover(intent['id'])
  self.assertEqual(r['state'],'confirmed');self.assertNotIn('sendTransaction',methods)
 def test_unmatched_recovery_preserves_reservation(self):
  intent=self.prepare();self.service.ready(intent['id'],W)
  with patch('swaps.rpc',return_value=[]):self.assertEqual(self.service.recover(intent['id'])['state'],'unresolved')
  self.assertEqual(self.service.state()['records'][0]['state'],'awaiting_wallet')

del SwapTests
if __name__=='__main__':unittest.main()
