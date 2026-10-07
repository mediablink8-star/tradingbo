"""Historical daily FX reference-rate loader for offline research.

The source is Frankfurter's ECB reference-rate series. These are daily
reference/mid rates, not executable intraday prices, so each returned Candle
uses the daily reference rate as close/open/high/low. This is intentionally
not presented as tick or OHLC market data.
"""
from dataclasses import dataclass
import datetime,json,math,os,urllib.parse,urllib.request
from backtest import Candle

DEFAULT_PAIRS=("EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CHF")

def _fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Ember-Forex-Lab/1.0"})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read(2_000_000))

def _date_ts(value):
    return datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.timezone.utc).timestamp()

def load_daily(pair,start_date,end_date=None,provider="ecb"):
    pair=pair.upper()
    base,quote=pair.split("/",1)
    if not start_date:
        raise ValueError("start_date is required")
    end_date=end_date or datetime.date.today().isoformat()
    currencies={base,quote,"EUR"}
    url="https://api.frankfurter.dev/v2/rates?"+urllib.parse.urlencode({
        "from":start_date,"to":end_date,"base":"EUR",
        "quotes":",".join(sorted(c for c in currencies if c!="EUR")),
        "providers":provider,
    })
    rows=_fetch(url)
    candles=[]
    for row in rows:
        if not isinstance(row,dict) or not row.get("date"): continue
        rates=row.get("rate")
        if not isinstance(rates,(int,float)): continue
        if base=="EUR": mid=float(rates) if quote!="EUR" else 1.0
        elif quote=="EUR":
            if base not in row: continue
            mid=1.0/float(row[base])
        else:
            if base not in row: continue
            if quote not in row: continue
            mid=float(row[quote])/float(row[base])
        if not math.isfinite(mid) or mid<=0: continue
        ts=_date_ts(row["date"])
        candles.append(Candle(ts,mid,mid,mid,mid))
    candles.sort(key=lambda c:c.timestamp)
    if not candles: raise ValueError(f"No historical FX data for {pair}.")
    return candles

def load_pairs(pairs,start_date,end_date=None,provider="ecb"):
    return {pair.upper():load_daily(pair,start_date,end_date,provider) for pair in pairs}

def save_json(candles,path):
    payload=[c.__dict__ for c in candles]
    with open(path,"w",encoding="utf-8") as f: json.dump(payload,f)

def load_json(path):
    with open(path,encoding="utf-8") as f: rows=json.load(f)
    return [Candle(float(r["timestamp"]),float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"])) for r in rows]
