"""Joint portfolio-aware walk-forward evaluation for FX research.

Selection uses only chronological training data. The selected combination is
then evaluated on the next unseen OOS window with the same shared-capital
constraints. The final holdout is excluded from every selection decision.
"""
from portfolio_backtest import MultiPairPortfolioBacktester
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
):
    if train_size < 2 or test_size < 1 or gap < 0:
        raise ValueError("train_size >= 2, test_size >= 1, gap >= 0 required")
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
        test = {
            pair: aligned[pair][test_start:test_start + test_size]
            for pair in pairs
        }
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
            pair: dict(candidate_map[pair])[name]()
            for pair, name in selected.items()
        }
        result = factory(cash).run(test, signals)
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
