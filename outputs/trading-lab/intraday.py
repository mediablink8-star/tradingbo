"""Intraday FX OHLC adapter for historical research.

Uses Alpha Vantage FX_INTRADAY when ALPHAVANTAGE_API_KEY is configured.
The provider supports 1/5/15/30/60 minute intervals and historical month
queries. This module only downloads and normalizes market data; it never
places orders.
"""
import datetime,json,math,os,urllib.parse,urllib.request
from backtest import Candle

VALID_INTERVALS={"1min","5min","15min","30min","60min"}

def _fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Ember-Forex-Lab/1.0"})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read(5_000_000))

def _timestamp(value):
    dt=datetime.datetime.strptime(value,"%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()

def load_month(pair,month,interval="15min"):
    if interval not in VALID_INTERVALS: raise ValueError("Unsupported interval")
    if len(month)!=7 or month[4]!="-": raise ValueError("month must be YYYY-MM")
    key=os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key: raise ValueError("ALPHAVANTAGE_API_KEY is required")
    base,quote=pair.upper().split("/",1)
    url="https://www.alphavantage.co/query?"+urllib.parse.urlencode({
        "function":"FX_INTRADAY","from_symbol":base,"to_symbol":quote,
        "interval":interval,"outputsize":"full","month":month,"apikey":key})
    raw=_fetch(url)
    series=raw.get("Time Series FX ("+interval+")")
    if not isinstance(series,dict):
        note=raw.get("Note") or raw.get("Information") or "Provider returned no intraday series"
        raise ValueError(str(note))
    candles=[]
    for stamp,row in series.items():
        try:
            o,h,l,c=(float(row[k]) for k in ("1. open","2. high","3. low","4. close"))
            if not all(math.isfinite(x) and x>0 for x in (o,h,l,c)) or l>h or not (l<=o<=h and l<=c<=h):
                continue
            candles.append(Candle(_timestamp(stamp),o,h,l,c))
        except (KeyError,TypeError,ValueError):
            continue
    candles.sort(key=lambda x:x.timestamp)
    if not candles: raise ValueError("No valid intraday candles returned")
    return candles

def validate(candles,interval_minutes):
    expected=interval_minutes*60
    timestamps=[c.timestamp for c in candles]
    duplicates=len(timestamps)-len(set(timestamps))
    bad_order=sum(b<=a for a,b in zip(timestamps,timestamps[1:]))
    gaps=[b-a for a,b in zip(timestamps,timestamps[1:]) if b>a and b-a>expected*1.5]
    return {"rows":len(candles),"duplicates":duplicates,"non_monotonic":bad_order,
            "gaps":len(gaps),"max_gap_minutes":max((g/60 for g in gaps),default=0)}

def save_json(candles,path):
    with open(path,"w",encoding="utf-8") as f: json.dump([c.__dict__ for c in candles],f)
