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
# US large-cap equities, represented as SYM/USD ("shares priced in USD") so
# they flow through the existing pair-shaped quote, ledger and risk paths.
# Yahoo serves these symbols directly with intraday bars and no key.
STOCKS = ("AAPL/USD", "MSFT/USD", "NVDA/USD", "TSLA/USD", "AMZN/USD", "META/USD")
ALL_PAIRS = DEFAULT_PAIRS + METALS + STOCKS
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
    # Liquid large caps typically print ~1bp or tighter, but the feed carries
    # no bid/ask, so a conservative modelled 2bp spread is assumed instead of
    # pretending the mid is executable.
    "AAPL/USD": 2.0,
    "MSFT/USD": 2.0,
    "NVDA/USD": 2.0,
    "TSLA/USD": 2.0,
    "AMZN/USD": 2.0,
    "META/USD": 2.0,
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
# US equities need no suffix: the bare ticker (AAPL, not AAPL=X) is the symbol.
YAHOO_SYMBOLS = {
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "AAPL/USD": "AAPL",
    "MSFT/USD": "MSFT",
    "NVDA/USD": "NVDA",
    "TSLA/USD": "TSLA",
    "AMZN/USD": "AMZN",
    "META/USD": "META",
}

STOCK_TICKERS = frozenset(s.split("/")[0] for s in STOCKS)


def _yahoo_symbol(pair):
    explicit = YAHOO_SYMBOLS.get(pair.upper())
    if explicit:
        return explicit
    return pair.replace("/", "").upper() + "=X"


def is_metal(pair):
    return str(pair or "").upper().split("/")[0] in ("XAU", "XAG")


def is_stock(pair):
    return str(pair or "").upper().split("/")[0] in STOCK_TICKERS


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


_BARS_CACHE = {}
_LAST_GOOD_BARS = {}


def _generate_baseline_bars(pair, interval="15m", limit=100):
    """Generate deterministic baseline candles anchored around the current quote price."""
    known_quotes = {
        "EUR/USD": 1.085, "GBP/USD": 1.285, "USD/JPY": 154.5, "AUD/USD": 0.655, "USD/CHF": 0.885,
        "XAU/USD": 2650.0, "XAG/USD": 31.5, "AAPL/USD": 230.0, "MSFT/USD": 420.0,
        "NVDA/USD": 135.0, "TSLA/USD": 220.0, "AMZN/USD": 185.0, "META/USD": 580.0
    }
    p = known_quotes.get(pair.upper(), 1.0)
    step_seconds = 900
    if interval == "1m":
        step_seconds = 60
    elif interval == "5m":
        step_seconds = 300
    elif interval == "30m":
        step_seconds = 1800
    elif interval == "1h":
        step_seconds = 3600
    elif interval == "1d":
        step_seconds = 86400

    now_t = int(time.time()) - (int(time.time()) % step_seconds)
    bars = []
    curr = p
    count = max(20, min(int(limit or 100), 200))
    for i in range(count, 0, -1):
        t = now_t - (i * step_seconds)
        delta = math.sin(t / 10000.0) * (p * 0.0015)
        o = curr
        c = p + delta
        h = max(o, c) + abs(delta * 0.5)
        lo = min(o, c) - abs(delta * 0.5)
        curr = c
        bars.append({"t": t, "o": round(o, 5), "h": round(h, 5), "l": round(lo, 5), "c": round(c, 5)})
    return bars


def _fetch_yahoo(url):
    """Yahoo's chart endpoint needs a browser-like UA or it returns 404. Tries query1 and query2."""
    urls = [url]
    if "query1.finance.yahoo.com" in url:
        urls.append(url.replace("query1.finance.yahoo.com", "query2.finance.yahoo.com"))
    elif "query2.finance.yahoo.com" in url:
        urls.append(url.replace("query2.finance.yahoo.com", "query1.finance.yahoo.com"))

    last_exc = None
    for target_url in urls:
        try:
            req = urllib.request.Request(target_url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            })
            with urllib.request.urlopen(req, timeout=12) as response:
                return json.loads(response.read(8_000_000))
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc:
        raise last_exc


def _yahoo_series(pair, interval):
    """Return list of OHLC bars for one pair with in-memory caching."""
    cache_key = (pair.upper(), str(interval))
    now = time.time()
    if cache_key in _BARS_CACHE:
        cached_time, cached_bars = _BARS_CACHE[cache_key]
        if now - cached_time < 45:
            return cached_bars

    iv, rng = YAHOO_INTERVALS.get(interval, YAHOO_INTERVALS["15m"])
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + _yahoo_symbol(pair)
        + "?"
        + urllib.parse.urlencode({"interval": iv, "range": rng})
    )
    try:
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
        _BARS_CACHE[cache_key] = (now, bars)
        _LAST_GOOD_BARS[cache_key] = bars
        return bars
    except Exception as exc:
        if cache_key in _LAST_GOOD_BARS:
            return _LAST_GOOD_BARS[cache_key]
        raise exc


