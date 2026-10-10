"""Broker-neutral FX market data with explicit paper bid/ask simulation.

Frankfurter/ECB is a reference/mid-rate source, not a live executable quote.
The generated bid/ask is a configurable simulation spread, not broker pricing.
"""
import datetime
import json
import math
import os
import time
import urllib.parse
import urllib.request

DEFAULT_PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF")

# Metals are quoted per troy ounce against USD and are not currencies. They are
# exposed as their own contract family rather than forced through the FX paths.
METALS = ("XAU/USD",)
ALL_PAIRS = DEFAULT_PAIRS + METALS
DEFAULT_SPREAD_BPS = {
    "EUR/USD": 1.0,
    "GBP/USD": 1.2,
    "USD/JPY": 1.0,
    "AUD/USD": 1.4,
    "USD/CHF": 1.4,
    # Metals are quoted per troy ounce; a one-tenth-of-a-cent spread assumption
    # is used, and it remains a modelled figure rather than an observed one.
    "XAU/USD": 0.12,
    "XAG/USD": 0.15,
}

# Interval -> (Yahoo interval, max lookback range). These are empirically
# verified limits; Yahoo serves null bars or errors outside them.
YAHOO_INTERVALS = {
    "1m": ("1m", "1d"),
    "2m": ("2m", "5d"),
    "5m": ("5m", "5d"),
    "15m": ("15m", "5d"),
    "30m": ("30m", "1mo"),
    "1h": ("1h", "1mo"),
    "1d": ("1d", "1y"),
}


# Yahoo does not serve a spot gold symbol (XAUUSD=X returns 404). GC=F is the
# COMEX gold futures front contract, so a quote sourced from it is a futures
# price, not spot XAU/USD, and carries a basis against the physical market.
YAHOO_SYMBOLS = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
}


def _yahoo_symbol(pair):
    explicit = YAHOO_SYMBOLS.get(pair.upper())
    if explicit:
        return explicit
    return pair.replace("/", "").upper() + "=X"


def is_metal(pair):
    return str(pair or "").upper().split("/")[0] in ("XAU", "XAG")


def _fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Ember-Forex-Lab/1.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read(500000))


def _spread(pair):
    raw = os.environ.get("FX_SPREAD_BPS")
    if raw:
        try:
            value = float(raw)
            if math.isfinite(value) and value >= 0:
                return value
        except ValueError:
            pass
    return DEFAULT_SPREAD_BPS.get(pair, 1.5)


def _provider_timestamp(value):
    """Parse a provider timestamp; naive provider timestamps are treated as UTC."""
    if not value:
        return 0.0
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _fetch_yahoo(url):
    """Yahoo's chart endpoint needs a browser-like UA or it returns 404."""
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "Chrome/126 Safari/537.36"
        ),
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read(8_000_000))


def _yahoo_series(pair, interval):
    """Return list of OHLC bars for one pair.

    Null OHLC bars are dropped rather than forward-filled: a flat carry-forward
    bar is a provider artifact, not a trade.
    """
    iv, rng = YAHOO_INTERVALS.get(interval, YAHOO_INTERVALS["15m"])
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + _yahoo_symbol(pair)
        + "?"
        + urllib.parse.urlencode({"interval": iv, "range": rng})
    )
    payload = _fetch_yahoo(url)
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ValueError("Yahoo returned an error for " + pair)
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo returned no chart for " + pair)
    result = results[0]
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []

    bars = []
    for i, stamp in enumerate(stamps):
        try:
            o = float(opens[i]); h = float(highs[i])
            lo = float(lows[i]); c = float(closes[i])
        except (IndexError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (o, h, lo, c)):
            continue
        if h < max(o, c, lo) or lo > min(o, c, h):
            continue
        bars.append({"t": int(stamp), "o": o, "h": h, "l": lo, "c": c})
    if not bars:
        raise ValueError("Yahoo returned no usable bars for " + pair)
    return bars


