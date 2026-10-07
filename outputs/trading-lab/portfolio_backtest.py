"""Shared-capital multi-pair FX portfolio backtest for offline research.

Signals are supplied per pair. The engine aligns candles by timestamp,
allocates a fixed USD notional per new position, enforces portfolio exposure
and position-count limits, marks open positions to market, and reports
portfolio-level equity and drawdown. It does not connect to brokers.
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
    ):
        self.starting_cash = float(starting_cash)
        self.per_position_notional = float(per_position_notional)
        self.max_exposure = float(max_exposure)
        self.max_positions = int(max_positions)
        self.spread_bps = float(spread_bps)
        self.slippage_bps = float(slippage_bps)

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
        _, quote_to_usd = self._engine(position.pair)._conversion_rates(
            position.entry_time, price
        )
        return quote_pnl * quote_to_usd

    def run(self, candles_by_pair, signals_by_pair):
        if not candles_by_pair:
            return {
                "starting_cash": self.starting_cash,
                "ending_cash": self.starting_cash,
                "return_pct": 0.0,
                "max_drawdown": 0.0,
                "trades": [],
                "history": [],
            }

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

        for timestamp in timeline:
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
                signal = signals_by_pair[pair](candles_by_pair[pair][:indexes[pair]])
                position = positions.get(pair)

                if position is not None:
                    exit_action = signal in ("flat", "buy", "sell") and signal != position.side
                    if exit_action:
                        exit_price = self._exec(candle.close, position.side, False)
                        pnl = self._pnl(position, exit_price)
                        cash += pnl
                        trades.append({
                            "pair": pair,
                            "side": position.side,
                            "entry_time": position.entry_time,
                            "entry_price": position.entry_price,
                            "exit_time": timestamp,
                            "exit_price": exit_price,
                            "pnl": pnl,
                        })
                        del positions[pair]
                        position = None

                if position is None and signal in ("buy", "sell"):
                    if len(positions) >= self.max_positions:
                        continue
                    current_exposure = len(positions) * self.per_position_notional
                    if current_exposure + self.per_position_notional > self.max_exposure:
                        continue
                    entry_price = self._exec(candle.close, signal, True)
                    positions[pair] = PortfolioPosition(
                        pair=pair,
                        side=signal,
                        entry_time=timestamp,
                        entry_price=entry_price,
                        base_units=self._base_units(pair, candle.close),
                    )

            equity = cash
            for pair, position in positions.items():
                mark = latest[pair].close
                equity += self._pnl(position, mark)

            history.append({
                "timestamp": timestamp,
                "equity": equity,
                "cash": cash,
                "open_positions": len(positions),
                "exposure": len(positions) * self.per_position_notional,
            })

        if positions:
            final_timestamp = timeline[-1]
            for pair, position in list(positions.items()):
                candle = latest[pair]
                exit_price = self._exec(candle.close, position.side, False)
                pnl = self._pnl(position, exit_price)
                cash += pnl
                trades.append({
                    "pair": pair,
                    "side": position.side,
                    "entry_time": position.entry_time,
                    "entry_price": position.entry_price,
                    "exit_time": final_timestamp,
                    "exit_price": exit_price,
                    "pnl": pnl,
                })
            positions.clear()
            history[-1]["equity"] = cash
            history[-1]["cash"] = cash
            history[-1]["open_positions"] = 0
            history[-1]["exposure"] = 0

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
        if history and len(history) > 1:
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
