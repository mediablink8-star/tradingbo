"""Joint portfolio-aware walk-forward evaluation for FX research.

Selection uses only chronological training data. The selected combination is
then evaluated on the next unseen OOS window with the same shared-capital
constraints. The final holdout is excluded from every selection decision.
"""
from portfolio_backtest import MultiPairPortfolioBacktester
import math
import statistics

from portfolio_selection import select_portfolio_strategies


def _align(candles_by_pair):
    pairs = sorted(candles_by_pair)
    common = None
    for pair in pairs:
        timestamps = {c.timestamp for c in candles_by_pair[pair]}
        common = timestamps if common is None else common & timestamps
    if not common:
        raise ValueError("pairs have no common timestamps")
    aligned = {}
    for pair in pairs:
        by_ts = {c.timestamp: c for c in candles_by_pair[pair]}
        aligned[pair] = [by_ts[ts] for ts in sorted(common)]
    return aligned


def portfolio_true_walk_forward(
    candles_by_pair,
    candidate_map,
    train_size=500,
    test_size=100,
    gap=0,
    starting_cash=10000.0,
    portfolio_backtester_factory=None,
    metric="sharpe",
    max_drawdown=None,
    min_return_pct=None,
    max_iterations=2,
    warmup_size=0,
):
    if train_size < 2 or test_size < 1 or gap < 0 or warmup_size < 0:
        raise ValueError("train_size >= 2, test_size >= 1, gap >= 0, warmup_size >= 0 required")
    aligned = _align(candles_by_pair)
    pairs = sorted(aligned)
    length = len(aligned[pairs[0]])
    if length < train_size + gap + test_size:
        raise ValueError("Not enough aligned candles for one train/test window")

    def factory(cash):
        if portfolio_backtester_factory is not None:
            return portfolio_backtester_factory(cash)
        return MultiPairPortfolioBacktester(starting_cash=cash)

    windows = []
    cash = float(starting_cash)
    start = 0
    while start + train_size + gap + test_size <= length:
        train = {pair: aligned[pair][start:start + train_size] for pair in pairs}
        test_start = start + train_size + gap
        test = {pair: aligned[pair][test_start:test_start + test_size] for pair in pairs}
        warmup_start = max(0, test_start - warmup_size)
        warmup = {pair: aligned[pair][warmup_start:test_start] for pair in pairs}
        combined = {pair: warmup[pair] + test[pair] for pair in pairs}
        selection = select_portfolio_strategies(
            train,
            candidate_map,
            metric=metric,
            max_drawdown=max_drawdown,
            min_return_pct=min_return_pct,
            max_iterations=max_iterations,
            portfolio_backtester_factory=lambda: factory(starting_cash),
        )
        selected = selection["selected"]
        signals = {
            pair: (dict(candidate_map[pair])[name]() if name != "__flat__" else (lambda history: "flat"))
            for pair, name in selected.items()
        }
        guarded_signals = {
            pair: (lambda signal=signals[pair], count=len(warmup[pair]):
                   (lambda history: None if len(history) <= count else signal(history)))()
            for pair in pairs
        }
        result = factory(cash).run(combined, guarded_signals)
        result["history"] = result["history"][len(next(iter(warmup.values()))):]
        equity_values = [float(row["equity"]) for row in result["history"]]
        returns = []
        previous_equity = cash
        for equity in equity_values:
            returns.append(equity / previous_equity - 1.0 if previous_equity > 0 else 0.0)
            previous_equity = equity
        deviation = statistics.stdev(returns) if len(returns) > 1 else 0.0
        periods = 252.0
        if len(test[pairs[0]]) > 1:
            gaps = [b.timestamp - a.timestamp for a, b in zip(test[pairs[0]], test[pairs[0]][1:]) if b.timestamp > a.timestamp]
            if gaps:
                periods = max(1.0, 31536000.0 / statistics.median(gaps))
        result["sharpe"] = statistics.mean(returns) / deviation * math.sqrt(periods) if deviation > 0 else 0.0
        windows.append({
            "train_start": aligned[pairs[0]][start].timestamp,
            "train_end": aligned[pairs[0]][start + train_size - 1].timestamp,
            "gap": gap,
            "test_start": aligned[pairs[0]][test_start].timestamp,
            "test_end": aligned[pairs[0]][test_start + test_size - 1].timestamp,
            "selected_strategies": selected,
            "selection_training": selection["training_result"],
            "selection_iterations": selection["iterations"],
            "oos_starting_cash": cash,
            "oos_ending_cash": result["ending_cash"],
            "oos_return_pct": result["return_pct"],
            "oos_sharpe": result["sharpe"],
            "oos_max_drawdown": result["max_drawdown"],
            "oos_trades": len(result["trades"]),
            "oos_trades_detail": result["trades"],
        })
        cash = result["ending_cash"]
        start += test_size

    profitable = sum(w["oos_return_pct"] > 0 for w in windows)
    return {
        "starting_cash": starting_cash,
        "ending_cash": cash,
        "compounded_oos_return_pct": (cash / starting_cash - 1.0) * 100.0,
        "profitable_oos_windows": profitable,
        "profitable_oos_pct": 100.0 * profitable / len(windows),
        "window_count": len(windows),
        "windows": windows,
    }
