"""Deterministic FX risk controls."""
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class RiskConfig:
    starting_cash: float = 10000.0
    max_trade_notional: float = 1000.0
    max_exposure: float = 3000.0
    max_positions: int = 3
    max_daily_loss: float = 200.0
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.02
    max_position_age: float = 86400.0
    max_leverage: float = 1.0
    # Gross USD-equivalent exposure per currency, including both sides of
    # every pair. This is a conservative concentration proxy, not a claim
    # that a live statistical correlation matrix has been calculated.
    max_currency_exposure: float = 2000.0


class FXRisk:
    def __init__(self, config=None):
        self.config = config or RiskConfig()

    @staticmethod
    def _currency_legs(pair, side):
        if not isinstance(pair, str) or side not in ("buy", "sell"):
            raise ValueError("Invalid FX pair or side for currency risk.")
        parts = pair.upper().split("/")
        if len(parts) != 2 or any(len(currency) != 3 for currency in parts) or parts[0] == parts[1]:
            raise ValueError("Invalid FX pair for currency risk.")
        direction = 1.0 if side == "buy" else -1.0
        return ((parts[0], direction), (parts[1], -direction))

    def validate_currency_exposure(self, positions, pair, side, notional):
        """Cap gross currency-leg exposure to prevent concentrated USD bets."""
        limit = self.config.max_currency_exposure
        if not math.isfinite(limit) or limit <= 0:
            raise ValueError("Invalid maximum FX currency exposure configuration.")
        gross = {}
        for position in positions:
            # Broker rows use (id, pair, side, units, entry, opened, notional).
            open_pair, open_side, open_notional = position[1], position[2], float(position[6])
            if not math.isfinite(open_notional) or open_notional <= 0:
                raise ValueError("Invalid existing FX position notional.")
            for currency, _direction in self._currency_legs(open_pair, open_side):
                gross[currency] = gross.get(currency, 0.0) + open_notional
        for currency, _direction in self._currency_legs(pair, side):
            if gross.get(currency, 0.0) + notional > limit:
                raise ValueError(
                    f"Maximum FX currency concentration reached for {currency}."
                )

    def validate_entry(self, cash, exposure, positions, notional, pair=None, side=None):
        c = self.config
        if not math.isfinite(notional) or not 0 < notional <= c.max_trade_notional:
            raise ValueError("Trade exceeds the FX per-trade notional limit.")
        if len(positions) >= c.max_positions:
            raise ValueError("Maximum open FX positions reached.")
        if not math.isfinite(exposure) or exposure < 0 or exposure + notional > c.max_exposure:
            raise ValueError("Maximum FX exposure reached.")
        if not math.isfinite(cash) or cash < 0 or notional > cash * c.max_leverage:
            raise ValueError("Insufficient cash under the configured leverage limit.")
        if pair is not None or side is not None:
            self.validate_currency_exposure(positions, pair, side, notional)

    def validate_daily_loss(self, daily_pnl):
        if not math.isfinite(daily_pnl) or daily_pnl <= -self.config.max_daily_loss:
            raise ValueError("Daily FX loss limit reached; trading is halted.")

    def exits(self, p, price, now=None):
        now = time.time() if now is None else now
        change = (float(price) / float(p["entry_price"]) - 1) * (
            1 if p["side"] == "buy" else -1
        )
        c = self.config
        return (
            change <= -c.stop_loss_pct
            or change >= c.take_profit_pct
            or now - float(p["opened"]) >= c.max_position_age
        )
