import unittest,time,tempfile
from unittest.mock import patch
from pathlib import Path
from live_trial import LiveTrial,TrialStore
from dataclasses import replace
from paper_quotes import QuoteExecution,usage_cost
from live_trial import initial,process_tick,S
import swaps
TOKEN='So11111111111111111111111111111111111111112'

def mint(*args):return {'value':{'owner':swaps.TOKEN,'data':{'parsed':{'type':'mint','info':{'decimals':6,'isInitialized':True}}}}}
def route(a,b,n):
    out=10_000_000 if b==TOKEN else 9_950_000
    return {'inputMint':a,'outputMint':b,'inAmount':str(n),'outAmount':str(out),'otherAmountThreshold':str(int(out*.995)),'swapMode':'ExactIn','slippageBps':50,'priceImpactPct':'0.001','routePlan':[{'swapInfo':{'ammKey':'pool'}}]}
def row(t):return {'token':TOKEN,'price':1,'liquidity':200000,'age_hours':30,'observed':t,'available':True,'exit_ok':True,'pair':'pool'}
class QuoteTests(unittest.TestCase):
    def adapter(self,quote=route):return QuoteExecution([],quote=quote,rpc=mint,clock=lambda:360)
    def test_threshold_units_and_no_double_fee(self):
        e=self.adapter();units,price=e.buy(row(360),S)
        self.assertEqual(units,9.95);self.assertAlmostEqual(price,10/9.95)
        p={'units':units,'fill_mode':e.mode,**e.last_fill}
        self.assertEqual(e.sell_value(p,row(360),S),9.90025)
        self.assertEqual(p['base_units'],9950000)
    def test_wrong_pool_rejected(self):
        def wrong(*args):q=route(*args);q['routePlan'][0]['swapInfo']['ammKey']='other';return q
        with self.assertRaises(ValueError):self.adapter(wrong).buy(row(360),S)
    def test_bad_reverse_rejected(self):
        def wrong(a,b,n):q=route(a,b,n);q['otherAmountThreshold']='1000000' if b==swaps.USDC else q['otherAmountThreshold'];return q
        with self.assertRaises(ValueError):self.adapter(wrong).buy(row(360),S)
    def test_mismatched_quote_rejected(self):
        def wrong(*args):q=route(*args);q['inAmount']='1';return q
        with self.assertRaises(ValueError):self.adapter(wrong).buy(row(360),S)
    def test_quote_cache_expires(self):
        now=[0];calls=[]
        def fetch(*args):calls.append(args);return route(*args)
        e=QuoteExecution([],quote=fetch,rpc=mint,clock=lambda:now[0]);e.route(swaps.USDC,TOKEN,10000000);now[0]=10;e.route(swaps.USDC,TOKEN,10000000);self.assertEqual(len(calls),1);now[0]=16;e.route(swaps.USDC,TOKEN,10000000);self.assertEqual(len(calls),2)
    def test_no_route_no_snapshot_fallback(self):
        def fail(*args):raise ValueError('offline')
        state=initial();state['strategy']['pending']=[{'token':TOKEN,'due':360}];state['token_risk']={TOKEN:{'allowed':True,'expires':450}};state['watch']=[TOKEN]
        events=process_tick(state,[row(360)],360,execution=self.adapter(fail),settings=replace(S,operating_cost_step=0,network_cost=0))
        self.assertEqual(state['strategy']['cash'],100);self.assertFalse(state['strategy']['positions']);self.assertTrue(any(e.get('reason')=='fresh_quote_or_roundtrip_unavailable' for e in events))
    def test_failed_exit_retained_and_marked_zero(self):
        def fail(*args):raise ValueError('offline')
        state=initial();state['strategy']['cash']=90;state['strategy']['positions']={TOKEN:{'units':10,'base_units':10000000,'entry_price':1,'opened':0,'cost':10,'exit_due':360,'fill_mode':QuoteExecution.mode}}
        events=process_tick(state,[row(360)],360,execution=self.adapter(fail),settings=replace(S,operating_cost_step=0,network_cost=0))
        self.assertIn(TOKEN,state['strategy']['positions']);self.assertEqual(state['strategy']['equity'],90);self.assertTrue(state['strategy']['halted']);self.assertFalse(any(e['kind']=='paper_sell' for e in events))
    def test_no_observation_fee_preserves_legacy_cost(self):
        state=initial();state['strategy']['cash']=99;state['strategy']['cost']=1
        process_tick(state,[],360,execution=self.adapter(),settings=replace(S,operating_cost_step=0,network_cost=0))
        self.assertEqual(state['strategy']['cash'],99);self.assertEqual(state['strategy']['cost'],1)
    def test_usage_pricing_includes_cached_tokens(self):
        u={'input_tokens':1000,'output_tokens':200,'input_tokens_details':{'cached_tokens':400}}
        self.assertAlmostEqual(usage_cost(u,{'input':2,'cached':.5,'output':10}),.0034)
    def test_missing_usage_or_prices_unresolved(self):
        self.assertIsNone(usage_cost({},{}));self.assertIsNone(usage_cost({'input_tokens':100,'output_tokens':10},{}));self.assertIsNone(usage_cost({'input_tokens':1,'output_tokens':2,'input_tokens_details':{'cached_tokens':3}},{'input':1,'cached':0,'output':1}))
    def test_expiring_snapshot_prevents_fill(self):
        e=self.adapter();e.clock=lambda:460
        state=initial();state['strategy']['pending']=[{'token':TOKEN,'due':360}];state['token_risk']={TOKEN:{'allowed':True,'expires':500}};state['watch']=[TOKEN]
        events=process_tick(state,[row(360)],360,execution=e,settings=replace(S,operating_cost_step=0,network_cost=0))
        self.assertFalse(state['strategy']['positions']);self.assertTrue(any(v.get('reason')=='evidence_expired_during_quote' for v in events))
