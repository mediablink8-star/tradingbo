"""Deterministic FX backtesting engine with costs and mark-to-market metrics.

Account currency is USD. The built-in supported-pair conversion logic keeps
P/L and position sizing economically consistent for pairs containing USD.
"""

from dataclasses import dataclass
from typing import Callable
import math
import statistics


@dataclass(frozen=True)
class Candle:
    timestamp: float
    open: float
    high: float
    low: float
    close: float


@dataclass
class Trade:
    side: str
    entry_time: float
    entry_price: float
    exit_time: float
    exit_price: float
    pnl: float


def _usd_rates(pair, price):
    """Return (base->USD, quote->USD) for USD-containing major pairs."""
    base, quote = pair.upper().split("/", 1)
    if base == "USD":
        if price <= 0:
            raise ValueError("price must be positive")
        return 1.0, 1.0 / price
    if quote == "USD":
        return price, 1.0
    raise ValueError(
        f"No built-in USD conversion for {pair}; provide conversion callbacks"
    )


class FXBacktester:
    def __init__(
        self,
        starting_cash=10000.0,
        spread_bps=1.0,
        slippage_bps=0.5,
        notional=500.0,
        periods_per_year=None,
        pair="EUR/USD",
        base_to_usd: Callable[[float, float], float] | None = None,
        quote_to_usd: Callable[[float, float], float] | None = None,
    ):
        self.starting_cash = float(starting_cash)
        self.spread_bps = float(spread_bps)
        self.slippage_bps = float(slippage_bps)
        self.notional = float(notional)
        self.periods_per_year = periods_per_year
        self.pair = pair.upper()
        self.base_to_usd = base_to_usd
        self.quote_to_usd = quote_to_usd

    def _conversion_rates(self, timestamp, price):
        if self.base_to_usd and self.quote_to_usd:
            return (
                float(self.base_to_usd(timestamp, price)),
                float(self.quote_to_usd(timestamp, price)),
            )
        return _usd_rates(self.pair, price)

    def _exec(self, price, side, opening):
        half = self.spread_bps / 20000
        slip = self.slippage_bps / 10000
        if opening:
            return price * (1 + half + slip) if side == "buy" else price * (1 - half - slip)
        return price * (1 - half - slip) if side == "buy" else price * (1 + half + slip)

    def _pnl(self, position, price, timestamp):
        direction = 1 if position["side"] == "buy" else -1
        quote_pnl = (price - position["entry_price"]) * direction * position["base_units"]
        quote_to_usd = self._conversion_rates(timestamp, price)[1]
        return quote_pnl * quote_to_usd

    def _unrealized(self, position, mark, timestamp):
        if not position:
            return 0.0
        return self._pnl(position, mark, timestamp)

    def _annualization(self, candles):
        if self.periods_per_year is not None:
            return max(float(self.periods_per_year), 1.0)
        gaps = [
            b.timestamp - a.timestamp
            for a, b in zip(candles, candles[1:])
            if b.timestamp > a.timestamp
        ]
        if not gaps:
            return 252.0
        return max(1.0, 31536000.0 / statistics.median(gaps))

    def _position(self, side, candle):
        # A signal formed from completed candles can only fill at the next bar's open.
        entry_price = self._exec(candle.open, side, True)
        base_to_usd, _ = self._conversion_rates(candle.timestamp, candle.open)
        if base_to_usd <= 0 or entry_price <= 0:
            raise ValueError("invalid conversion or entry price")
        # Notional is expressed in account USD. Convert that USD amount to
        # base-currency units; entry price is not part of this conversion.
        base_units = self.notional / base_to_usd
        return {
            "side": side,
            "entry_time": candle.timestamp,
            "entry_price": entry_price,
            "base_units": base_units,
        }

    def run(self, candles: list[Candle], signal: Callable[[list[Candle]], str | None]):
        empty = {
            "starting_cash": self.starting_cash,
            "ending_cash": self.starting_cash,
            "return_pct": 0.0,
            "trades": [],
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "history": [],
        }
        if not candles:
            return empty

        cash = self.starting_cash
        position = None
        trades = []
        history = []

        pending_action = None
        for i, candle in enumerate(candles):
            # Execute only a signal computed after the previous candle closed.
            # Using this candle's close to both form and fill a signal leaks future data.
            action = pending_action
            if position is None and action in ("buy", "sell"):
                position = self._position(action, candle)
            elif position is not None and (
                action == ("sell" if position["side"] == "buy" else "buy")
                or action == "flat"
            ):
                exit_price = self._exec(candle.open, position["side"], False)
                pnl = self._pnl(position, exit_price, candle.timestamp)
                cash += pnl
                trades.append(
                    Trade(
                        position["side"],
                        position["entry_time"],
                        position["entry_price"],
                        candle.timestamp,
                        exit_price,
                        pnl,
                    )
                )
                position = None

            history.append(
                {
                    "timestamp": candle.timestamp,
                    "equity": cash + self._unrealized(position, candle.close, candle.timestamp),
                    "position": position["side"] if position else None,
                }
            )
            pending_action = signal(candles[: i + 1])

        if position is not None:
            candle = candles[-1]
            exit_price = self._exec(candle.close, position["side"], False)
            pnl = self._pnl(position, exit_price, candle.timestamp)
            cash += pnl
            trades.append(
                Trade(
                    position["side"],
                    position["entry_time"],
                    position["entry_price"],
                    candle.timestamp,
                    exit_price,
                    pnl,
                )
            )
            history[-1]["equity"] = cash

        wins = [t.pnl for t in trades if t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl < 0]
        returns = []
        prev = self.starting_cash
        for item in history:
            returns.append((item["equity"] / prev) - 1 if prev else 0)
            prev = item["equity"]

        mean = statistics.mean(returns) if returns else 0
        sd = statistics.stdev(returns) if len(returns) > 1 else 0
        sharpe = (mean / sd * math.sqrt(self._annualization(candles))) if sd else 0

        peak = self.starting_cash
        max_dd = 0
        for item in history:
            peak = max(peak, item["equity"])
            max_dd = max(max_dd, peak - item["equity"])

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss
            else (math.inf if gross_profit else 0)
        )
        expectancy = statistics.mean([t.pnl for t in trades]) if trades else 0

        return {
            "starting_cash": self.starting_cash,
            "ending_cash": cash,
            "return_pct": (cash / self.starting_cash - 1) * 100,
            "trades": [t.__dict__ for t in trades],
            "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "history": history,
        }