def yahoo_bars(pair="EUR/USD", interval="15m", limit=400):
    """Public candle history for charting. Never fabricates a price."""
    bars = _yahoo_series(pair, interval)
    if limit and len(bars) > limit:
        bars = bars[-int(limit):]
    return {
        "pair": pair, "interval": interval, "bars": bars,
        "source": "Yahoo Finance chart endpoint (unofficial)",
        "observed": bars[-1]["t"], "fetched_at": time.time(),
    }


def _spot_metal(pair):
    """True spot metal from gold-api (free, no key).

    Yahoo has no spot gold symbol, so intraday bars come from the GC=F futures
    contract and carry a basis against this price. Reporting the futures number
    as if it were spot would misstate the instrument, so the spot quote is
    authoritative and the futures series is labelled as a proxy.
    """
    code = pair.split("/")[0].upper()
    url = "https://api.gold-api.com/price/" + code
    raw = _fetch_yahoo(url)
    price = raw.get("price")
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("Spot metal price unavailable for " + pair)
    observed = _provider_timestamp(raw.get("updatedAt")) or time.time()
    spread_bps = _spread(pair)
    half = spread_bps / 20000
    return {
        "pair": pair, "price": float(price),
        "bid": float(price) * (1 - half), "ask": float(price) * (1 + half),
        "spread_bps": spread_bps, "observed": observed,
        "fetched_at": time.time(),
        "provider_date": raw.get("updatedAt") or None,
        "instrument": "metal",
        "source": "gold-api.com spot metal",
        "note": "spot XAU/USD per troy ounce",
    }


