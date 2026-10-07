"""Wallet-approved swaps. No server signing keys or automatic wallet calls."""
import base64, hashlib, json, math, os, re, sqlite3, threading, time, urllib.parse, urllib.request, uuid
from connections import validate_address, _ALPHABET
from token_risk import scan as scan_risk
SOL='So11111111111111111111111111111111111111112'
USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
JUP='JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4'
ALLOWED={JUP,TOKEN,'11111111111111111111111111111111','ComputeBudget111111111111111111111111111111','ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL','MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr'}
_key='';_lock=threading.Lock()

def encode58(raw):
    n=int.from_bytes(raw,'big');text=''
    while n:n,r=divmod(n,58);text=_ALPHABET[r]+text
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+text

def request(url,payload=None,headers=None):
    req=urllib.request.Request(url,data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type':'application/json','User-Agent':'MemecoinResearchLab/1.0',**(headers or {})})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:result=json.loads(response.read(2000000))
        if 'error' in result:raise ValueError()
        return result
    except Exception:raise ValueError('Provider request failed. Check credentials, network and rate limits; no transaction was sent by this server.') from None

def rpc(method,params):return request('https://api.mainnet-beta.solana.com',dict(jsonrpc='2.0',id=1,method=method,params=params))['result']
def credential():return _key or os.environ.get('JUPITER_API_KEY','')
def connect(data):
    global _key
    key=data.get('key','')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,512}',key):raise ValueError('Enter a Jupiter API key.')
    with _lock:_key=key
    return dict(configured=True,storage='Session memory only')
def quote(a,b,amount):
    if not credential():raise ValueError('Connect a Jupiter API key first.')
    url='https://api.jup.ag/swap/v1/quote?'+urllib.parse.urlencode(dict(inputMint=a,outputMint=b,amount=str(amount),slippageBps=50,swapMode='ExactIn',asLegacyTransaction='true',restrictIntermediateTokens='true'))
    value=request(url,headers={'x-api-key':credential()})
    try:
        impact=float(value['priceImpactPct'])
        if value['inputMint']!=a or value['outputMint']!=b or int(value['inAmount'])!=amount or value['swapMode']!='ExactIn' or value['slippageBps']!=50 or not value['routePlan']:raise ValueError()
        if not math.isfinite(impact) or not 0<=impact<=.01 or not 0<int(value['otherAmountThreshold'])<=int(value['outAmount']):raise ValueError()
    except (KeyError,ValueError,TypeError):raise ValueError('No acceptable exact-input route: require 0.5% slippage and at most 1% quoted impact.') from None
    return value

def message(encoded,wallet,unsigned=True):
    try:
        raw=base64.b64decode(encoded,validate=True)
        if not 100<=len(raw)<=1232 or raw[0]!=1:raise ValueError()
        if unsigned and any(raw[1:65]):raise ValueError()
        m=raw[65:]
        if len(m)<36 or m[0]!=1 or m[1]!=0:raise ValueError()
        offset=3
        def compact():
            nonlocal offset
            value=0
            for shift in (0,7,14):
                byte=m[offset];offset+=1;value|=(byte&127)<<shift
                if not byte&128:return value
            raise ValueError()
        count=compact()
        if not 1<=count<=64 or offset+count*32+32>len(m):raise ValueError()
        keys=[encode58(m[offset+i*32:offset+(i+1)*32]) for i in range(count)];offset+=count*32+32
        if keys[0]!=wallet:raise ValueError()
        instructions=compact();programs=[]
        for _ in range(instructions):
            index=m[offset];offset+=1;accounts=compact()
            if index>=count or any(x>=count for x in m[offset:offset+accounts]):raise ValueError()
            offset+=accounts;size=compact()
            if offset+size>len(m):raise ValueError()
            data=m[offset:offset+size];offset+=size;program=keys[index]
            if program not in ALLOWED:raise ValueError()
            if program==TOKEN and data and data[0] in (4,5,6):raise ValueError()
            programs.append(program)
        if offset!=len(m) or JUP not in programs:raise ValueError()
        return m
    except Exception:raise ValueError('Transaction rejected: unsupported format, signer, program or authority instruction.') from None

