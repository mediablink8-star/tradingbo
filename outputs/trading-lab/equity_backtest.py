"""Long-only equity paper backtester with conservative, explicit trading costs.

Signals use completed candles and execute at the next candle's open. The engine
is research-only: it has no broker connection and does not model dividends,
splits, taxes, borrow, delistings, or exchange-specific order rules. Fractional
shares are assumed. Supply point-in-time data to avoid survivorship/look-ahead
bias; current ticker lists alone are not a valid historical universe.
"""
from dataclasses import dataclass
import math
import statistics

from backtest import Candle


@dataclass(frozen=True)
class EquityTrade:
    symbol: str
    side: str
    entry_time: float
    entry_price: float
    exit_time: float
    exit_price: float
    shares: float
    pnl: float
    entry_fee: float
    exit_fee: float
    reason: str


class EquityBacktester:
    """Single-symbol, cash-only, long-only stock backtester.

    spread_bps and slippage_bps apply adversely on each side. commission_bps
    is charged on each fill's executed notional. No leverage or shorting.
    """

    def __init__(
        self,
        starting_cash=10000.0,
        notional=1000.0,
        spread_bps=2.0,
        slippage_bps=2.0,
        commission_bps=0.0,
        periods_per_year=252.0,
        symbol="UNKNOWN",
    ):
        self.starting_cash = float(starting_cash)
        self.notional = float(notional)
        self.spread_bps = float(spread_bps)
        self.slippage_bps = float(slippage_bps)
        self.commission_bps = float(commission_bps)
        self.periods_per_year = float(periods_per_year)
        self.symbol = str(symbol).upper()
        values = (self.starting_cash, self.notional, self.spread_bps,
                  self.slippage_bps, self.commission_bps, self.periods_per_year)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("backtest parameters must be finite")
        if self.starting_cash <= 0 or self.notional <= 0 or self.notional > self.starting_cash:
            raise ValueError("require 0 < notional <= starting_cash")
        if min(self.spread_bps, self.slippage_bps, self.commission_bps) < 0:
            raise ValueError("trading costs must be non-negative")
        if self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")

    def _execution_price(self, reference, side):
        adjustment = self.spread_bps / 20000.0 + self.slippage_bps / 10000.0
        return reference * (1.0 + adjustment if side == "buy" else 1.0 - adjustment)

    def _fee(self, shares, price):
        return abs(shares * price) * self.commission_bps / 10000.0

    @staticmethod
    def _validate_candles(candles):
        previous = None
        for candle in candles:
            values = (candle.timestamp, candle.open, candle.high, candle.low, candle.close)
            if not all(math.isfinite(float(value)) for value in values):
                raise ValueError("candle values must be finite")
            if min(candle.open, candle.high, candle.low, candle.close) <= 0:
                raise ValueError("candle prices must be positive")
            if candle.high < max(candle.open, candle.close, candle.low):
                raise ValueError("invalid candle high")
            if candle.low > min(candle.open, candle.close, candle.high):
                raise ValueError("invalid candle low")
            if previous is not None and candle.timestamp <= previous:
                raise ValueError("candle timestamps must be strictly increasing")
            previous = candle.timestamp

    def run(self, candles: list[Candle], signal):
        self._validate_candles(candles)
        cash = self.starting_cash
        position = None
        pending_action = None
        trades = []
        history = []
        equity_values = []
        previous_equity = self.starting_cash

        for index, candle in enumerate(candles):
            action = pending_action
            if position is None and action == "buy":
                fill = self._execution_price(candle.open, "buy")
                shares = min(self.notional, cash) / fill
                cost = shares * fill
                fee = self._fee(shares, fill)
                if shares > 0 and cost + fee <= cash:
                    cash -= cost + fee
                    position = {
                        "entry_time": candle.timestamp,
                        "entry_price": fill,
                        "shares": shares,
                        "entry_fee": fee,
                    }
            elif position is not None and action in ("sell", "flat"):
                fill = self._execution_price(candle.open, "sell")
                proceeds = position["shares"] * fill
                exit_fee = self._fee(position["shares"], fill)
                cash += proceeds - exit_fee
                pnl = (fill - position["entry_price"]) * position["shares"] - position["entry_fee"] - exit_fee
                trades.append(EquityTrade(
                    self.symbol, "long", position["entry_time"], position["entry_price"],
                    candle.timestamp, fill, position["shares"], pnl,
                    position["entry_fee"], exit_fee, "signal",
                ).__dict__)
                position = None

            market_value = 0.0 if position is None else position["shares"] * candle.close
            equity = cash + market_value
            equity_values.append(equity)
            period_return = equity / previous_equity - 1.0 if previous_equity else 0.0
            history.append({
                "timestamp": candle.timestamp,
                "cash": cash,
                "equity": equity,
                "return_pct": (equity / self.starting_cash - 1.0) * 100.0,
                "period_return": period_return,
                "open_position": position is not None,
            })
            previous_equity = equity
            # This signal is formed only after the current candle is complete.
            pending_action = signal(candles[:index + 1])

        if position is not None and candles:
            last = candles[-1]
            fill = self._execution_price(last.close, "sell")
            proceeds = position["shares"] * fill
            exit_fee = self._fee(position["shares"], fill)
            cash += proceeds - exit_fee
            pnl = (fill - position["entry_price"]) * position["shares"] - position["entry_fee"] - exit_fee
            trades.append(EquityTrade(
                self.symbol, "long", position["entry_time"], position["entry_price"],
                last.timestamp, fill, position["shares"], pnl,
                position["entry_fee"], exit_fee, "end_of_data",
            ).__dict__)
            if history:
                history[-1]["cash"] = cash
                history[-1]["equity"] = cash
                history[-1]["return_pct"] = (cash / self.starting_cash - 1.0) * 100.0
                history[-1]["open_position"] = False
                equity_values[-1] = cash

        ending = cash if not position else cash + position["shares"] * candles[-1].close
        returns = [row["period_return"] for row in history if math.isfinite(row["period_return"])]
        stdev = statistics.stdev(returns) if len(returns) > 1 else 0.0
        sharpe = (statistics.mean(returns) / stdev * math.sqrt(self.periods_per_year)
                  if stdev > 0 else 0.0)
        peak = self.starting_cash
        max_drawdown = 0.0
        for value in equity_values:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
        pnls = [trade["pnl"] for trade in trades]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]
        gross_profit, gross_loss = sum(wins), abs(sum(losses))
        return {
            "symbol": self.symbol,
            "starting_cash": self.starting_cash,
            "ending_cash": ending,
            "return_pct": (ending / self.starting_cash - 1.0) * 100.0,
            "trades": trades,
            "win_rate": len(wins) / len(pnls) if pnls else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0),
            "expectancy": statistics.mean(pnls) if pnls else 0.0,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "history": history,
        }