def _yahoo(pairs):
    """Live snapshot built from the most recent Yahoo bar per pair.

    The bar close is a mid reference, not an executable broker quote. Bid/ask
    remain simulated from the configured spread, exactly as with ECB.
    """
    interval = os.environ.get("FX_YAHOO_INTERVAL", "15m")
    out = {}
    latest = 0.0
    for pair in pairs:
        if is_metal(pair):
            # Spot is authoritative for a metal quote. The futures contract is
            # fetched only to report the basis, never in place of the spot price.
            quote = _spot_metal(pair)
            basis = None
            try:
                futures = _yahoo_series(pair, interval)[-1]
                basis = (float(quote["price"]) - float(futures["c"]))
                quote["basis_vs_futures"] = round(basis, 4)
                quote["futures_symbol"] = _yahoo_symbol(pair).upper()
            except Exception:
                pass
            out[pair] = quote
            latest = max(latest, float(quote["observed"]))
            continue
        bars = _yahoo_series(pair, interval)
        bar = bars[-1]
        mid = float(bar["c"])
        spread_bps = _spread(pair)
        half = spread_bps / 20000
        source = "Yahoo Finance chart endpoint (unofficial)"
        if is_metal(pair):
            source = ("Yahoo " + _yahoo_symbol(pair).upper()
                      + " futures, not spot metal")
        out[pair] = {
            "pair": pair, "price": mid,
            "bid": mid * (1 - half), "ask": mid * (1 + half),
            "spread_bps": spread_bps, "observed": float(bar["t"]),
            "fetched_at": time.time(),
            "provider_date": datetime.datetime.fromtimestamp(
                bar["t"], datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S"),
            "instrument": "metal" if is_metal(pair) else "fx",
            "source": source,
        }
        latest = max(latest, float(bar["t"]))
    if not out:
        raise ValueError("No usable FX rates were returned.")
    sources = sorted({q.get("source", "") for q in out.values()})
    return {
        "observed": latest, "fetched_at": time.time(),
        "provider_date": datetime.datetime.fromtimestamp(
            latest, datetime.timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "source": " + ".join(s for s in sources if s),
        "pairs": out, "market_open": None,
    }


def _alpha_vantage(pairs):
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise ValueError(
            "ALPHAVANTAGE_API_KEY is required for the Alpha Vantage provider."
        )
    out = {}
    for pair in pairs:
        base, quote = pair.split("/", 1)
        url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode({
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": base,
            "to_currency": quote,
            "apikey": key,
        })
        raw = _fetch(url)
        row = raw.get("Realtime Currency Exchange Rate", {})
        if "5. Exchange Rate" not in row:
            raise ValueError("Alpha Vantage returned no exchange rate for " + pair)
        mid = float(row["5. Exchange Rate"])
        if not math.isfinite(mid) or mid <= 0:
            raise ValueError("Alpha Vantage returned an invalid rate for " + pair)
        stamp = row.get("6. Last Refreshed")
        fetched_at = time.time()
        observed = _provider_timestamp(stamp)
        if not observed:
            raise ValueError("Alpha Vantage returned no valid quote timestamp for " + pair)
        spread_bps = _spread(pair)
        half = spread_bps / 20000
        out[pair] = {
            "pair": pair, "price": mid,
            "bid": mid * (1 - half), "ask": mid * (1 + half),
            "spread_bps": spread_bps, "observed": observed,
            "fetched_at": fetched_at, "provider_date": stamp,
            "source": "Alpha Vantage exchange-rate endpoint",
        }
    return {
        "observed": time.time(), "provider_date": None,
        "source": "Alpha Vantage exchange-rate endpoint",
        "pairs": out, "market_open": True,
    }


def snapshot(pairs=DEFAULT_PAIRS):
    pairs = [p.upper() for p in pairs if isinstance(p, str) and "/" in p]
    if not pairs:
        raise ValueError("At least one valid FX pair is required.")
    provider = os.environ.get("FX_PROVIDER", "").lower()
    if provider == "alpha_vantage":
        return _alpha_vantage(pairs)
    if provider == "ecb":
        return _frankfurter(pairs)
    if provider == "yahoo":
        return _yahoo(pairs)
    # Default: prefer the intraday Yahoo feed, but never lose the snapshot if it
    # fails. Frankfurter is slower but independent, so it is a genuine fallback.
    try:
        return _yahoo(pairs)
    except Exception:
        return _frankfurter(pairs)


def _frankfurter(pairs):

    currencies = sorted({currency for pair in pairs for currency in pair.split("/")})
    base = "USD" if "USD" in currencies else currencies[0]
    targets = [currency for currency in currencies if currency != base]
    url = os.environ.get(
        "FX_MARKET_DATA_URL", "https://api.frankfurter.dev/v2/rates"
    ) + "?" + urllib.parse.urlencode({
        "base": base, "quotes": ",".join(targets), "providers": "ecb"
    })
    raw = _fetch(url)
    rates = {
        row["quote"]: row["rate"]
        for row in raw
        if isinstance(row, dict)
        and row.get("quote") in targets
        and isinstance(row.get("rate"), (int, float))
    }
    provider_date = raw[0].get("date") if raw and isinstance(raw[0], dict) else None
    now = time.time()
    try:
        provider_observed = (
            datetime.datetime.fromisoformat(str(provider_date))
            .replace(tzinfo=datetime.timezone.utc).timestamp()
            if provider_date else 0.0
        )
    except (TypeError, ValueError, OverflowError):
        provider_observed = 0.0

    out = {}
    for pair in pairs:
        base_currency, quote_currency = pair.split("/", 1)
        try:
            if base_currency == base:
                mid = float(rates[quote_currency])
            elif quote_currency == base:
                mid = 1 / float(rates[base_currency])
            else:
                mid = float(rates[quote_currency]) / float(rates[base_currency])
            if not math.isfinite(mid) or mid <= 0:
                continue
            spread_bps = _spread(pair)
            half = spread_bps / 20000
            out[pair] = {
                "pair": pair, "price": mid,
                "bid": mid * (1 - half), "ask": mid * (1 + half),
                "spread_bps": spread_bps, "observed": provider_observed,
                "fetched_at": now, "provider_date": provider_date,
                "source": "ECB reference rate via Frankfurter",
            }
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    if not out:
        raise ValueError("No usable FX rates were returned.")
    return {
        "observed": provider_observed, "fetched_at": now,
        "provider_date": provider_date,
        "source": "ECB reference rate via Frankfurter",
        "pairs": out, "market_open": None,
    }
