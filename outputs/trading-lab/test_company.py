import unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch
from live_trial import initial,TrialStore,LiveTrial
from virtual_company import Company
from operations import Operations
class CompanyTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'company.sqlite';self.store=TrialStore(self.path);self.company=Company(self.path)
    def tearDown(self):self.store.db.close();self.tmp.cleanup()
    def test_policy_persists_and_rejects_invalid_budget(self):
        self.company.configure({'name':'My company','priority':'preservation','daily_ai_budget':.25});self.assertEqual(Company(self.path).config()['daily_ai_budget'],.25)
        for value in (-1,11,True,float('nan')):
            with self.assertRaises(ValueError):self.company.configure({'daily_ai_budget':value})
    def test_budget_counts_usage_reservations_and_current_pending(self):
        now=time.time();self.store.save(initial(),[{'kind':'ai_usage_cost','timestamp':now,'amount':.1},{'kind':'ai_cost_unresolved','timestamp':now,'reserved':.05},{'kind':'ai_usage_cost','timestamp':now-172800,'amount':100}]);s=initial();s['cost_accounting']={'pending_call':{'reserve':.02}}
        self.assertAlmostEqual(self.company.budget(s,now)['used'],.17)
    def test_company_budget_blocks_review_before_model_or_scan(self):
        self.company.configure({'daily_ai_budget':.01});s=initial();s['config'].update(provider='openai',cost_per_call=.01)
        with patch('live_trial.scan_risk') as scan:self.assertEqual(LiveTrial(self.path,None).decide(['token'],{},s,[]),([],[]));scan.assert_not_called()
        self.assertEqual(s['status'],'company_ai_budget_reached')
    def test_work_orders_deduplicate_and_resolve(self):
        s=initial();s.update(worker_running=True,last_tick=time.time(),valid_price_snapshots=1,eligible_count=1);ops=Operations(self.path)
        with patch('operations.swaps.credential',return_value=''):
            data=ops.update(s,{'running':True});first=self.company.board(s,data);second=self.company.board(s,data)
        self.assertEqual(len(first['tasks']),len(second['tasks']));self.assertEqual(len(first['employees']),10)
        ready={**data,'checklist':[{**c,'ok':True} for c in data['checklist']]};resolved=self.company.board(s,ready);self.assertTrue(any(t['key']=='model' and t['status']=='done' for t in resolved['tasks']))
    def test_mission_and_fixed_authority(self):
        s=initial();data=Operations(self.path).update(s,{'running':False});board=self.company.board(s,data);self.assertEqual(board['capital']['shutdown_equity'],90);self.assertIn('Owner approves',board['authority']);self.assertIn('Abstain',board['mission'])
if __name__=='__main__':unittest.main()