class Swaps:
    def __init__(self,path):self.path=path;self.lock=threading.Lock();self.db().close()
    def db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute('CREATE TABLE IF NOT EXISTS swaps(id TEXT PRIMARY KEY,wallet TEXT,usd REAL,state TEXT,payload TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS swap_control(id INTEGER PRIMARY KEY CHECK(id=1), halted INTEGER)')
        db.commit();return db
    def state(self):
        db=self.db()
        try:
            row=db.execute('SELECT halted FROM swap_control WHERE id=1').fetchone()
            records=[json.loads(r[0]) for r in db.execute('SELECT payload FROM swaps ORDER BY rowid DESC LIMIT 30')]
            return dict(configured=bool(credential()),buys_halted=bool(row and row[0]),mode='wallet_approved',autonomous=False,per_buy_usdc_limit=10,total_reserved_usdc_limit=100,records=[{k:v for k,v in r.items() if k not in ('transaction','message')} for r in records])
        finally:db.close()
    def halt(self):
        db=self.db()
        try:
            with db:db.execute('INSERT OR REPLACE INTO swap_control VALUES(1,1)')
        finally:db.close()
        return self.state()
    def prepare(self,data):
        if not credential():raise ValueError('Connect a Jupiter API key first.')
        wallet=validate_address(data.get('wallet'));mint=validate_address(data.get('mint'));side=data.get('side','buy')
        if mint==SOL or side not in ('buy','sell'):raise ValueError('Choose a token mint and buy or sell.')
        with self.lock:
            db=self.db()
            try:
                active=db.execute("SELECT payload FROM swaps WHERE wallet=? AND json_extract(payload,'$.mint')=? AND json_extract(payload,'$.side')=? AND state IN ('prepared','awaiting_wallet','pending')",(wallet,mint,side)).fetchall()
                if any(json.loads(r[0])['state']!='prepared' or time.time()<=json.loads(r[0])['expires'] for r in active):raise ValueError('An unresolved intent already exists for this wallet, token and action. Recover or confirm it before preparing another.')
            finally:db.close()
            control=self.state()
            if side=='buy' and control['buys_halted']:raise ValueError('Real buy stop is latched. Sells remain available.')
            account=rpc('getAccountInfo',[mint,dict(encoding='jsonParsed',commitment='confirmed')])['value']
            try:
                info=account['data']['parsed']['info']
                if account['owner']!=TOKEN or account['data']['parsed']['type']!='mint' or not info['isInitialized']:raise ValueError()
                if side=='buy' and (not {'mintAuthority','freezeAuthority'}<=set(info) or info['mintAuthority'] is not None or info['freezeAuthority'] is not None):raise ValueError()
                decimals=info['decimals']
                if type(decimals)!=int or not 0<=decimals<=12:raise ValueError()
            except Exception:raise ValueError('Unsupported token or mutable mint/freeze authority. Token-2022 is not supported; this check does not certify token safety.') from None
            risk=None
            if side=='buy':
                risk=scan_risk(mint,self.path,rpc_client=rpc,fetch=request,mint_account=account)
                if not risk['allowed']:raise ValueError('Token risk gate blocked buy: '+', '.join(risk['reasons']))
            rate=int(quote(SOL,USDC,1_000_000_000)['outAmount'])/1_000_000
            if not math.isfinite(rate) or rate<=0:raise ValueError('Invalid SOL/USDC reference.')
            usd=0
            if side=='buy':
                budget=data.get('usd',10)
                if isinstance(budget,bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or not 0<budget<=10:raise ValueError('Buy allocation must be above zero and at most 10 USDC-equivalent.')
                amount=int(budget/rate*1_000_000_000)
                if amount<=0:raise ValueError('Buy amount too small.')
                usd=amount/1_000_000_000*rate
                route=quote(SOL,mint,amount)
                if len(route['routePlan'])!=1 or route['routePlan'][0].get('swapInfo',{}).get('ammKey')!=risk['market']['pair']:raise ValueError('Buy route does not use the screened pool directly.')
                reverse=quote(mint,SOL,int(route['otherAmountThreshold']))
                if int(reverse['outAmount'])<amount*.90:raise ValueError('Round-trip quote loses more than 10%; buy rejected.')
            else:
                raw=data.get('amount','')
                if not isinstance(raw,str) or not re.fullmatch(r'[0-9]{1,20}',raw) or not 0<int(raw)<2**64:raise ValueError('Sell amount must be a positive integer in token base units.')
                amount=int(raw)
                tokens=rpc('getTokenAccountsByOwner',[wallet,dict(mint=mint),dict(encoding='jsonParsed',commitment='confirmed')])['value']
                owned=sum(int(t['account']['data']['parsed']['info']['tokenAmount']['amount']) for t in tokens)
                if amount>owned:raise ValueError('Sell exceeds the on-chain token balance.')
                route=quote(mint,SOL,amount)
            balance=rpc('getBalance',[wallet,dict(commitment='confirmed')])['value']
            if balance<(amount if side=='buy' else 0)+10_000_000:raise ValueError('Keep at least 0.01 SOL above swap input for fees and rent.')
            built=request('https://api.jup.ag/swap/v1/swap',dict(userPublicKey=wallet,quoteResponse=route,wrapAndUnwrapSol=True,asLegacyTransaction=True,dynamicComputeUnitLimit=True,dynamicSlippage=False,prioritizationFeeLamports=100000),{'x-api-key':credential()})
            encoded=built.get('swapTransaction','');m=message(encoded,wallet)
            height=built.get('lastValidBlockHeight')
            if type(height)!=int or height<=0:raise ValueError('Missing transaction expiry.')
            simulation=rpc('simulateTransaction',[encoded,dict(encoding='base64',sigVerify=False,replaceRecentBlockhash=False,commitment='confirmed',accounts=dict(encoding='base64',addresses=[wallet]))])['value']
            if simulation.get('err') is not None:raise ValueError('On-chain simulation failed; nothing sent.')
            after=simulation.get('accounts')
            if not after or type(after[0].get('lamports'))!=int:raise ValueError('Simulation did not verify wallet balance.')
            debit=balance-after[0]['lamports']
            if debit>(amount if side=='buy' else 0)+5_000_000:raise ValueError('Simulated SOL debit exceeds swap plus fee/rent allowance.')
            if side=='buy':
                before_tokens=simulation.get('preTokenBalances');after_tokens=simulation.get('postTokenBalances')
                if not isinstance(before_tokens,list) or not isinstance(after_tokens,list):raise ValueError('RPC did not provide token balance deltas; cannot verify the requested recipient and mint.')
                def tokens_owned(values):
                    return sum(int(t['uiTokenAmount']['amount']) for t in values if t.get('owner')==wallet and t.get('mint')==mint)
                if tokens_owned(after_tokens)-tokens_owned(before_tokens)<int(route['otherAmountThreshold']):raise ValueError('Simulation does not deliver the minimum requested tokens to this wallet.')
            elif after[0]['lamports']-balance<int(route['otherAmountThreshold'])-5_000_000:
                raise ValueError('Simulation does not return the minimum quoted SOL after the fee/rent allowance.')
            fees=rpc('getFeeForMessage',[base64.b64encode(m).decode(),dict(commitment='confirmed')])['value']
            if type(fees)!=int or not 0<=fees<=500000:raise ValueError('Transaction fee unavailable or exceeds 0.0005 SOL.')
            fee_usd=(max(0,debit-(amount if side=='buy' else 0))+fees)/1_000_000_000*rate
            trade_quality=None
            if side=='buy':
                from market_evidence import cost_hurdle
                trade_quality=cost_hurdle(10*int(reverse['otherAmountThreshold'])/amount,10*fee_usd/usd)
                if not trade_quality['allowed']:raise ValueError('Assumed upside does not comfortably cover round-trip cost and uncertainty; buy rejected.')
            reserve=usd+fee_usd
            if risk and time.time()>risk['expires']:raise ValueError('Token risk evidence expired during preparation.')
            record=dict(id=uuid.uuid4().hex,wallet=wallet,mint=mint,side=side,state='prepared',received=time.time(),expires=min(time.time()+45,risk['expires']) if risk else time.time()+45,token_risk=risk,lastValidBlockHeight=height,input_base_units=str(amount),expected_output_base_units=route['outAmount'],minimum_output_base_units=route['otherAmountThreshold'],token_decimals=decimals,trade_quality=trade_quality,slippage_bps=50,reference_sol_usdc=rate,reserved_usdc=reserve,network_fee_lamports=fees,message=encode58(m),transaction=encoded,message_hash=hashlib.sha256(m).hexdigest(),checks=['Basic rug-risk gate for buys; only the screened direct pool','Buy reverse route; quote impact and slippage','Wallet signer and permitted top-level programs','Simulation and wallet SOL debit','Persistent conservative purchase budget'],limitations='Basic checks sample 20 accounts; LP protection, hidden insiders and future sellability remain unverified. Amounts use a SOL/USDC quote, not a guaranteed USD price.')
            db=self.db()
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    duplicates=db.execute("SELECT payload FROM swaps WHERE wallet=? AND json_extract(payload,'$.mint')=? AND json_extract(payload,'$.side')=? AND state IN ('prepared','awaiting_wallet','pending')",(wallet,mint,side)).fetchall()
                    if any(json.loads(r[0])['state']!='prepared' or json.loads(r[0])['expires']>time.time() for r in duplicates):raise ValueError('An unresolved intent already exists for this wallet, token and side.')
                    spent=db.execute('SELECT COALESCE(SUM(usd),0) FROM swaps WHERE wallet=?',(wallet,)).fetchone()[0]
                    if side=='buy' and spent+reserve>100:raise ValueError('100 USDC-equivalent conservative budget exhausted for this wallet.')
                    db.execute('INSERT INTO swaps VALUES(?,?,?,?,?)',(record['id'],wallet,reserve,'prepared',json.dumps(record)))
            finally:db.close()
            return record
    def ready(self,identifier,wallet):
        db=self.db()
        try:row=db.execute('SELECT payload FROM swaps WHERE id=?',(identifier,)).fetchone()
        finally:db.close()
        if not row:raise ValueError('Unknown prepared swap.')
        record=json.loads(row[0])
        if wallet!=record['wallet'] or record['state']!='prepared' or time.time()>record['expires']:raise ValueError('Swap expired, changed wallet or already used. Prepare again.')
        if record['side']=='buy' and (not record.get('token_risk',{}).get('allowed') or time.time()>record.get('token_risk',{}).get('expires',0)):raise ValueError('Fresh token-risk screening is required before a buy handoff.')
        if record['side']=='buy' and self.state()['buys_halted']:raise ValueError('Buy stop is latched.')
        if rpc('getBlockHeight',[dict(commitment='confirmed')])>record['lastValidBlockHeight'] or time.time()>record['expires']:raise ValueError('Transaction blockhash expired.')
        # Reserve once-only intent before the browser can open the wallet.
        record['state']='awaiting_wallet'
        db=self.db()
        try:
            with db:
                cursor=db.execute("UPDATE swaps SET state='awaiting_wallet',payload=? WHERE id=? AND state='prepared'",(json.dumps(record),identifier))
                if cursor.rowcount!=1:raise ValueError('Swap already handed to wallet.')
        finally:db.close()
        return dict(id=identifier,message=record['message'],wallet=wallet)
    def confirm(self,identifier,signature):
        if not isinstance(signature,str) or not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{64,88}',signature):raise ValueError('Invalid signature.')
        db=self.db()
        try:row=db.execute('SELECT payload FROM swaps WHERE id=?',(identifier,)).fetchone()
        finally:db.close()
        if not row:raise ValueError('Unknown swap.')
        record=json.loads(row[0])
        if record['state'] not in ('awaiting_wallet','pending','confirmed','failed'):raise ValueError('Swap was not handed to wallet.')
        if record.get('signature') and record['signature']!=signature:raise ValueError('Signature already recorded; cannot replace it.')
        result=rpc('getTransaction',[signature,dict(encoding='base64',commitment='confirmed',maxSupportedTransactionVersion=0)])
        if result:
            raw=result['transaction'][0];m=message(raw,record['wallet'],unsigned=False)
            if hashlib.sha256(m).hexdigest()!=record['message_hash']:raise ValueError('On-chain transaction does not match the prepared swap.')
            from execution_audit import reconcile
            record['reconciliation']=reconcile(record,result)
            record['state']='failed' if result['meta']['err'] is not None else 'confirmed';record['chain_fee_lamports']=result['meta']['fee'];record['slot']=result['slot']
        else:record['state']='pending'
        record['signature']=signature
        db=self.db()
        try:
            with db:
                conflict=db.execute("SELECT id FROM swaps WHERE id!=? AND json_extract(payload,'$.signature')=?",(identifier,signature)).fetchone()
                if conflict:raise ValueError('Signature already belongs to another swap intent.')
                db.execute('UPDATE swaps SET state=?,payload=? WHERE id=?',(record['state'],json.dumps(record),identifier))
        finally:db.close()
        return dict(id=identifier,state=record['state'],signature=signature,reconciliation=record.get('reconciliation'),explorer='https://solscan.io/tx/'+signature)


    def recover(self,identifier):
        db=self.db()
        try:row=db.execute('SELECT payload FROM swaps WHERE id=?',(identifier,)).fetchone()
        finally:db.close()
        if not row:raise ValueError('Unknown swap')
        record=json.loads(row[0])
        if record.get('signature'):return self.confirm(identifier,record['signature'])
        if record['state']!='awaiting_wallet':return {'id':identifier,'state':record['state'],'message':'No interrupted wallet handoff to recover.'}
        # Read-only search; never re-submit a transaction or open the wallet again.
        signatures=rpc('getSignaturesForAddress',[record['wallet'],{'limit':20,'commitment':'confirmed'}])
        for entry in signatures:
            if entry.get('blockTime') and entry['blockTime']<record['received']-30:continue
            result=rpc('getTransaction',[entry['signature'],dict(encoding='base64',commitment='confirmed',maxSupportedTransactionVersion=0)])
            if not result:continue
            try:m=message(result['transaction'][0],record['wallet'],unsigned=False)
            except ValueError:continue
            if hashlib.sha256(m).hexdigest()==record['message_hash']:return self.confirm(identifier,entry['signature'])
        return {'id':identifier,'state':'unresolved','message':'No matching transaction among the latest 20 wallet signatures. Reservation retained; no resend or automatic refund.'}
