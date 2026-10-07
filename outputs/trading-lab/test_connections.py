import json, os, unittest
from unittest.mock import patch, MagicMock
import connections
from agents import ModelClient

ADDRESS='So11111111111111111111111111111111111111112'
KEY='sk-test-session-only-0123456789'
class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{},clear=True);self.env.start();connections.forget()
    def tearDown(self):connections.forget();self.env.stop()
    def response(self,value):
        reply=MagicMock();reply.__enter__.return_value.read.return_value=json.dumps(value).encode();return reply
    def test_session_key_not_in_status_and_forget(self):
        state=connections.configure(dict(key=KEY,model='test-model'))
        self.assertTrue(state['configured']);self.assertNotIn(KEY,json.dumps(state))
        self.assertEqual(connections.api_key(),KEY)
        self.assertFalse(connections.forget()['configured'])
        self.assertEqual(connections.api_key(),'')
    def test_invalid_secrets_and_model_rejected(self):
        for key in ('word '*12,'sk-key\r\nInjected: yes',''):
            with self.assertRaises(ValueError):connections.configure(dict(key=key,model='test-model'))
        with self.assertRaises(ValueError):connections.configure(dict(key=KEY,model='https://attacker.invalid'))
        self.assertFalse(connections.status()['configured'])
    def test_model_adapter_uses_session_key(self):
        connections.configure(dict(key=KEY,model='test-model'));client=ModelClient('openai','test-model')
        result=dict(output=[dict(type='message',content=[dict(type='output_text',text='{}')])])
        with patch('urllib.request.urlopen',return_value=self.response(result)) as request:
            self.assertEqual(client.call('Researcher','Review',{},[]),{})
            self.assertEqual(request.call_args.args[0].get_header('Authorization'),'Bearer '+KEY)
        connections.forget()
        with self.assertRaises(ValueError):client.call('Researcher','Review',{},[])
    def test_verify_only_lists_models_no_inference(self):
        connections.configure(dict(key=KEY,model='test-model'))
        with patch('urllib.request.urlopen',return_value=self.response(dict(data=[dict(id='test-model')])) ) as request:
            value=connections.verify()
            req=request.call_args.args[0]
            self.assertEqual(req.full_url,'https://api.openai.com/v1/models');self.assertEqual(req.get_method(),'GET')
            self.assertTrue(value['verified']);self.assertNotIn(KEY,json.dumps(value))
    def test_balance_converts_lamports_and_only_reads(self):
        with patch('urllib.request.urlopen',return_value=self.response(dict(result=dict(value=1500000000,context=dict(slot=123))))) as request:
            value=connections.wallet_balance(ADDRESS);payload=json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['method'],'getBalance');self.assertEqual(payload['params'][0],ADDRESS)
            self.assertEqual(value['sol'],1.5);self.assertFalse(value['funds_available_for_trading'])
    def test_addresses_and_rpc_failures_never_fake_balance(self):
        for address in ('seed phrase here','1'*33,'0'*44,ADDRESS+'1'):
            with self.assertRaises(ValueError):connections.validate_address(address)
        self.assertEqual(connections.validate_address('1'*32),'1'*32)
        with patch('urllib.request.urlopen',return_value=self.response(dict(error=dict(message=KEY)))):
            with self.assertRaises(ValueError) as error:connections.wallet_balance(ADDRESS)
            self.assertNotIn(KEY,str(error.exception))
    def test_host_and_origin_guards(self):
        from app import Handler
        from io import BytesIO
        handler=Handler.__new__(Handler);handler.headers={'Host':'attacker.invalid'}
        handler.send=MagicMock();handler.do_GET()
        self.assertEqual(handler.send.call_args.args[1],403)
        handler.headers={'Host':'127.0.0.1:8765','Content-Type':'application/json'}
        handler.path='/api/connections/model';handler.rfile=BytesIO(b'{}');handler.do_POST()
        self.assertEqual(handler.send.call_args.args[1],403)
        handler.headers={'Host':'127.0.0.1:8765','Origin':'https://attacker.invalid','Content-Type':'application/json'}
        handler.do_POST();self.assertEqual(handler.send.call_args.args[1],403)

if __name__=='__main__':unittest.main()

