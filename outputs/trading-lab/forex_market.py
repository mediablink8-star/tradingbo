"""Broker-neutral FX market data with explicit paper bid/ask simulation.
Frankfurter/ECB is a reference/mid-rate source, not a live executable quote.
"""
import json,math,os,time,urllib.parse,urllib.request
DEFAULT_PAIRS=("EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CHF")
DEFAULT_SPREAD_BPS={"EUR/USD":1.0,"GBP/USD":1.2,"USD/JPY":1.0,"AUD/USD":1.4,"USD/CHF":1.4}
def _fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Ember-Forex-Lab/1.0"})
    with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read(500000))
def _spread(pair):
    raw=os.environ.get("FX_SPREAD_BPS")
    if raw:
        try:return max(0.0,float(raw))
        except ValueError:pass
    return DEFAULT_SPREAD_BPS.get(pair,1.5)
def snapshot(pairs=DEFAULT_PAIRS):
    pairs=[p.upper() for p in pairs if isinstance(p,str) and "/" in p]
    currencies=sorted({c for p in pairs for c in p.split("/")});base="USD" if "USD" in currencies else currencies[0]
    targets=[c for c in currencies if c!=base]
    url=os.environ.get("FX_MARKET_DATA_URL","https://api.frankfurter.dev/v2/rates")+"?"+urllib.parse.urlencode({"base":base,"quotes":",".join(targets),"providers":"ecb"})
    raw=_fetch(url);rates={x["quote"]:x["rate"] for x in raw if isinstance(x,dict) and x.get("quote") in targets and isinstance(x.get("rate"),(int,float))}
    provider_date=raw[0].get("date") if raw and isinstance(raw[0],dict) else None
    now=time.time();out={}
    for pair in pairs:
        b,q=pair.split("/",1)
        try:
            mid=float(rates[q]) if b==base else (1/float(rates[b]) if q==base else float(rates[q])/float(rates[b]))
            if not math.isfinite(mid) or mid<=0:raise ValueError()
            spread_bps=_spread(pair);half=spread_bps/20000
            bid=mid*(1-half);ask=mid*(1+half)
            out[pair]={"pair":pair,"price":mid,"bid":bid,"ask":ask,"spread_bps":spread_bps,"observed":now,"provider_date":provider_date,"source":"ECB reference rate via Frankfurter"}
        except (KeyError,TypeError,ValueError,ZeroDivisionError):pass
    if not out:raise ValueError("No usable FX rates were returned.")
    return {"observed":now,"provider_date":provider_date,"source":"ECB reference rate via Frankfurter","pairs":out,"market_open":True}
