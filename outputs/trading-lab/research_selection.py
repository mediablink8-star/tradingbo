"""Research-only parameter grid and holdout evaluation helpers.

These utilities keep parameter selection inside chronological training data,
apply minimum-quality constraints, and reserve a final untouched holdout for
a single final evaluation.
"""


def grid_candidates(prefix, factory_builder, parameter_grid):
    if not parameter_grid:
        raise ValueError("parameter_grid must not be empty")
    keys = list(parameter_grid)
    candidates = []

    def walk(i, params):
        if i == len(keys):
            frozen = dict(params)
            name = prefix + "(" + ",".join(f"{k}={frozen[k]}" for k in keys) + ")"
            candidates.append((name, lambda p=frozen: factory_builder(**p)))
            return
        key = keys[i]
        values = parameter_grid[key]
        if not values:
            raise ValueError(f"parameter grid for {key} is empty")
        for value in values:
            params[key] = value
            walk(i + 1, params)
        params.pop(key)

    walk(0, {})
    return candidates


def filter_candidates(
    scored,
    min_trades=1,
    max_drawdown=None,
    min_return_pct=None,
):
    kept = []
    for item in scored:
        if item["trades"] < min_trades:
            continue
        if max_drawdown is not None and item["max_drawdown"] > max_drawdown:
            continue
        if min_return_pct is not None and item["return_pct"] < min_return_pct:
            continue
        kept.append(item)
    return kept


def select_candidate(
    scored,
    metric="sharpe",
    min_trades=1,
    max_drawdown=None,
    min_return_pct=None,
):
    eligible = filter_candidates(
        scored, min_trades=min_trades,
        max_drawdown=max_drawdown,
        min_return_pct=min_return_pct,
    )
    if not eligible:
        return None
    return max(eligible, key=lambda x: float(x.get(metric, float("-inf"))))


def final_holdout(candles, backtester, factory, train_size, holdout_size):
    if train_size < 1 or holdout_size < 1:
        raise ValueError("train_size and holdout_size must be positive")
    if train_size + holdout_size > len(candles):
        raise ValueError("Not enough candles for final holdout")
    holdout = candles[-holdout_size:]
    result = backtester.run(holdout, factory)
    return {
        "holdout_start": holdout[0].timestamp,
        "holdout_end": holdout[-1].timestamp,
        "return_pct": result["return_pct"],
        "sharpe": result["sharpe"],
        "max_drawdown": result["max_drawdown"],
        "profit_factor": result["profit_factor"],
        "expectancy": result["expectancy"],
        "trades": len(result["trades"]),
    }
