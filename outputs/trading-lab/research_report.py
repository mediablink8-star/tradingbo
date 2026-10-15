"""Research-only reporting helpers for deterministic FX walk-forward studies."""

from collections import Counter


def summarize_walk_forward(result):
    windows = result.get("windows", [])
    if not windows:
        raise ValueError("walk-forward result must contain windows")

    returns = [float(w["oos_return_pct"]) for w in windows]
    sharpes = [float(w["oos_sharpe"]) for w in windows]
    drawdowns = [float(w["oos_max_drawdown"]) for w in windows]
    strategies = Counter(w["selected_strategy"] for w in windows)
    compounded = 1.0
    for value in returns:
        compounded *= 1.0 + value / 100.0

    return {
        "window_count": len(windows),
        "profitable_oos_windows": sum(v > 0 for v in returns),
        "profitable_oos_pct": 100.0 * sum(v > 0 for v in returns) / len(returns),
        "compounded_oos_return_pct": (compounded - 1.0) * 100.0,
        "sum_oos_return_pct": sum(returns),
        "average_oos_return_pct": sum(returns) / len(returns),
        "average_oos_sharpe": sum(sharpes) / len(sharpes),
        "worst_oos_drawdown": max(drawdowns),
        "strategy_selection_frequency": dict(strategies),
    }


def build_research_report(pair, walk_forward_result, holdout=None):
    report = {
        "pair": pair,
        "walk_forward": summarize_walk_forward(walk_forward_result),
        "windows": walk_forward_result["windows"],
    }
    if holdout is not None:
        report["final_holdout"] = holdout
    return report
