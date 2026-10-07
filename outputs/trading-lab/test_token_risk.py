import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from token_risk import evaluate,scan
from swaps import TOKEN,USDC,encode58
M=USDC;NOW=1000000
def address(n):return encode58(n.to_bytes(32,'big'))
def fixture():
    mint=dict(owner=TOKEN,data=dict(parsed=dict(type='mint',info=dict(isInitialized=True,decimals=6,mintAuthority=None,freezeAuthority=None))))
    supply=dict(amount='100000',decimals=6)
    largest=[dict(address=address(i+1),amount='1000',decimals=6) for i in range(20)]
    accounts=[{'owner':TOKEN,'data':{'parsed':{'type':'account','info':{'mint':M,'state':'initialized','owner':address(i+100),'tokenAmount':{'amount':'1000'}}}}} for i in range(20)]
    pairs=[dict(chainId='solana',baseToken=dict(address=M),liquidity=dict(usd=200000),priceUsd='1',pairCreatedAt=(NOW-90000)*1000,pairAddress=address(500))]
    return mint,supply,largest,accounts,pairs
class RiskTests(unittest.TestCase):
    def evaluate(self,values,previous=None):return evaluate(M,*values,NOW,previous)
    def test_basics_pass_but_never_certifies_safety(self):
        report=self.evaluate(fixture());self.assertTrue(report['allowed']);self.assertFalse(report['certified_safe'])
        self.assertEqual(report['metrics']['sampled_accounts'],20);self.assertTrue(any('LP lock' in x for x in report['warnings']))
    def test_authorities_and_unknown_freeze_reject(self):
        values=fixture();info=values[0]['data']['parsed']['info'];info['mintAuthority']=address(5)
        self.assertIn('mint_authority_active_or_unknown',self.evaluate(values)['reasons'])
        info['mintAuthority']=None;del info['freezeAuthority']
        self.assertIn('freeze_authority_active_or_unknown',self.evaluate(values)['reasons'])
    def test_same_owner_split_accounts_is_aggregated(self):
        values=fixture()
        for i in (0,1):
            values[2][i]['amount']='15000';values[3][i]['data']['parsed']['info']['owner']=address(900);values[3][i]['data']['parsed']['info']['tokenAmount']['amount']='15000'
        result=self.evaluate(values);self.assertIn('concentrated_single_owner',result['reasons']);self.assertEqual(result['metrics']['largest_sampled_owner_pct'],30)
    def test_top10_concentration_rejects(self):
        values=fixture()
        for i in range(10):values[2][i]['amount']='6000';values[3][i]['data']['parsed']['info']['tokenAmount']['amount']='6000'
        self.assertIn('concentrated_top10_owners',self.evaluate(values)['reasons'])
    def test_pool_thresholds_and_liquidity_drop(self):
        values=fixture();values[4][0]['liquidity']['usd']=99999
        self.assertIn('thin_liquidity',self.evaluate(values)['reasons'])
        values[4][0]['liquidity']['usd']=200000;values[4][0]['pairCreatedAt']=(NOW-3600)*1000
        self.assertIn('young_pool',self.evaluate(values)['reasons'])
        values=fixture();previous=self.evaluate(values);previous['observed']=NOW-60;values[4][0]['liquidity']['usd']=140000
        self.assertIn('liquidity_dropped_30_percent',self.evaluate(values,previous)['reasons'])
    def test_missing_wrong_mint_duplicate_and_nan_fail_closed(self):
        for mutate in [
            lambda v:v[3].__setitem__(0,None),
            lambda v:v[3][0]['data']['parsed']['info'].__setitem__('mint',address(800)),
            lambda v:v[2][1].__setitem__('address',v[2][0]['address']),
            lambda v:v[4][0]['liquidity'].__setitem__('usd',float('nan')),
        ]:
            values=fixture();mutate(values);self.assertFalse(self.evaluate(values)['allowed'])
    def test_pool_switch_does_not_compare_unrelated_liquidity(self):
        previous=self.evaluate(fixture());previous['observed']=NOW-60
        values=fixture();values[4][0]['pairAddress']=address(600);values[4][0]['liquidity']['usd']=110000
        report=self.evaluate(values,previous);self.assertTrue(report['allowed']);self.assertTrue(any('pool changed' in x for x in report['warnings']))
    def test_scanner_provider_failure_is_saved_as_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            report=scan(M,Path(folder)/'risk.sqlite',rpc_client=lambda *args:(_ for _ in ()).throw(ValueError()),fetch=lambda *args:[])
            self.assertFalse(report['allowed']);self.assertEqual(report['status'],'unknown');self.assertTrue((Path(folder)/'risk.sqlite').exists())
    def test_liquidity_history_survives_unknown_scan(self):
        values=fixture()
        def rpc(method,args):
            return {'getAccountInfo':dict(value=values[0]),'getTokenSupply':dict(value=values[1]),'getTokenLargestAccounts':dict(value=values[2]),'getMultipleAccounts':dict(value=values[3])}[method]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'risk.sqlite'
            with patch('token_risk.time.time',return_value=NOW):scan(M,path,rpc_client=rpc,fetch=lambda *a:values[4])
            with patch('token_risk.time.time',return_value=NOW+30):scan(M,path,rpc_client=lambda *a:(_ for _ in ()).throw(ValueError()))
            values[4][0]['liquidity']['usd']=140000
            with patch('token_risk.time.time',return_value=NOW+60):report=scan(M,path,rpc_client=rpc,fetch=lambda *a:values[4])
            self.assertIn('liquidity_dropped_30_percent',report['reasons'])
    def test_scanner_success_and_stale_report(self):
        values=fixture()
        def rpc(method,args):
            return {'getAccountInfo':dict(value=values[0]),'getTokenSupply':dict(value=values[1]),'getTokenLargestAccounts':dict(value=values[2]),'getMultipleAccounts':dict(value=values[3])}[method]
        with tempfile.TemporaryDirectory() as folder:
            with patch('token_risk.time.time',return_value=NOW):
                report=scan(M,Path(folder)/'risk.sqlite',rpc_client=rpc,fetch=lambda *args:values[4]);self.assertTrue(report['allowed'])
            with patch('token_risk.time.time',side_effect=[NOW,NOW+100,NOW+100]):
                report=scan(M,Path(folder)/'risk.sqlite',rpc_client=rpc,fetch=lambda *args:values[4]);self.assertFalse(report['allowed']);self.assertIn('evidence_stale',report['reasons'])

if __name__=='__main__':unittest.main()

