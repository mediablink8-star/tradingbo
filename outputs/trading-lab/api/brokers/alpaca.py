"""Alpaca paper trading client (stocks/ETFs)."""
from __future__ import annotations

from typing import Any

import httpx

from config import Settings


class AlpacaPaper:
    def __init__(self, settings: Settings):
        self.base = settings.alpaca_base_url.rstrip("/")
        self.key = settings.alpaca_api_key
        self.secret = settings.alpaca_secret_key

    @property
    def configured(self) -> bool:
        return bool(self.key and self.secret)

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json",
        }

    async def account(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "configured": False,
                "error": "Set ALPACA_API_KEY and ALPACA_SECRET_KEY",
            }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base}/v2/account", headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return {
                "configured": True,
                "broker": "alpaca_paper",
                "equity": float(data.get("equity", 0)),
                "cash": float(data.get("cash", 0)),
                "buying_power": float(data.get("buying_power", 0)),
                "status": data.get("status"),
                "currency": data.get("currency", "USD"),
                "pattern_day_trader": data.get("pattern_day_trader"),
            }

    async def positions(self) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base}/v2/positions", headers=self._headers())
            r.raise_for_status()
            out = []
            for p in r.json():
                out.append(
                    {
                        "symbol": p.get("symbol"),
                        "qty": float(p.get("qty", 0)),
                        "side": p.get("side"),
                        "entry_price": float(p.get("avg_entry_price", 0)),
                        "current_price": float(p.get("current_price", 0) or 0),
                        "unrealized_pnl": float(p.get("unrealized_pl", 0) or 0),
                        "market_value": float(p.get("market_value", 0) or 0),
                        "status": "OPEN",
                    }
                )
            return out

    async def submit_market_order(
        self, symbol: str, notional: float, side: str = "buy"
    ) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Alpaca not configured"}
        payload = {
            "symbol": symbol.upper(),
            "notional": str(round(notional, 2)),
            "side": side.lower(),
            "type": "market",
            "time_in_force": "day",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"{self.base}/v2/orders", headers=self._headers(), json=payload
            )
            body = r.json() if r.content else {}
            if r.status_code >= 400:
                return {"ok": False, "error": body, "status": r.status_code}
            return {"ok": True, "order": body}
