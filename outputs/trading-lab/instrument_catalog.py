"""Canonical supported instrument catalog and executable quote validation."""
from __future__ import annotations
from dataclasses import dataclass
import math
import time
from typing import Any, Mapping, Optional

@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_class: str
    base_currency: str
    quote_currency: str
    quantity_unit: str
    trading_session: str
    supported_order_types: tuple[str, ...]
    ibkr_contract_required: bool = True
    tick_size: Optional[float] = None  # Resolve from IBKR contract details.

_FX = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF")
def _fx(s):
    b, q = s.split("/")
    return Instrument(s, "fx", b, q, "base_currency_units", "FX_WEEKDAY", ("MKT", "LMT"))
def _stock(s):
    b, q = s.split("/")
    return Instrument(s, "stock", b, q, "shares", "US_EQUITIES", ("MKT", "LMT"))
INSTRUMENTS = {s: _fx(s) for s in _FX}
SUPPORTED_SYMBOLS = tuple(INSTRUMENTS)

def get_instrument(symbol: str) -> Instrument:
    normalized = str(symbol or "").strip().upper()
    try:
        return INSTRUMENTS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported instrument: {normalized or '(empty)'}") from exc

def validate_executable_quote(symbol: str, quote: Mapping[str, Any], *,
                              now: Optional[float] = None,
                              max_age_seconds: float = 5.0) -> dict[str, Any]:
    """Reject all but fresh, correctly identified, executable IBKR quotes."""
    instrument = get_instrument(symbol)
    if not isinstance(quote, Mapping):
        raise ValueError("Quote must be an object")
    if str(quote.get("source") or "").strip().lower() != "ibkr":
        raise ValueError("Live entry requires a quote sourced directly from IBKR")
    if quote.get("executable") is not True:
        raise ValueError("Quote is not marked executable")
    if str(quote.get("symbol") or quote.get("pair") or "").strip().upper() != instrument.symbol:
        raise ValueError("Quote instrument does not match the requested symbol")
    contract_id = quote.get("contract_id")
    if contract_id in (None, "", 0, "0"):
        raise ValueError("IBKR contract identity is required")
    try:
        bid, ask, observed = float(quote["bid"]), float(quote["ask"]), float(quote["observed"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Quote requires numeric bid, ask, and observed timestamp") from exc
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask, observed)):
        raise ValueError("Quote values must be finite and positive")
    if bid > ask:
        raise ValueError("Crossed bid/ask quote rejected")
    stamp = time.time() if now is None else float(now)
    if not math.isfinite(stamp) or not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
        raise ValueError("Invalid quote freshness policy")
    age = stamp - observed
    if age < 0 or age > max_age_seconds:
        raise ValueError("IBKR quote is stale or from the future")
    return {"symbol": instrument.symbol, "asset_class": instrument.asset_class,
            "bid": bid, "ask": ask, "observed": observed,
            "age_seconds": age, "source": "ibkr", "contract_id": contract_id,
            "executable": True}
