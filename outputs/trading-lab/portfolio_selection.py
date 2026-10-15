"""Portfolio-aware strategy selection for offline FX research.

Selection only sees the supplied training data. The same backtester factory can
be used for training and holdout evaluation so capital/risk assumptions cannot
silently change between selection and evaluation.
"""
from portfolio_backtest import MultiPairPortfolioBacktester


def _score(result, metric):
    value = result.get(metric)
    return float(value) if value is not None else float("-inf")


def select_portfolio_strategies(
    candles_by_pair,
    candidate_map,
    train_size=None,
    metric="sharpe",
    max_drawdown=None,
    min_return_pct=None,
    max_iterations=2,
    portfolio_backtester_factory=None,
):
    if not candles_by_pair:
        raise ValueError("candles_by_pair must not be empty")
    if not candidate_map:
        raise ValueError("candidate_map must not be empty")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    pairs = sorted(candles_by_pair)
    missing = [pair for pair in pairs if pair not in candidate_map]
    if missing:
        raise ValueError(f"Missing candidates for pairs: {missing}")

    training = {}
    for pair in pairs:
        candles = candles_by_pair[pair]
        if train_size is not None:
            if train_size < 2 or len(candles) < train_size:
                raise ValueError("train_size exceeds available candles")
            training[pair] = candles[-train_size:]
        else:
            training[pair] = candles

    factory = portfolio_backtester_factory or MultiPairPortfolioBacktester

    def run(selected):
        signals = {
            pair: selected[pair][1]()
            for pair in pairs
        }
        return factory().run(training, signals)

    selected = {
        pair: ("__flat__", lambda: (lambda history: "flat"))
        for pair in pairs
    }

    def allowed(result):
        if max_drawdown is not None and result["max_drawdown"] > max_drawdown:
            return False
        if min_return_pct is not None and result["return_pct"] < min_return_pct:
            return False
        return True

    completed_iterations = 0
    for _ in range(max_iterations):
        changed = False
        completed_iterations += 1
        for pair in pairs:
            baseline = selected[pair]
            baseline_result = run(selected)
            best = baseline
            best_result = baseline_result if allowed(baseline_result) else None

            for name, candidate_factory in sorted(
                candidate_map[pair], key=lambda item: item[0]
            ):
                selected[pair] = (name, candidate_factory)
                result = run(selected)
                if not allowed(result):
                    continue
                if best_result is None or _score(result, metric) > _score(best_result, metric):
                    best = (name, candidate_factory)
                    best_result = result

            selected[pair] = best
            if best[0] != baseline[0]:
                changed = True

        if not changed:
            break

    final_result = run(selected)
    if not allowed(final_result):
        # A constrained search must still return a valid deterministic baseline.
        selected = {
            pair: ("__flat__", lambda: (lambda history: "flat"))
            for pair in pairs
        }
        final_result = run(selected)

    return {
        "selected": {pair: selected[pair][0] for pair in pairs},
        "training_result": final_result,
        "iterations": completed_iterations,
    }
