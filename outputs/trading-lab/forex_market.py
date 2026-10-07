"""Broker-neutral FX market data using ECB reference rates."""
import json, math, os, time, urllib.parse, urllib.request
DEFAULT_PAIRS=("EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CHF")
def _fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Ember-Forex-Lab/1.0"})
    with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read(500000))
def snapshot(pairs=DEFAULT_PAIRS):
    pairs=[p.upper() for p in pairs if isinstance(p,str) and "/" in p]
    currencies=sorted({c for p in pairs for c in p.split("/")})
    base="USD" if "USD" in currencies else currencies[0]
    targets=[c for c in currencies if c!=base]
    url=os.environ.get("FX_MARKET_DATA_URL","https://api.frankfurter.app/latest")+"?"+urllib.parse.urlencode({"from":base,"to":",".join(targets)})
    raw=_fetch(url);rates=raw.get("rates",{});now=time.time();out={}
    for pair in pairs:
        b,q=pair.split("/",1)
        try:
            price=float(rates[q]) if b==base else (1/float(rates[b]) if q==base else float(rates[q])/float(rates[b]))
            if not math.isfinite(price) or price<=0:raise ValueError()
            out[pair]={"pair":pair,"price":price,"observed":now,"source":"ECB reference rates via Frankfurter"}
        except (KeyError,TypeError,ValueError,ZeroDivisionError):pass
    if not out:raise ValueError("No usable FX rates were returned.")
    return {"observed":now,"source":"ECB reference rates via Frankfurter","pairs":out,"market_open":True}
