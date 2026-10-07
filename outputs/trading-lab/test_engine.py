import unittest, tempfile
from dataclasses import replace
from engine import *

class Tests(unittest.TestCase):
    def test_deterministic_and_partitions(self):
        s=Settings();a=run_demo(s,'development');self.assertEqual(a,run_demo(s,'development'))
        self.assertNotEqual(a['strategy']['curve'],run_demo(s,'evaluation')['strategy']['curve'])
    def test_no_lookahead(self):
        frames=Scanner.synthetic('development');r=ReviewAgent()
        full=r.run(frames,Settings());prefix=r.run(frames[:40],Settings())
        self.assertEqual(full['events'][:len(prefix['events'])],prefix['events'])
        self.assertEqual(full['curve'][:40],prefix['curve'])
    def test_risk_cannot_override(self):
        risk=RiskController(Settings());self.assertEqual(risk.check(899,0,0,1000),'loss_shutdown')
        self.assertEqual(risk.check(2000,0,0,2000),'loss_shutdown')
        self.assertEqual(RiskController(Settings()).check(1000,300,2,700),'exposure_limit')
    def test_caps_and_delayed_fills(self):
        r=run_demo(Settings(),'development')['strategy']
        self.assertTrue(all(c['exposure']<=300 for c in r['curve']))
        self.assertGreaterEqual(r['cash'],0)
        signals={}
        for e in r['events']:
            if e['action']=='signal':signals[e['token']]=e['step']
            if e['action']=='buy':self.assertGreater(e['step'],signals[e['token']])
    def test_stale_entry_and_failed_exit(self):
        s=replace(Settings(),momentum=.001)
        frames=Scanner.synthetic('development')
        r=ReviewAgent().run(frames,s,True)
        self.assertTrue(any(e['action']=='failed_exit' for e in r['events']))
        self.assertFalse(any(e['action']=='buy' and e['token']=='SYNTH-1' and 45<=e['step']<=49 for e in r['events']))
    def test_costs_reduce_equity(self):
        s=Settings();r=run_demo(s,'development')['strategy']
        cheaper=run_demo(replace(s,fee_bps=.001,slippage_bps=.001,network_cost=.001,operating_cost_step=.001),'development')['strategy']
        self.assertGreater(cheaper['equity'],r['equity'])
    def test_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'test.sqlite');store.save('development',Settings(),{'test':True});store.db.close()
            store=Store(Path(d)/'test.sqlite');self.assertEqual(len(store.history()),1);store.db.close()
    def test_operating_cost_never_borrows(self):
        r=run_demo(replace(Settings(),operating_cost_step=2000),'development')['strategy']
        self.assertEqual(r['cash'],0);self.assertTrue(r['halted'])
        self.assertTrue(all(c['equity']>=0 for c in r['curve']))
    def test_exit_delay(self):
        r=run_demo(Settings(),'development')['strategy'];signals={}
        for e in r['events']:
            if e['action']=='exit_signal':signals[e['token']]=e['step']
            if e['action']=='sell':self.assertGreater(e['step'],signals[e['token']])
    def test_invalid(self):
        for change in ({'capital':float('nan')},{'max_exposure':2},{'max_positions':1.5},{'ticket':10000}):
            with self.assertRaises(ValueError):replace(Settings(),**change).validate()

if __name__=='__main__':unittest.main()
