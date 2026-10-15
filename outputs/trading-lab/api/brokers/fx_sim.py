"""FX simulation book until OANDA (or other) is connected."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FxSimBook:
    initial_cash: float = 10_000.0
    cash: float = 10_000.0
    positions: list[dict[str, Any]] = field(default_factory=list)
    realized_pnl: float = 0.0

    def equity(self, marks: dict[str, float] | None = None) -> float:
        marks = marks or {}
        eq = self.cash
        for p in self.positions:
            if p.get("status") != "OPEN":
                continue
            px = marks.get(p["pair"], p.get("entry_price", 0))
            units = float(p.get("units", 0))
            entry = float(p.get("entry_price", 0))
            eq += units * (px - entry)
        return eq

    def snapshot(self, marks: dict[str, float] | None = None) -> dict[str, Any]:
        open_pos = [p for p in self.positions if p.get("status") == "OPEN"]
        return {
            "broker": "fx_simulation",
            "cash": round(self.cash, 4),
            "equity": round(self.equity(marks), 4),
            "initial_cash": self.initial_cash,
            "realized_pnl": round(self.realized_pnl, 4),
            "open_positions_count": len(open_pos),
            "positions": open_pos,
        }


FX_BOOK = FxSimBook()
