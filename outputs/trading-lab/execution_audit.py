"""Read-only transaction recovery and balance reconciliation."""
import math,time
from swaps import SOL

def reconcile(record,result):
    meta=result.get('meta') or {};report={'observed_at':time.time(),'status':'unknown','commitment':'confirmed','basis':'Transaction wallet balance deltas; SOL amounts may include account rent. No total wallet P&L is inferred.','transaction_failed':meta.get('err') is not None,'quoted_output':record['expected_output_base_units'],'minimum_output':record['minimum_output_base_units'],'realized_output':None,'quote_shortfall_bps':None,'network_fee_lamports':meta.get('fee'),'wallet_sol_change_lamports':None}
    try:
        pre=meta['preBalances'];post=meta['postBalances']
        if not isinstance(pre,list) or not isinstance(post,list) or not pre or len(pre)!=len(post) or type(pre[0])!=int or type(post[0])!=int:raise ValueError()
        report['wallet_sol_change_lamports']=post[0]-pre[0]
        if report['transaction_failed']:report['status']='failed';return report
        if record['side']=='buy':
            before=meta['preTokenBalances'];after=meta['postTokenBalances']
            if not isinstance(before,list) or not isinstance(after,list):raise ValueError()
            def owned(values):return sum(int(x['uiTokenAmount']['amount']) for x in values if x.get('owner')==record['wallet'] and x.get('mint')==record['mint'])
            amount=owned(after)-owned(before)
        else:amount=post[0]-pre[0]+int(meta['fee'])
        expected=int(record['expected_output_base_units']);minimum=int(record['minimum_output_base_units'])
        report['realized_output']=str(amount);report['quote_shortfall_bps']=(expected-amount)/expected*10000 if expected else None;report['status']='verified' if amount>=minimum else 'minimum_output_breach'
    except (KeyError,TypeError,ValueError,IndexError):report['reason']='Required transaction balance deltas unavailable or invalid; do not infer realized output.'
    return report
