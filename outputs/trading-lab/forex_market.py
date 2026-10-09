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
DEFAULT_SPREAD_BPS = {
    "EUR/USD": 1.0,
    "GBP/USD": 1.2,
    "USD/JPY": 1.0,
    "AUD/USD": 1.4,
    "USD/CHF": 1.4,
}


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
    if os.environ.get("FX_PROVIDER", "").lower() == "alpha_vantage":
        return _alpha_vantage(pairs)

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
