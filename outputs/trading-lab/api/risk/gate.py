"""Hard risk authority — ARM/DISARM + size/loss limits. Agents never bypass this."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    sized_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskGate:
    max_per_trade_usd: float = 12.0
    max_daily_loss_usd: float = 25.0
    max_open_positions: int = 2
    max_exposure_usd: float = 30.0
    arm_ttl_hours: float = 24.0

    armed: bool = False
    armed_until: float = 0.0
    daily_realized_loss_usd: float = 0.0
    open_positions: int = 0
    open_exposure_usd: float = 0.0
    day_key: str = ""

    def _roll_day(self) -> None:
        key = time.strftime("%Y-%m-%d", time.gmtime())
        if key != self.day_key:
            self.day_key = key
            self.daily_realized_loss_usd = 0.0

    def arm(self, hours: Optional[float] = None) -> dict[str, Any]:
        self._roll_day()
        ttl = hours if hours is not None else self.arm_ttl_hours
        self.armed = True
        self.armed_until = time.time() + ttl * 3600.0
        return self.status()

    def disarm(self) -> dict[str, Any]:
        self.armed = False
        self.armed_until = 0.0
        return self.status()

    def status(self) -> dict[str, Any]:
        self._roll_day()
        now = time.time()
        if self.armed and self.armed_until and now > self.armed_until:
            self.armed = False
        return {
            "armed": self.armed,
            "armed_until": self.armed_until or None,
            "seconds_remaining": max(0, int(self.armed_until - now)) if self.armed else 0,
            "daily_realized_loss_usd": round(self.daily_realized_loss_usd, 4),
            "open_positions": self.open_positions,
            "open_exposure_usd": round(self.open_exposure_usd, 4),
            "limits": {
                "max_per_trade_usd": self.max_per_trade_usd,
                "max_daily_loss_usd": self.max_daily_loss_usd,
                "max_open_positions": self.max_open_positions,
                "max_exposure_usd": self.max_exposure_usd,
                "arm_ttl_hours": self.arm_ttl_hours,
            },
        }

    def check_order(self, notional_usd: float, side: str = "buy") -> RiskDecision:
        self._roll_day()
        if not self.armed:
            return RiskDecision(False, "DISARMED — arm the bot before any new order")
        if self.armed_until and time.time() > self.armed_until:
            self.armed = False
            return RiskDecision(False, "ARM expired — re-arm required")
        if self.daily_realized_loss_usd >= self.max_daily_loss_usd:
            return RiskDecision(False, f"daily loss limit hit ({self.daily_realized_loss_usd:.2f})")
        if self.open_positions >= self.max_open_positions and side.lower() in ("buy", "long"):
            return RiskDecision(False, f"max open positions ({self.max_open_positions})")
        sized = min(float(notional_usd), self.max_per_trade_usd)
        if sized <= 0:
            return RiskDecision(False, "notional must be > 0")
        if side.lower() in ("buy", "long") and self.open_exposure_usd + sized > self.max_exposure_usd:
            room = max(0.0, self.max_exposure_usd - self.open_exposure_usd)
            if room < 1.0:
                return RiskDecision(False, "max exposure reached")
            sized = min(sized, room)
        return RiskDecision(True, "ok", sized_usd=round(sized, 4))

    def record_fill(self, side: str, notional_usd: float, realized_pnl: float = 0.0) -> None:
        self._roll_day()
        if side.lower() in ("buy", "long"):
            self.open_positions += 1
            self.open_exposure_usd += abs(notional_usd)
        elif side.lower() in ("sell", "close", "short"):
            self.open_positions = max(0, self.open_positions - 1)
            self.open_exposure_usd = max(0.0, self.open_exposure_usd - abs(notional_usd))
        if realized_pnl < 0:
            self.daily_realized_loss_usd += abs(realized_pnl)


GATE = RiskGate()
