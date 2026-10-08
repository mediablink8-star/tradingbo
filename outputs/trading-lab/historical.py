"""Historical daily FX reference-rate loader for offline research.

The source is Frankfurter's provider-pinned ECB reference-rate series. The API
returns one quote per row, so cross rates are reconstructed by date. These are
daily reference/mid rates, not executable intraday prices.
"""
from dataclasses import dataclass
import datetime
import json
import math
import os
import urllib.parse
import urllib.request

from backtest import Candle

DEFAULT_PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF")


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TradingLab-FX/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read(2_000_000))


def _date_ts(value):
    return datetime.datetime.fromisoformat(value).replace(
        tzinfo=datetime.timezone.utc
    ).timestamp()


def load_daily(pair, start_date, end_date=None, provider="ecb"):
    pair = pair.upper()
    base, quote = pair.split("/", 1)
    if not start_date:
        raise ValueError("start_date is required")
    end_date = end_date or datetime.date.today().isoformat()
    currencies = {base, quote, "EUR"}
    url = "https://api.frankfurter.dev/v2/rates?" + urllib.parse.urlencode({
        "from": start_date,
        "to": end_date,
        "base": "EUR",
        "quotes": ",".join(sorted(c for c in currencies if c != "EUR")),
        "providers": provider,
    })
    rows = _fetch(url)
    by_date = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("date"):
            continue
        value = row.get("rate")
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            continue
        quote_currency = row.get("quote")
        if quote_currency:
            by_date.setdefault(row["date"], {})[quote_currency.upper()] = float(value)
        else:
            # Backward-compatible handling for older pivot-style fixtures.
            for currency in currencies:
                if currency != "EUR" and currency in row:
                    by_date.setdefault(row["date"], {})[currency] = float(row[currency])

    candles = []
    for date, rates in sorted(by_date.items()):
        if base == "EUR":
            if quote == "EUR":
                mid = 1.0
            else:
                mid = rates.get(quote)
        elif quote == "EUR":
            base_rate = rates.get(base)
            mid = 1.0 / base_rate if base_rate else None
        else:
            base_rate = rates.get(base)
            quote_rate = rates.get(quote)
            mid = quote_rate / base_rate if base_rate and quote_rate else None
        if mid is None or not math.isfinite(mid) or mid <= 0:
            continue
        ts = _date_ts(date)
        candles.append(Candle(ts, mid, mid, mid, mid))

    if not candles:
        raise ValueError(f"No historical FX data for {pair}.")
    return candles


def load_pairs(pairs, start_date, end_date=None, provider="ecb"):
    return {pair.upper(): load_daily(pair, start_date, end_date, provider) for pair in pairs}


def save_json(candles, path):
    payload = [c.__dict__ for c in candles]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    return [
        Candle(float(row["timestamp"]), float(row["open"]), float(row["high"]),
               float(row["low"]), float(row["close"]))
        for row in rows
    ]
