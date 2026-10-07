"""True walk-forward parameter selection for deterministic FX strategies.

Each window uses only the training candles to select the best candidate
parameter set. The selected parameters are then evaluated once on the
following unseen test window. No future test candles influence selection.
"""
from backtest import FXBacktester


def _score(result, metric):
    value = result.get(metric)
    if value is None:
        return float("-inf")
    return float(value)


def optimize_window(train_candles, backtester, strategy_candidates, metric="sharpe"):
    if not train_candles:
        raise ValueError("train_candles must not be empty")
    if not strategy_candidates:
        raise ValueError("strategy_candidates must not be empty")
    scored = []
    for name, factory in strategy_candidates:
        result = backtester.run(train_candles, factory)
        scored.append({
            "name": name,
            "metric": metric,
            "score": _score(result, metric),
            "return_pct": result["return_pct"],
            "sharpe": result["sharpe"],
            "max_drawdown": result["max_drawdown"],
            "trades": len(result["trades"]),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[0], scored


def true_walk_forward(
    candles,
    backtester_factory,
    strategy_candidates,
    train_size=500,
    test_size=100,
    metric="sharpe",
):
    if train_size < 2 or test_size < 1:
        raise ValueError("train_size must be >= 2 and test_size >= 1")
    windows = []
    start = 0
    while start + train_size + test_size <= len(candles):
        train = candles[start:start + train_size]
        test = candles[start + train_size:start + train_size + test_size]
        trainer = backtester_factory()
        selected, ranking = optimize_window(
            train, trainer, strategy_candidates, metric
        )
        selected_factory = dict(strategy_candidates)[selected["name"]]
        tester = backtester_factory()
        oos = tester.run(test, selected_factory)
        windows.append({
            "train_start": train[0].timestamp,
            "train_end": train[-1].timestamp,
            "test_start": test[0].timestamp,
            "test_end": test[-1].timestamp,
            "selected_strategy": selected["name"],
            "selection_score": selected["score"],
            "train_ranking": ranking,
            "oos_return_pct": oos["return_pct"],
            "oos_sharpe": oos["sharpe"],
            "oos_max_drawdown": oos["max_drawdown"],
            "oos_profit_factor": oos["profit_factor"],
            "oos_expectancy": oos["expectancy"],
            "oos_trades": len(oos["trades"]),
        })
        start += test_size

    if not windows:
        raise ValueError("Not enough candles for one train/test window")

    profitable = sum(w["oos_return_pct"] > 0 for w in windows)
    return {
        "windows": windows,
        "window_count": len(windows),
        "profitable_oos_windows": profitable,
        "profitable_oos_pct": 100.0 * profitable / len(windows),
        "total_oos_return_pct": sum(w["oos_return_pct"] for w in windows),
        "average_oos_return_pct": sum(w["oos_return_pct"] for w in windows) / len(windows),
        "average_oos_sharpe": sum(w["oos_sharpe"] for w in windows) / len(windows),
    }
