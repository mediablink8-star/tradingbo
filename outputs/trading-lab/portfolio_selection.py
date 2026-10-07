"""Greedy coordinate-descent portfolio strategy selection for offline research.

The selector evaluates candidate combinations under the same shared-capital
constraints as the portfolio backtester. It only sees the supplied training
slice and never the holdout.
"""

from portfolio_backtest import MultiPairPortfolioBacktester


def _score(result, metric):
    value = result.get(metric)
    if value is None:
        return float("-inf")
    return float(value)


def select_portfolio_strategies(
    candles_by_pair,
    candidate_map,
    train_size=None,
    metric="sharpe",
    max_drawdown=None,
    min_return_pct=None,
    max_iterations=2,
):
    if not candles_by_pair:
        raise ValueError("candles_by_pair must not be empty")
    if not candidate_map:
        raise ValueError("candidate_map must not be empty")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    pairs = sorted(candles_by_pair)
    training = {}
    for pair in pairs:
        candles = candles_by_pair[pair]
        if train_size is not None:
            if train_size < 2 or len(candles) < train_size:
                raise ValueError("train_size exceeds available candles")
            training[pair] = candles[-train_size:]
        else:
            training[pair] = candles

    selected = {pair: ("__flat__", lambda history: "flat") for pair in pairs}

    def evaluate():
        factories = {
            pair: selected[pair][1]
            for pair in pairs
        }
        return MultiPairPortfolioBacktester().run(
            training, {pair: factory() for pair, factory in factories.items()}
        )

    for _ in range(max_iterations):
        changed = False
        for pair in pairs:
            baseline = selected[pair]
            best = baseline
            best_result = evaluate()
            for name, factory in candidate_map[pair]:
                selected[pair] = (name, factory)
                result = evaluate()
                if max_drawdown is not None and result["max_drawdown"] > max_drawdown:
                    continue
                if min_return_pct is not None and result["return_pct"] < min_return_pct:
                    continue
                if _score(result, metric) > _score(best_result, metric):
                    best = (name, factory)
                    best_result = result
            selected[pair] = best
            if best[0] != baseline[0]:
                changed = True
        if not changed:
            break

    final_result = evaluate()
    return {
        "selected": {pair: selected[pair][0] for pair in pairs},
        "training_result": final_result,
        "iterations": max_iterations,
    }