class BillingTests(unittest.TestCase):
    def run_decision(self,reported):
        now=time.time();state=initial();state['accounting_version']=2;state['cost_accounting']={};state['config'].update(provider='openai',model='test-fixture',cost_per_call=.01,token_rates={'input':2,'cached':.5,'output':10})
        class Client:
            last_usage={}
            def call(self,*args):
                self.last_usage=reported
                return {'summary':'test fixture','approve':[TOKEN],'exit':[],'concerns':[]}
        with tempfile.TemporaryDirectory() as d:
            trial=LiveTrial(Path(d)/'lab.sqlite',None)
            with patch('live_trial.ModelClient',return_value=Client()),patch('live_trial.scan_risk',return_value={'allowed':True,'expires':now+600,'status':'pass','reasons':[]}),patch('live_trial.swaps.credential',return_value='fixture'):
                approval,_=trial.decide([TOKEN],{TOKEN:row(now)},state,[])
            store=TrialStore(trial.path);saved=store.load();store.db.close()
        return state,saved,approval
    def test_reported_usage_settles_reserve_durably(self):
        state,saved,approval=self.run_decision({'input_tokens':1000,'output_tokens':200,'input_tokens_details':{'cached_tokens':400}})
        self.assertAlmostEqual(state['strategy']['cash'],100-5*.0034);self.assertAlmostEqual(saved['strategy']['cost'],5*.0034);self.assertEqual(approval,[TOKEN]);self.assertNotIn('pending_call',saved['cost_accounting'])
    def test_unknown_usage_retains_reserve_and_abstains(self):
        state,saved,approval=self.run_decision({})
        self.assertEqual(state['calls_today'],1);self.assertAlmostEqual(saved['strategy']['cash'],99.99);self.assertEqual(saved['cost_accounting']['unresolved_calls'],1);self.assertFalse(approval)
    def test_interrupted_call_blocks_new_decision(self):
        state=initial();state['cost_accounting']={'pending_call':{'reserve':.01}}
        trial=LiveTrial('unused',None)
        with patch('live_trial.scan_risk') as scan:self.assertEqual(trial.decide([TOKEN],{TOKEN:row(time.time())},state,[]),([],[]));scan.assert_not_called()

if __name__=='__main__':unittest.main()
