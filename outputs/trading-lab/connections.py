"""Session-only model credentials and public Solana balance lookup."""
import json, os, re, threading, time, urllib.request, urllib.error
_lock=threading.Lock()
_key=None
_model=''
_verified=False

def api_key():
    with _lock:return _key or os.environ.get('OPENAI_API_KEY','')

def status():
    with _lock:
        return dict(provider='openai',configured=bool(_key or os.environ.get('OPENAI_API_KEY')),
                    model=_model,verified=_verified,storage='Server memory only; entered key is forgotten on restart.',
                    wallet_execution=False)

def configure(data):
    global _key,_model,_verified
    key=data.get('key','');model=data.get('model','')
    if not isinstance(key,str) or not 16<=len(key)<=512 or not re.fullmatch(r'[A-Za-z0-9_\-]+',key):
        raise ValueError('Enter a valid API key; never enter a wallet seed or private key.')
    if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9_.:\-]{1,100}',model):
        raise ValueError('Enter the exact model ID from your provider.')
    with _lock:_key=key;_model=model;_verified=False
    return status()

def forget():
    global _key,_model,_verified
    with _lock:_key=None;_model='';_verified=False
    return status()

def verify():
    global _verified
    with _lock:key=_key or os.environ.get('OPENAI_API_KEY','');model=_model
    if not key:raise ValueError('Connect your API key first.')
    req=urllib.request.Request('https://api.openai.com/v1/models',headers={'Authorization':'Bearer '+key})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:result=json.loads(response.read(1000000))
        models=sorted({item['id'] for item in result['data'] if isinstance(item.get('id'),str)})
    except urllib.error.HTTPError as exc:
        raise ValueError({401:'API key rejected. Check or replace it.',403:'This API key does not have model-list access.',429:'Provider rate limit reached. Try later.'}.get(exc.code,'Provider check failed. Try later.')) from None
    except Exception:raise ValueError('Could not reach the model provider. Try later.') from None
    accessible=bool(model and model in models)
    with _lock:
        if key==(_key or os.environ.get('OPENAI_API_KEY','')) and model==_model:_verified=accessible
    return dict(**status(),available_models=models,selected_model_accessible=accessible,
        message='Key accepted. Model listed; paper runs will still validate structured responses.' if accessible else 'Key accepted. Choose a listed model ID. No inference was requested.')

_ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
def validate_address(address):
    if not isinstance(address,str) or not 32<=len(address)<=44:raise ValueError('Enter a Solana public wallet address.')
    n=0
    for c in address:
        if c not in _ALPHABET:raise ValueError('Enter a Solana public wallet address.')
        n=n*58+_ALPHABET.index(c)
    length=(n.bit_length()+7)//8+len(address)-len(address.lstrip('1'))
    if length!=32:raise ValueError('Solana public address must decode to 32 bytes.')
    return address

def wallet_balance(address):
    address=validate_address(address)
    payload=dict(jsonrpc='2.0',id=1,method='getBalance',params=[address,dict(commitment='finalized')])
    req=urllib.request.Request('https://api.mainnet-beta.solana.com',data=json.dumps(payload).encode(),
        headers={'Content-Type':'application/json','User-Agent':'MemecoinResearchLab/1.0'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=15) as response:result=json.loads(response.read(100000))
        value=result['result']['value'];slot=result['result']['context']['slot']
        if type(value)!=int or not 0<=value<2**64 or type(slot)!=int:raise ValueError()
    except Exception:raise ValueError('Mainnet balance lookup unavailable. Your wallet connection does not require this lookup to succeed; retry later.') from None
    return dict(address=address,network='Solana mainnet-beta',lamports=value,sol=value/1_000_000_000,
                slot=slot,received=time.time(),permission='public balance only',funds_available_for_trading=False)

