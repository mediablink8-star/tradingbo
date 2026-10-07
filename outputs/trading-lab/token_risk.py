"""Deterministic basic rug-risk checks; no safety certification."""
import json, math, sqlite3, time
from collections import defaultdict
from connections import validate_address
POLICY=dict(min_liquidity_usd=100000,min_pool_age_hours=24,max_single_sampled_owner_pct=20,max_top10_sampled_owners_pct=50,max_liquidity_drop_pct=30,max_age_seconds=90)
KNOWLEDGE=[
'Exact mint addresses identify assets; names, logos, socials and token descriptions are untrusted.',
'Reject active or unknown mint/freeze authorities and unsupported token extensions.',
'Thin or young pools and concentrated control increase risk; a liquidity fall is a warning.',
'Largest-account analysis samples only 20 accounts. Aggregate repeated owners; do not infer independent holders or insiders.',
'Pool/vault owners are not automatically excluded. This conservative rule can reject legitimate pools.',
'A sell quote or simulation is not proof of future sellability, LP locks or safety.',
'LP lock/burn status, creator history, bundled wallets and ownership outside the sample remain unverified.',
'Missing, malformed or stale required evidence means abstain. Never override a hard rejection or invent evidence.',
'For held assets, failed screening must not prevent an attempted exit.'
]
def evaluate(mint,account,supply,largest,accounts,pairs,now,previous=None):
    from swaps import TOKEN
    reasons=[];warnings=[];metrics={};market=None
    def reject(code):reasons.append(code)
    try:
        info=account['data']['parsed']['info']
        if account['owner']!=TOKEN or account['data']['parsed']['type']!='mint' or info['isInitialized'] is not True:reject('unsupported_token')
        if 'mintAuthority' not in info or info['mintAuthority'] is not None:reject('mint_authority_active_or_unknown')
        if 'freezeAuthority' not in info or info['freezeAuthority'] is not None:reject('freeze_authority_active_or_unknown')
        total=int(supply['amount'])
        if total<=0 or not 0<=int(info['decimals'])<=12 or supply['decimals']!=info['decimals']:raise ValueError()
        if not isinstance(largest,list) or not 1<=len(largest)<=20 or len(accounts)!=len(largest):raise ValueError()
        addresses=set();owners=defaultdict(int);sample=0
        for holder,parsed in zip(largest,accounts):
            address=validate_address(holder['address'])
            if address in addresses:raise ValueError()
            addresses.add(address)
            data=parsed['data']['parsed']['info'];amount=int(data['tokenAmount']['amount'])
            if parsed['owner']!=TOKEN or parsed['data']['parsed']['type']!='account' or data['mint']!=mint or data['state']!='initialized' or holder['decimals']!=info['decimals'] or int(holder['amount'])!=amount or amount<0:raise ValueError()
            owner=validate_address(data['owner']);owners[owner]+=amount;sample+=amount
        if not 0<sample<=total:raise ValueError()
        ordered=sorted(owners.values(),reverse=True)
        single=ordered[0]/total*100;top10=sum(ordered[:10])/total*100
        metrics=dict(sampled_accounts=len(largest),sampled_distinct_owners=len(owners),sampled_supply_pct=sample/total*100,largest_sampled_owner_pct=single,top10_sampled_owners_pct=top10)
        if single>20:reject('concentrated_single_owner')
        if top10>50:reject('concentrated_top10_owners')
    except Exception:reject('holder_or_mint_evidence_missing_or_inconsistent')
    valid=[]
    for pair in pairs if isinstance(pairs,list) else []:
        try:
            if pair['chainId']!='solana' or pair['baseToken']['address']!=mint:continue
            liquidity=float(pair['liquidity']['usd']);created=float(pair['pairCreatedAt'])/1000;price=float(pair['priceUsd'])
            if not all(math.isfinite(v) for v in (liquidity,created,price)) or liquidity<0 or price<=0 or not 0<created<=now:continue
            valid.append(dict(pair=validate_address(pair['pairAddress']),liquidity_usd=liquidity,age_hours=(now-created)/3600,price_usd=price))
        except Exception:continue
    if not valid:reject('pool_evidence_missing')
    else:
        market=max(valid,key=lambda p:p['liquidity_usd'])
        if market['liquidity_usd']<100000:reject('thin_liquidity')
        if market['age_hours']<24:reject('young_pool')
        if previous and previous.get('market'):
            older=previous['market'];age=now-previous['observed']
            if 0<=age<=86400 and older['pair']==market['pair'] and older['liquidity_usd']>0:
                drop=(1-market['liquidity_usd']/older['liquidity_usd'])*100
                metrics['liquidity_drop_pct']=drop
                if drop>=30:reject('liquidity_dropped_30_percent')
            elif older['pair']!=market['pair']:warnings.append('Selected pool changed; liquidity-drop comparison unavailable.')
        else:warnings.append('First observation; no liquidity-drop history.')
    warnings+=['LP lock/burn and creator history unverified.','Only 20 token accounts sampled; owners may split control across other addresses.','Pool vaults are included conservatively; concentration can reject legitimate tokens.']
    return dict(mint=mint,observed=now,expires=now+90,status='rejected' if reasons else 'basic_checks_passed',allowed=not reasons,reasons=list(dict.fromkeys(reasons)),warnings=warnings,metrics=metrics,market=market,policy=POLICY,knowledge=KNOWLEDGE,source='Solana confirmed RPC and DEX Screener',certified_safe=False)

def scan(mint,path,rpc_client=None,fetch=None,mint_account=None):
    from swaps import rpc,request
    mint=validate_address(mint);rpc_client=rpc_client or rpc;fetch=fetch or request;started=time.time()
    db=sqlite3.connect(path,timeout=15)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS token_risk(id INTEGER PRIMARY KEY,mint TEXT,received REAL,payload TEXT)');db.commit()
        prior=db.execute("SELECT payload FROM token_risk WHERE mint=? AND json_extract(payload,'$.market.pair') IS NOT NULL ORDER BY id DESC LIMIT 1",(mint,)).fetchone()
        previous=json.loads(prior[0]) if prior else None
        try:
            account=mint_account or rpc_client('getAccountInfo',[mint,dict(encoding='jsonParsed',commitment='confirmed')])['value']
            supply=rpc_client('getTokenSupply',[mint,dict(commitment='confirmed')])['value']
            largest=rpc_client('getTokenLargestAccounts',[mint,dict(commitment='confirmed')])['value']
            if not isinstance(largest,list) or not 1<=len(largest)<=20:raise ValueError()
            accounts=rpc_client('getMultipleAccounts',[[validate_address(v['address']) for v in largest],dict(encoding='jsonParsed',commitment='confirmed')])['value']
            pairs=fetch('https://api.dexscreener.com/token-pairs/v1/solana/'+mint)
            report=evaluate(mint,account,supply,largest,accounts,pairs,started,previous)
        except Exception:
            report=dict(mint=mint,observed=started,expires=started+90,status='unknown',allowed=False,reasons=['required_evidence_unavailable'],warnings=['No token safety conclusion: provider failed or data unavailable.'],metrics={},market=None,policy=POLICY,knowledge=KNOWLEDGE,certified_safe=False)
        if time.time()>report['expires']:
            report['allowed']=False;report['status']='unknown';report['reasons'].append('evidence_stale')
        with db:db.execute('INSERT INTO token_risk(mint,received,payload) VALUES(?,?,?)',(mint,time.time(),json.dumps(report,allow_nan=False)))
        return report
    finally:db.close()

