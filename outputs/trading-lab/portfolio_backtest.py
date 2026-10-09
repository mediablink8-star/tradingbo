"""Shared-capital multi-pair FX portfolio backtest for offline research.

Signals are supplied per pair. The engine aligns candles by timestamp,
allocates fixed USD notional per new position, enforces portfolio exposure,
position-count and optional currency-concentration limits, marks positions to
market, and applies deterministic stop/take-profit, age and daily-loss rules.
It never connects to a broker.
"""
from dataclasses import dataclass
import math
import statistics

from backtest import FXBacktester


@dataclass
class PortfolioPosition:
    pair: str
    side: str
    entry_time: float
    entry_price: float
    base_units: float


class MultiPairPortfolioBacktester:
    def __init__(
        self,
        starting_cash=10000.0,
        per_position_notional=1000.0,
        max_exposure=3000.0,
        max_positions=3,
        spread_bps=1.0,
        slippage_bps=0.5,
        max_daily_loss=None,
        stop_loss_pct=None,
        take_profit_pct=None,
        max_position_age=None,
        max_currency_exposure=None,
    ):
        self.starting_cash = float(starting_cash)
        self.per_position_notional = float(per_position_notional)
        self.max_exposure = float(max_exposure)
        self.max_positions = int(max_positions)
        self.spread_bps = float(spread_bps)
        self.slippage_bps = float(slippage_bps)
        self.max_daily_loss = None if max_daily_loss is None else float(max_daily_loss)
        self.stop_loss_pct = None if stop_loss_pct is None else float(stop_loss_pct)
        self.take_profit_pct = None if take_profit_pct is None else float(take_profit_pct)
        self.max_position_age = None if max_position_age is None else float(max_position_age)
        self.max_currency_exposure = (
            None if max_currency_exposure is None else float(max_currency_exposure)
        )
        if self.per_position_notional <= 0 or self.max_exposure < 0:
            raise ValueError("portfolio notionals must be positive")
        if self.max_positions < 1:
            raise ValueError("max_positions must be positive")

    def _engine(self, pair):
        return FXBacktester(
            starting_cash=self.starting_cash,
            spread_bps=self.spread_bps,
            slippage_bps=self.slippage_bps,
            notional=self.per_position_notional,
            pair=pair,
        )

    def _exec(self, price, side, opening):
        half = self.spread_bps / 20000
        slip = self.slippage_bps / 10000
        if opening:
            return price * (1 + half + slip) if side == "buy" else price * (1 - half - slip)
        return price * (1 - half - slip) if side == "buy" else price * (1 + half + slip)

    def _base_units(self, pair, price):
        base_to_usd, _ = self._engine(pair)._conversion_rates(0, price)
        return self.per_position_notional / base_to_usd

    def _pnl(self, position, price):
        direction = 1 if position.side == "buy" else -1
        quote_pnl = (price - position.entry_price) * direction * position.base_units
        _, quote_to_usd = self._engine(position.pair)._conversion_rates(position.entry_time, price)
        return quote_pnl * quote_to_usd

    def _currency_exposure(self, positions, marks):
        exposure = {}
        for position in positions.values():
            price = marks[position.pair]
            base, quote = position.pair.split("/", 1)
            direction = 1 if position.side == "buy" else -1
            base_to_usd, quote_to_usd = self._engine(position.pair)._conversion_rates(0, price)
            base_usd = position.base_units * base_to_usd * direction
            quote_usd = position.base_units * price * quote_to_usd * -direction
            exposure[base] = exposure.get(base, 0.0) + base_usd
            exposure[quote] = exposure.get(quote, 0.0) + quote_usd
        return exposure

    def _close(self, position, candle, cash, trades, timestamp, reason, price=None):
        # Signal exits fill at the next bar's open; risk/final exits default to close.
        reference_price = candle.close if price is None else price
        exit_price = self._exec(reference_price, position.side, False)
        pnl = self._pnl(position, exit_price)
        cash += pnl
        trades.append({
            "pair": position.pair,
            "side": position.side,
            "entry_time": position.entry_time,
            "entry_price": position.entry_price,
            "exit_time": timestamp,
            "exit_price": exit_price,
            "pnl": pnl,
            "reason": reason,
        })
        return cash, pnl

    def run(self, candles_by_pair, signals_by_pair):
        if not candles_by_pair:
            return {
                "starting_cash": self.starting_cash,
                "ending_cash": self.starting_cash,
                "return_pct": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
                "trades": [],
                "history": [],
            }
        if set(candles_by_pair) != set(signals_by_pair):
            raise ValueError("candles_by_pair and signals_by_pair must contain the same pairs")

        timeline = sorted({
            candle.timestamp
            for candles in candles_by_pair.values()
            for candle in candles
        })
        indexes = {pair: 0 for pair in candles_by_pair}
        latest = {}
        positions = {}
        cash = self.starting_cash
        trades = []
        history = []
        daily_realized = 0.0
        current_day = None
        halted_day = False

        for timestamp in timeline:
            day = math.floor(timestamp / 86400)
            if day != current_day:
                current_day = day
                daily_realized = 0.0
                halted_day = False

            current = {}
            for pair, candles in candles_by_pair.items():
                i = indexes[pair]
                while i < len(candles) and candles[i].timestamp <= timestamp:
                    latest[pair] = candles[i]
                    i += 1
                indexes[pair] = i
                if pair in latest and latest[pair].timestamp == timestamp:
                    current[pair] = latest[pair]

            for pair in sorted(current):
                candle = current[pair]
                # The current candle is excluded: its close is not known at its open.
                completed = candles_by_pair[pair][: indexes[pair] - 1]
                signal = signals_by_pair[pair](completed) if completed else None
                position = positions.get(pair)
                closed = False

                if position is not None:
                    age = timestamp - position.entry_time
                    move = (candle.close / position.entry_price - 1.0) * (
                        1 if position.side == "buy" else -1
                    )
                    reason = None
                    if self.stop_loss_pct is not None and move <= -self.stop_loss_pct:
                        reason = "stop_loss"
                    elif self.take_profit_pct is not None and move >= self.take_profit_pct:
                        reason = "take_profit"
                    elif self.max_position_age is not None and age >= self.max_position_age:
                        reason = "max_position_age"
                    elif signal in ("flat", "buy", "sell") and signal != position.side:
                        reason = "signal"
                    if reason:
                        cash, pnl = self._close(
                            position, candle, cash, trades, timestamp, reason,
                            price=candle.open if reason == "signal" else None,
                        )
                        daily_realized += pnl
                        del positions[pair]
                        position = None
                        closed = True
                        if daily_realized <= -(self.max_daily_loss or float("inf")):
                            halted_day = True

                if position is None and not closed and not halted_day and signal in ("buy", "sell"):
                    if len(positions) >= self.max_positions:
                        continue
                    if len(positions) * self.per_position_notional + self.per_position_notional > self.max_exposure:
                        continue
                    entry_price = self._exec(candle.open, signal, True)
                    candidate = PortfolioPosition(
                        pair=pair,
                        side=signal,
                        entry_time=timestamp,
                        entry_price=entry_price,
                        base_units=self._base_units(pair, candle.open),
                    )
                    if self.max_currency_exposure is not None:
                        # Current bars are executable at open; do not use their future closes.
                        marks = {
                            p: (current[p].open if p in current else latest[p].close)
                            for p in latest
                        }
                        marks[pair] = candle.open
                        proposed = dict(positions)
                        proposed[pair] = candidate
                        currency = self._currency_exposure(proposed, marks)
                        if max((abs(v) for v in currency.values()), default=0.0) > self.max_currency_exposure:
                            continue
                    positions[pair] = candidate

            equity = cash
            for pair, position in positions.items():
                equity += self._pnl(position, latest[pair].close)
            history.append({
                "timestamp": timestamp,
                "equity": equity,
                "cash": cash,
                "open_positions": len(positions),
                "exposure": len(positions) * self.per_position_notional,
                "currency_exposure": self._currency_exposure(
                    positions, {p: latest[p].close for p in positions}
                ) if positions else {},
                "daily_realized_pnl": daily_realized,
                "daily_loss_halted": halted_day,
            })

        if positions:
            final_timestamp = timeline[-1]
            for pair, position in list(positions.items()):
                candle = latest[pair]
                cash, pnl = self._close(position, candle, cash, trades, final_timestamp, "final")
                positions.pop(pair, None)
            history[-1]["equity"] = cash
            history[-1]["cash"] = cash
            history[-1]["open_positions"] = 0
            history[-1]["exposure"] = 0
            history[-1]["currency_exposure"] = {}

        peak = self.starting_cash
        max_dd = 0.0
        returns = []
        previous = self.starting_cash
        for row in history:
            peak = max(peak, row["equity"])
            max_dd = max(max_dd, peak - row["equity"])
            if previous:
                returns.append(row["equity"] / previous - 1.0)
            previous = row["equity"]

        sd = statistics.stdev(returns) if len(returns) > 1 else 0.0
        mean = statistics.mean(returns) if returns else 0.0
        if len(history) > 1:
            gaps = [
                b["timestamp"] - a["timestamp"]
                for a, b in zip(history, history[1:])
                if b["timestamp"] > a["timestamp"]
            ]
            annualization = 31536000.0 / statistics.median(gaps) if gaps else 252.0
        else:
            annualization = 252.0

        return {
            "starting_cash": self.starting_cash,
            "ending_cash": cash,
            "return_pct": (cash / self.starting_cash - 1.0) * 100.0,
            "max_drawdown": max_dd,
            "sharpe": mean / sd * math.sqrt(max(1.0, annualization)) if sd else 0.0,
            "trades": trades,
            "history": history,
        }