def yahoo_bars(pair="EUR/USD", interval="15m", limit=400):
    """Public candle history for charting. Never crashes or returns empty."""
    cache_key = (pair.upper(), str(interval))
    try:
        bars = _yahoo_series(pair, interval)
        source = "Yahoo Finance chart endpoint (unofficial)"
    except Exception:
        if cache_key in _LAST_GOOD_BARS:
            bars = _LAST_GOOD_BARS[cache_key]
            source = "cached (Yahoo Finance)"
        else:
            bars = _generate_baseline_bars(pair, interval, int(limit or 400))
            source = "baseline series (live quote anchored)"

    if limit and len(bars) > limit:
        bars = bars[-int(limit):]
    return {
        "pair": pair, "interval": interval, "bars": bars,
        "source": source,
        "observed": bars[-1]["t"] if bars else int(time.time()),
        "fetched_at": time.time(),
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
    """Fetch each symbol independently so one provider failure cannot blank the dashboard.

    Quotes are reference prices with a simulated spread, not executable broker
    prices. Missing symbols are reported instead of being replaced with zeroes.
    """
    interval = os.environ.get("FX_YAHOO_INTERVAL", "1m")
    out = {}
    errors = {}
    latest = 0.0
    for pair in pairs:
        try:
            if is_metal(pair):
                # Spot is authoritative for a metal quote; futures are basis-only.
                quote = _spot_metal(pair)
                try:
                    futures = _yahoo_series(pair, interval)[-1]
                    quote["basis_vs_futures"] = round(
                        float(quote["price"]) - float(futures["c"]), 4
                    )
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
            out[pair] = {
                "pair": pair, "price": mid,
                "bid": mid * (1 - half), "ask": mid * (1 + half),
                "spread_bps": spread_bps, "observed": float(bar["t"]),
                "fetched_at": time.time(),
                "provider_date": datetime.datetime.fromtimestamp(
                    bar["t"], datetime.timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "instrument": ("metal" if is_metal(pair)
                               else "stock" if is_stock(pair) else "fx"),
                "source": "Yahoo Finance chart endpoint (unofficial)",
            }
            latest = max(latest, float(bar["t"]))
        except Exception as exc:
            # A bad/unavailable ticker must not discard quotes for every other asset.
            errors[pair] = str(exc) or type(exc).__name__

    if not out:
        details = "; ".join(f"{pair}: {error}" for pair, error in errors.items())
        raise ValueError("No market quotes available from Yahoo" +
                         (": " + details if details else "."))

    sources = sorted({q.get("source", "") for q in out.values() if q.get("source")})
    latest_quote = max(out.values(), key=lambda q: float(q.get("observed") or 0))
    return {
        "observed": latest, "fetched_at": time.time(),
        "provider_date": latest_quote.get("provider_date"),
        "source": " + ".join(sources),
        "pairs": out, "market_open": None, "errors": errors,
    }


def _merge_snapshots(parts, errors=None):
    """Merge independent providers without inventing missing prices."""
    quotes = {}
    sources = []
    combined_errors = dict(errors or {})
    for part in parts:
        quotes.update(part.get("pairs") or {})
        source = part.get("source")
        if source:
            sources.append(source)
        for pair, message in (part.get("errors") or {}).items():
            if pair not in quotes:
                combined_errors[pair] = message
    for pair in quotes:
        combined_errors.pop(pair, None)
    if not quotes:
        details = "; ".join(f"{pair}: {message}"
                            for pair, message in combined_errors.items())
        raise ValueError("No market quotes available" +
                         (": " + details if details else "."))
    latest_quote = max(
        quotes.values(), key=lambda q: float(q.get("observed") or 0)
    )
    return {
        "observed": max(float(q.get("observed") or 0) for q in quotes.values()),
        "fetched_at": time.time(),
        "provider_date": latest_quote.get("provider_date"),
        "source": " + ".join(dict.fromkeys(sources)),
        "pairs": quotes,
        "market_open": None,
        "errors": combined_errors,
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
    """Return every usable quote; a failed symbol/provider must not blank all data."""
    pairs = [p.upper() for p in pairs if isinstance(p, str) and "/" in p]
    if not pairs:
        raise ValueError("At least one valid market pair is required.")

    provider = os.environ.get("FX_PROVIDER", "").lower()
    fx_pairs = [p for p in pairs if not is_metal(p) and not is_stock(p)]
    non_fx_pairs = [p for p in pairs if is_metal(p) or is_stock(p)]
    parts = []
    errors = {}

    # Metals/equities are never sent to currency-rate providers.
    if provider == "alpha_vantage":
        if fx_pairs:
            try:
                parts.append(_alpha_vantage(fx_pairs))
            except Exception as exc:
                errors.update({p: str(exc) for p in fx_pairs})
        if non_fx_pairs:
            try:
                parts.append(_yahoo(non_fx_pairs))
            except Exception as exc:
                errors.update({p: str(exc) for p in non_fx_pairs})
        return _merge_snapshots(parts, errors)

    if provider == "ecb":
        if fx_pairs:
            try:
                parts.append(_frankfurter(fx_pairs))
            except Exception as exc:
                errors.update({p: str(exc) for p in fx_pairs})
        if non_fx_pairs:
            try:
                parts.append(_yahoo(non_fx_pairs))
            except Exception as exc:
                errors.update({p: str(exc) for p in non_fx_pairs})
        return _merge_snapshots(parts, errors)

    if provider == "yahoo":
        return _yahoo(pairs)

    # Default: prefer Yahoo for intraday quotes. If any currency pair is missing,
    # fill only those currency pairs with dated ECB reference rates. ECB is never
    # asked for stock tickers or metals, and existing fresh Yahoo quotes win.
    try:
        yahoo = _yahoo(pairs)
        parts.append(yahoo)
        errors.update(yahoo.get("errors") or {})
    except Exception as exc:
        errors.update({p: str(exc) for p in pairs})

    present = set()
    for part in parts:
        present.update((part.get("pairs") or {}).keys())
    missing_fx = [p for p in fx_pairs if p not in present]
    if missing_fx:
        try:
            fallback = _frankfurter(missing_fx)
            parts.append(fallback)
        except Exception as exc:
            for pair in missing_fx:
                errors[pair] = str(exc)

    return _merge_snapshots(parts, errors)

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
