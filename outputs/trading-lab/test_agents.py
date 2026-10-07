import unittest, tempfile, os, json
from unittest.mock import patch
from agents import AgentTeam, ModelClient, run_team, validate_output, ROLES
from engine import Settings, Scanner, ReviewAgent

class AgentTests(unittest.TestCase):
    def test_handoffs_and_bounded_rounds(self):
        team=AgentTeam(max_rounds=2,cost_per_call=0);seen=[]
        def model(role,instructions,context,reports):
            seen.append((role,len(reports),context['step']))
            return dict(summary='Mock response',approve=context['eligible'],exit=[],concerns=[])
        team.client.call=model;result=run_team(Settings(),'development',team)
        self.assertEqual(team.calls,10);self.assertEqual([x[1] for x in seen[:5]],[0,1,2,3,4])
        self.assertTrue(any(e['action']=='buy' for e in result['strategy']['events']))
        self.assertTrue(all(e['step']<30 for e in result['strategy']['events'] if e['action']=='buy'))
    def test_veto_cannot_be_overridden(self):
        team=AgentTeam(max_rounds=1,cost_per_call=0)
        def model(role,instructions,context,reports):
            return dict(summary='Mock',approve=[] if role=='Risk critic' else context['eligible'],exit=[],concerns=[])
        team.client.call=model;result=run_team(Settings(),'development',team)
        self.assertFalse(any(e['action']=='buy' for e in result['strategy']['events']))
    def test_invalid_model_fail_closed(self):
        team=AgentTeam(cost_per_call=0);team.client.call=lambda *a:{'approve':['EVIL']}
        result=run_team(Settings(),'development',team)
        self.assertEqual(team.calls,1);self.assertIsNotNone(team.error)
        self.assertFalse(any(e['action']=='buy' for e in result['strategy']['events']))
    def test_budget_and_cost_accounting(self):
        team=AgentTeam(max_rounds=1,cost_per_call=1);r=run_team(Settings(),'development',team)
        self.assertEqual(r['strategy']['ai_cost_estimate'],5)
        team=AgentTeam(cost_per_call=100);r=run_team(Settings(capital=100,ticket=10),'development',team)
        self.assertEqual(team.calls,0);self.assertIsNotNone(team.error)
    def test_cancel_does_not_start_calls(self):
        team=AgentTeam(cost_per_call=0);team.cancelled=True;r=run_team(Settings(),'development',team)
        self.assertEqual(team.calls,0);self.assertTrue(r['strategy']['halted'])
    def test_no_future_evidence(self):
        frames=Scanner.synthetic('development');team=AgentTeam(cost_per_call=0)
        def model(role,instructions,context,reports):
            step=context['step'];self.assertTrue(all(row['observed']<=step*60 for row in context['rows']))
            self.assertEqual(context['past_prices']['SYNTH-0'][-1],frames[step-1]['rows'][0]['price'])
            return dict(summary='Mock',approve=context['eligible'],exit=[],concerns=[])
        team.client.call=model;run_team(Settings(),'development',team)
    def test_input_validation(self):
        with self.assertRaises(ValueError):validate_output(dict(summary='x',approve=['unknown'],exit=[],concerns=[]),[],[])
        with self.assertRaises(ValueError):AgentTeam(max_rounds=100)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):ModelClient('openai','some-model')
    def test_ai_cannot_override_loss_shutdown(self):
        team=AgentTeam(max_rounds=12,cost_per_call=0)
        r=run_team(Settings(max_loss=.001,fee_bps=1000),'development',team)['strategy']
        self.assertTrue(r['halted'])
        self.assertTrue(all(c['exposure']<=300 for c in r['curve']))
        buys=[e['step'] for e in r['events'] if e['action']=='buy']
        shutdown=min(e['step'] for e in r['events'] if e['reason']=='shutdown')
        self.assertTrue(all(step<shutdown for step in buys))
    def test_cancel_during_call(self):
        team=AgentTeam(cost_per_call=0)
        def model(role,instructions,context,reports):
            team.cancelled=True
            return dict(summary='Mock',approve=context['eligible'],exit=[],concerns=[])
        team.client.call=model;r=run_team(Settings(),'development',team)['strategy']
        self.assertEqual(team.calls,1);self.assertTrue(r['halted'])
        self.assertFalse(any(e['action']=='buy' for e in r['events']))
    def test_openai_request_and_usage(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return json.dumps({'usage':{'input_tokens':3},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(dict(summary='mock',approve=[],exit=[],concerns=[]))}]}]}).encode()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-not-a-real-key'}):
            client=ModelClient('openai','test-model')
            with patch('urllib.request.urlopen',return_value=Response()) as transport:
                self.assertEqual(client.call('role','instruction',{},[])['summary'],'mock')
                payload=json.loads(transport.call_args[0][0].data)
                self.assertFalse(payload['store']);self.assertEqual(payload['text']['format']['type'],'json_schema')
                self.assertEqual(client.last_usage['input_tokens'],3)

if __name__=='__main__':unittest.main()
