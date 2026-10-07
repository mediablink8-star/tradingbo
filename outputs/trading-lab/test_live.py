import tempfile, unittest
from pathlib import Path
from live_trial import initial, process_tick, normalize_pairs, TrialStore, readiness

TOKEN='So11111111111111111111111111111111111111112'
def row(now,price=1):
    return dict(token=TOKEN,price=price,liquidity=200000,age_hours=30,observed=now,available=True,exit_ok=True,pair='pool',source='test fixture',synthetic=False)
class LiveTests(unittest.TestCase):
    def test_capital_history_persists_only_valid_valuations(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.sqlite'
            store=TrialStore(path)
            self.assertEqual(store.capital_history(),[])
            store.save(initial(),[{'kind':'valuation','timestamp':60,'strategy':99.5,'baseline':99.4},{'kind':'other','timestamp':90},{'kind':'valuation','timestamp':120,'strategy':99.2,'baseline':99.1},{'kind':'valuation','timestamp':180,'strategy':'invalid','baseline':98}])
            store.db.close()
            reopened=TrialStore(path)
            self.assertEqual(reopened.capital_history(),[{'timestamp':60,'strategy':99.5,'baseline':99.4},{'timestamp':120,'strategy':99.2,'baseline':99.1}])
            reopened.db.close()
    def ready(self):
        state=initial();state['watch']=[TOKEN];state['config']['provider']='ollama';state['token_risk']={TOKEN:dict(allowed=True,expires=390)}
        for step in range(6):process_tick(state,[row(step*60,1+step*.02)],step*60,lambda *args:([TOKEN],[]))
        return state
    def test_readiness_reports_unconfigured_and_costs(self):
        state=initial();state['worker_running']=True
        info=readiness(state,0)
        self.assertTrue(any('provider' in item for item in info['blockers']))
        self.assertEqual(info['modeled_operating_cost_per_day'],7.2)
        self.assertEqual(info['completed_strategy_trades'],0)
    def test_screening_counts_and_no_signal(self):
        state=initial();state['watch']=[TOKEN]
        process_tick(state,[row(100)],100)
        info=readiness(state,100)
        self.assertEqual(info['screening_counts'],{'history_or_momentum':1})
        self.assertEqual(state['eligible_count'],0)
    def test_batch_never_matches_other_token(self):
        pair=dict(chainId='solana',baseToken=dict(address='other'),priceUsd='1',liquidity=dict(usd=200000),pairCreatedAt=1000,pairAddress='pool')
        self.assertIsNone(normalize_pairs(TOKEN,[pair],100000))
    def test_live_delayed_fill(self):
        state=self.ready();self.assertFalse(state['strategy']['positions']);self.assertEqual(len(state['strategy']['pending']),1)
        events=process_tick(state,[row(360,1.13)],360)
        self.assertTrue(state['strategy']['positions']);self.assertTrue(any(e['kind']=='paper_buy' and e['portfolio']=='strategy' for e in events))
        self.assertLessEqual(state['strategy']['exposure'],30);self.assertGreaterEqual(state['strategy']['cash'],0)
    def test_missing_data_latches_shutdown_and_retains_position(self):
        state=self.ready();process_tick(state,[row(360,1.13)],360);process_tick(state,[],420)
        self.assertTrue(state['strategy']['halted']);self.assertTrue(state['strategy']['positions'])
        process_tick(state,[row(480,1.14)],480);process_tick(state,[row(540,1.14)],540)
        self.assertFalse(state['strategy']['positions']);self.assertTrue(state['strategy']['halted'])
    def test_no_provider_no_ai_entries(self):
        state=initial();state['watch']=[TOKEN]
        for step in range(8):process_tick(state,[row(step*60,1+step*.02)],step*60,lambda *args:self.fail('No provider must not call model'))
        self.assertFalse(state['strategy']['positions']);self.assertFalse(state['strategy']['pending'])
    def test_expired_order_and_gap(self):
        state=self.ready();events=process_tick(state,[row(600,2)],600)
        self.assertFalse(state['strategy']['positions']);self.assertTrue(any(e['kind']=='data_gap' for e in events))
    def test_stale_token_risk_blocks_entry_but_not_exit(self):
        state=self.ready();state['token_risk'][TOKEN]['expires']=359
        events=process_tick(state,[row(360,1.13)],360)
        self.assertFalse(state['strategy']['positions'])
        self.assertTrue(any(e.get('reason')=='token_risk_unknown_or_stale' for e in events))
    def test_pause_rejects_pending_fill(self):
        state=self.ready();process_tick(state,[row(360,1.13)],360,stopping=True)
        self.assertFalse(state['strategy']['positions'])
    def test_model_failure_abstains(self):
        state=initial();state['watch']=[TOKEN];state['config']['provider']='ollama'
        def fail(*args):raise ValueError('invalid output')
        for step in range(6):process_tick(state,[row(step*60,1+step*.02)],step*60,fail)
        self.assertEqual(state['status'],'ai_error');self.assertFalse(state['strategy']['pending'])
    def test_restart_preserves_financial_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lab.sqlite';state=self.ready();process_tick(state,[row(360,1.13)],360)
            store=TrialStore(path);store.save(state,[dict(kind='test')]);store.db.close()
            store=TrialStore(path);saved=store.load();self.assertEqual(saved['strategy'],state['strategy']);self.assertEqual(saved['history'],state['history']);store.db.close()
    def test_source_units_and_missing_fields(self):
        self.assertIsNone(normalize_pairs(TOKEN,[dict(priceUsd='1')],100000))
        pair=dict(chainId='solana',baseToken=dict(address=TOKEN),priceUsd='1',liquidity=dict(usd=200000),pairCreatedAt=1000,pairAddress='pool')
        normalized=normalize_pairs(TOKEN,[pair],100000);self.assertFalse(normalized['synthetic']);self.assertIsNone(normalized['source_timestamp'])
        pair['priceUsd']='NaN';self.assertIsNone(normalize_pairs(TOKEN,[pair],100000))

if __name__=='__main__':unittest.main()

