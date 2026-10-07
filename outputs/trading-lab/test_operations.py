import unittest,tempfile
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from operations import Operations,journal,checks
from live_trial import TrialStore,initial,process_tick,S
TOKEN='So11111111111111111111111111111111111111112'
class OperationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'lab.sqlite';self.store=TrialStore(self.path);self.ops=Operations(self.path)
    def tearDown(self):self.store.db.close();self.folder.cleanup()
    def healthy(self):
        s=initial();s.update(worker_running=True,last_tick=100,valid_price_snapshots=1,eligible_count=1);return s
    def test_incidents_deduplicate_recover_and_reopen(self):
        s=self.healthy();s['worker_running']=False;p={'running':True,'stale':False}
        a=self.ops.update(s,p,100)['alerts'];self.assertEqual(len(a),1);self.ops.update(s,p,101);self.assertEqual(len(self.ops.update(s,p,102)['alerts']),1)
        self.ops.acknowledge(a[0]['id']);s['worker_running']=True;r=self.ops.update(s,p,103)['alerts'][0];self.assertIsNotNone(r['acknowledged']);self.assertEqual(r['resolved'],103)
        s['worker_running']=False;self.assertEqual(len(Operations(self.path).update(s,p,104)['alerts']),2)
    def test_journal_pagination_exact_token_and_no_sql_injection(self):
        events=[{'kind':'order_rejected','timestamp':i,'token':TOKEN,'reason':'fixture'} for i in range(55)];self.store.save(initial(),events)
        page=journal(self.path);self.assertEqual(len(page['items']),50);older=journal(self.path,before=page['next_cursor']);self.assertEqual(len(older['items']),5);self.assertFalse(set(e['id'] for e in page['items'])&set(e['id'] for e in older['items']))
        self.assertEqual(journal(self.path,token="' OR 1=1 --")['items'],[]);self.assertEqual(len(journal(self.path,token=TOKEN)['items']),50)
    def test_report_disagreement_persists(self):
        self.store.save(initial(),[{'kind':'ai_team_decision','timestamp':1,'eligible':[TOKEN],'approve':[],'vetoes':{TOKEN:['Risk critic']}}]);self.assertEqual(journal(self.path,'reports',token=TOKEN)['items'][0]['vetoes'][TOKEN],['Risk critic'])
    def test_scoreboard_does_not_invent_rules_results(self):
        d=self.ops.update(self.healthy(),{'running':True},100);self.assertEqual(d['scoreboard'][1]['status'],'Not started');self.assertNotIn('pnl',d['scoreboard'][1])
    def test_scoreboard_uses_common_comparison_epoch(self):
        s=self.healthy();s['rules']=initial()['strategy'];s['comparison_start']={'timestamp':90,'equity':{'strategy':99,'baseline':98,'rules':100}};d=self.ops.update(s,{'running':True},100);self.assertEqual(d['scoreboard'][0]['pnl'],1);self.assertEqual(d['scoreboard'][2]['pnl'],2)
    def test_missing_credentials_are_checklist_blockers(self):
        with patch('operations.connections.api_key',return_value=''),patch('operations.swaps.credential',return_value=''):
            results={x['key']:x['ok'] for x in checks(self.healthy(),{'running':True},100)};self.assertFalse(results['model']);self.assertFalse(results['quotes'])
    def test_fixed_rules_prospective_entries_without_model_calls(self):
        s=initial();s['rules']=initial()['strategy'];s['watch']=[TOKEN];s['token_risk']={TOKEN:{'allowed':True,'expires':1000}}
        def row(t):return {'token':TOKEN,'price':1+t/6000,'liquidity':200000,'age_hours':30,'observed':t,'available':True,'exit_ok':True,'pair':'pool'}
        for i in range(7):process_tick(s,[row(i*60)],i*60,lambda *a:self.fail('No model configured'),settings=replace(S,operating_cost_step=0))
        self.assertTrue(s['rules']['positions']);self.assertFalse(s['strategy']['positions']);self.assertEqual(s['calls_today'],0)
    def test_acknowledgement_cannot_resolve_incident(self):
        s=self.healthy();s['strategy']['halted']=True;a=self.ops.update(s,{'running':True},100)['alerts'][0];self.ops.acknowledge(a['id']);r=self.ops.update(s,{'running':True},101)['alerts'][0];self.assertIsNone(r['resolved'])
if __name__=='__main__':unittest.main()
