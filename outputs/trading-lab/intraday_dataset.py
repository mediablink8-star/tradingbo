"""Reproducible multi-month intraday FX dataset pipeline.

Uses the intraday adapter to download one calendar month at a time, merges
months, removes exact timestamp duplicates at month boundaries, validates
ordering, and writes per-pair JSON plus a manifest. Research/data only.
"""
import datetime
import json
import os

from intraday import load_month, validate


def iter_months(start_month, end_month):
    start = datetime.date.fromisoformat(start_month + "-01")
    end = datetime.date.fromisoformat(end_month + "-01")
    if start > end:
        raise ValueError("start_month must not be after end_month")
    cur = start
    while cur <= end:
        yield cur.strftime("%Y-%m")
        if cur.month == 12:
            cur = datetime.date(cur.year + 1, 1, 1)
        else:
            cur = datetime.date(cur.year, cur.month + 1, 1)


def _interval_minutes(interval):
    return int(interval.replace("min", ""))


def merge_candles(candle_groups):
    by_timestamp = {}
    for candles in candle_groups:
        for candle in candles:
            by_timestamp[candle.timestamp] = candle
    return [by_timestamp[t] for t in sorted(by_timestamp)]


def build_dataset(
    pairs,
    start_month,
    end_month,
    output_dir,
    interval="15min",
):
    months = list(iter_months(start_month, end_month))
    os.makedirs(output_dir, exist_ok=True)
    manifest = {
        "provider": "alphavantage",
        "interval": interval,
        "start_month": start_month,
        "end_month": end_month,
        "months": months,
        "pairs": {},
    }

    for pair in pairs:
        groups = [load_month(pair, month, interval) for month in months]
        candles = merge_candles(groups)
        checks = validate(candles, _interval_minutes(interval))
        if checks["duplicates"] or checks["non_monotonic"]:
            raise ValueError(f"Invalid ordering/duplicates for {pair}: {checks}")

        name = pair.replace("/", "_") + f"_{interval}.json"
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([c.__dict__ for c in candles], f)

        manifest["pairs"][pair] = checks | {
            "file": name,
            "months_loaded": len(months),
        }

    with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
