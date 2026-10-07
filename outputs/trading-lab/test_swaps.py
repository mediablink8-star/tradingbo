import base64,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import swaps
W=swaps.SOL;M=swaps.USDC
def decode58(text):
    n=0
    for c in text:n=n*58+swaps._ALPHABET.index(c)
    return b'\0'*(len(text)-len(text.lstrip('1')))+(n.to_bytes((n.bit_length()+7)//8,'big') if n else b'')
def tx(program=swaps.JUP):
    message=bytes([1,0,1,2])+decode58(W)+decode58(program)+b'\0'*32+bytes([1,1,1,0,1,0])
    return base64.b64encode(b'\1'+b'\0'*64+message).decode()
def routed(a,b,n):
    out=200_000_000 if a==W and b==M and n==1_000_000_000 else (49_800_000 if a==M else 1_000_000)
    return dict(inputMint=a,outputMint=b,inAmount=str(n),outAmount=str(out),otherAmountThreshold=str(max(1,int(out*.995))),swapMode='ExactIn',slippageBps=50,routePlan=[dict(swapInfo=dict(ammKey=M))],priceImpactPct='0.001')
class SwapTests(unittest.TestCase):
    def setUp(self):
        self.keypatch=patch('swaps.credential',return_value='test-key');self.keypatch.start()
        self.tmp=tempfile.TemporaryDirectory();self.service=swaps.Swaps(Path(self.tmp.name)/'db.sqlite')
        self.mint=dict(owner=swaps.TOKEN,data=dict(parsed=dict(type='mint',info=dict(isInitialized=True,decimals=6,mintAuthority=None,freezeAuthority=None))))
        self.riskpatch=patch('swaps.scan_risk',return_value=dict(allowed=True,reasons=[],market=dict(pair=M),expires=time.time()+90));self.riskpatch.start()
        self.encoded=tx()
        self.rpcpatch=patch('swaps.rpc',side_effect=self.rpc);self.rpcpatch.start()
        self.qpatch=patch('swaps.quote',side_effect=routed);self.qpatch.start()
        self.reqpatch=patch('swaps.request',return_value=dict(swapTransaction=self.encoded,lastValidBlockHeight=1000));self.reqpatch.start()
    def tearDown(self):
        self.riskpatch.stop();self.keypatch.stop();self.reqpatch.stop();self.qpatch.stop();self.rpcpatch.stop();self.tmp.cleanup()
    def rpc(self,method,args):
        if method=='getAccountInfo':return dict(value=self.mint)
        if method=='getBalance':return dict(value=1_000_000_000)
        if method=='simulateTransaction':return {'value':{'err':None,'accounts':[{'lamports':949900000}],'preTokenBalances':[],'postTokenBalances':[{'owner':W,'mint':M,'uiTokenAmount':{'amount':'1000000'}}]}}
        if method=='getFeeForMessage':return dict(value=105000)
        if method=='getBlockHeight':return 500
        if method=='getTokenAccountsByOwner':return {'value':[{'account':{'data':{'parsed':{'info':{'tokenAmount':{'amount':'2000000'}}}}}}]}
        if method=='getTransaction':return dict(transaction=[self.encoded,'base64'],meta=dict(err=None,fee=105000),slot=500)
        self.fail(method)
    def prepare(self):return self.service.prepare(dict(wallet=W,mint=M,side='buy',usd=10))
    def test_prepare_wallet_only_and_secrets_not_in_history(self):
        result=self.prepare();self.assertEqual(result['state'],'prepared');self.assertEqual(result['input_base_units'],'50000000')
        self.assertFalse(self.service.state()['autonomous']);self.assertNotIn('message',self.service.state()['records'][0]);self.assertNotIn('transaction',self.service.state()['records'][0])
    def test_untrusted_authorities_and_unknown_fields_rejected(self):
        self.mint['data']['parsed']['info']['mintAuthority']=W
        with self.assertRaises(ValueError):self.prepare()
        del self.mint['data']['parsed']['info']['mintAuthority']
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.service.state()['records'])
    def test_bad_envelope_and_wrong_wallet_rejected(self):
        with self.assertRaises(ValueError):swaps.message(tx(program=W),W)
        with self.assertRaises(ValueError):swaps.message(self.encoded,M)
        raw=bytearray(base64.b64decode(self.encoded));raw[1]=1
        with self.assertRaises(ValueError):swaps.message(base64.b64encode(raw).decode(),W)
        with self.assertRaises(ValueError):swaps.message('not base64',W)
    def test_buy_stop_does_not_disable_sell(self):
        self.service.halt()
        with self.assertRaises(ValueError):self.prepare()
        with patch('swaps.rpc',side_effect=lambda method,args:dict(value=dict(err=None,accounts=[dict(lamports=1_047_000_000)])) if method=='simulateTransaction' else self.rpc(method,args)):
            result=self.service.prepare(dict(wallet=W,mint=M,side='sell',amount='1000000'))
        self.assertEqual(result['side'],'sell')
    def test_once_only_handoff_and_chain_confirmation(self):
        result=self.prepare();ready=self.service.ready(result['id'],W);self.assertEqual(ready['message'],result['message'])
        with self.assertRaises(ValueError):self.service.ready(result['id'],W)
        confirmed=self.service.confirm(result['id'],'1'*64);self.assertEqual(confirmed['state'],'confirmed')
    def test_expired_and_changed_wallet_handoffs_rejected(self):
        result=self.prepare()
        with self.assertRaises(ValueError):self.service.ready(result['id'],M)
        with patch('swaps.time.time',return_value=result['expires']+1):
            with self.assertRaises(ValueError):self.service.ready(result['id'],W)
    def test_restart_budget_not_reset(self):
        for i in range(9):
            intent=self.prepare();self.service.ready(intent['id'],W);self.service.confirm(intent['id'],'1'*63+str(i+1))
        reloaded=swaps.Swaps(self.service.path)
        with self.assertRaises(ValueError):reloaded.prepare(dict(wallet=W,mint=M,side='buy',usd=10))
    def test_simulation_and_fee_fail_closed(self):
        with patch('swaps.rpc',side_effect=lambda method,args:dict(value=dict(err='failed')) if method=='simulateTransaction' else self.rpc(method,args)):
            with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.service.state()['records'])
        with patch('swaps.rpc',side_effect=lambda method,args:dict(value=None) if method=='getFeeForMessage' else self.rpc(method,args)):
            with self.assertRaises(ValueError):self.prepare()
    def test_risk_rejection_blocks_buy_before_quote(self):
        with patch('swaps.scan_risk',return_value=dict(allowed=False,reasons=['concentrated_single_owner'])):
            with self.assertRaisesRegex(ValueError,'concentrated_single_owner'):self.prepare()
        self.assertFalse(self.service.state()['records'])
    def test_route_must_match_screened_pool(self):
        def bad(a,b,n):
            value=routed(a,b,n);value['routePlan'][0]['swapInfo']['ammKey']=W;return value
        with patch('swaps.quote',side_effect=bad):
            with self.assertRaisesRegex(ValueError,'screened pool'):self.prepare()
    def test_simulated_wrong_token_or_recipient_rejected(self):
        for tokens in ([],[dict(owner=M,mint=M,uiTokenAmount=dict(amount='1000000'))]):
            with patch('swaps.rpc',side_effect=lambda method,args:dict(value=dict(err=None,accounts=[dict(lamports=949900000)],preTokenBalances=[],postTokenBalances=tokens)) if method=='simulateTransaction' else self.rpc(method,args)):
                with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.service.state()['records'])
    def test_signature_must_match_prepared_message(self):
        result=self.prepare();self.service.ready(result['id'],W)
        wrong=base64.b64decode(self.encoded);wrong=wrong[:-1]+b'\1'
        with patch('swaps.rpc',return_value=dict(transaction=[base64.b64encode(wrong).decode(),'base64'],meta=dict(err=None,fee=1),slot=1)):
            with self.assertRaises(ValueError):self.service.confirm(result['id'],'1'*64)
    def test_unconfirmed_never_claims_success(self):
        result=self.prepare();self.service.ready(result['id'],W)
        with patch('swaps.rpc',return_value=None):
            response=self.service.confirm(result['id'],'1'*64)
        self.assertEqual(response['state'],'pending')

class RouteTests(unittest.TestCase):
    def test_quote_mismatch_impact_and_missing_key(self):
        with patch('swaps.credential',return_value='key'):
            valid=routed(W,M,100)
            with patch('swaps.request',return_value=valid):self.assertEqual(swaps.quote(W,M,100),valid)
            for field,value in [('inAmount','101'),('slippageBps',100),('priceImpactPct','NaN'),('routePlan',[])]:
                bad={**valid,field:value}
                with patch('swaps.request',return_value=bad):
                    with self.assertRaises(ValueError):swaps.quote(W,M,100)
        with patch('swaps.credential',return_value=''):
            with self.assertRaises(ValueError):swaps.quote(W,M,100)

if __name__=='__main__':unittest.main()

