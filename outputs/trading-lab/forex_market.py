"""Broker-neutral FX market data with explicit paper bid/ask simulation.
Frankfurter/ECB is a reference/mid-rate source, not a live executable quote.
"""
import datetime,json,math,os,time,urllib.parse,urllib.request
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
def _alpha_vantage(pairs):\n    key=os.environ.get("ALPHAVANTAGE_API_KEY")\n    if not key: raise ValueError("ALPHAVANTAGE_API_KEY is required for the Alpha Vantage provider.")\n    out={}\n    for pair in pairs:\n        b,q=pair.split("/",1)\n        url="https://www.alphavantage.co/query?"+urllib.parse.urlencode({"function":"CURRENCY_EXCHANGE_RATE","from_currency":b,"to_currency":q,"apikey":key})\n        raw=_fetch(url);row=raw.get("Realtime Currency Exchange Rate",{})\n        mid=float(row["5. Exchange Rate"]);stamp=row.get("6. Last Refreshed")\n        observed=time.time();spread_bps=_spread(pair);half=spread_bps/20000\n        out[pair]={"pair":pair,"price":mid,"bid":mid*(1-half),"ask":mid*(1+half),"spread_bps":spread_bps,"observed":observed,"fetched_at":observed,"provider_date":stamp,"source":"Alpha Vantage realtime FX rate"}\n    return {"observed":time.time(),"provider_date":None,"source":"Alpha Vantage realtime FX rate","pairs":out,"market_open":True}\ndef snapshot(pairs=DEFAULT_PAIRS):\n    if os.environ.get("FX_PROVIDER","").lower()=="alpha_vantage": return _alpha_vantage(pairs)
    pairs=[p.upper() for p in pairs if isinstance(p,str) and "/" in p]
    currencies=sorted({c for p in pairs for c in p.split("/")});base="USD" if "USD" in currencies else currencies[0]
    targets=[c for c in currencies if c!=base]
    url=os.environ.get("FX_MARKET_DATA_URL","https://api.frankfurter.dev/v2/rates")+"?"+urllib.parse.urlencode({"base":base,"quotes":",".join(targets),"providers":"ecb"})
    raw=_fetch(url);rates={x["quote"]:x["rate"] for x in raw if isinstance(x,dict) and x.get("quote") in targets and isinstance(x.get("rate"),(int,float))}
    provider_date=raw[0].get("date") if raw and isinstance(raw[0],dict) else None
    now=time.time();\n    try:\n        provider_observed=datetime.datetime.fromisoformat(str(provider_date)).replace(tzinfo=datetime.timezone.utc).timestamp() if provider_date else now\n    except ValueError:\n        provider_observed=now\n    out={}
    for pair in pairs:
        b,q=pair.split("/",1)
        try:
            mid=float(rates[q]) if b==base else (1/float(rates[b]) if q==base else float(rates[q])/float(rates[b]))
            if not math.isfinite(mid) or mid<=0:raise ValueError()
            spread_bps=_spread(pair);half=spread_bps/20000
            bid=mid*(1-half);ask=mid*(1+half)
            out[pair]={"pair":pair,"price":mid,"bid":bid,"ask":ask,"spread_bps":spread_bps,"observed":provider_observed,"fetched_at":now,"provider_date":provider_date,"source":"ECB reference rate via Frankfurter"}
        except (KeyError,TypeError,ValueError,ZeroDivisionError):pass
    if not out:raise ValueError("No usable FX rates were returned.")
    return {"observed":provider_observed,"fetched_at":now,"provider_date":provider_date,"source":"ECB reference rate via Frankfurter","pairs":out,"market_open":True}
