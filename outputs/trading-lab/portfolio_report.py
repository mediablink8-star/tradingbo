"""Portfolio-level aggregation for offline FX research.

This module combines already-evaluated per-pair OOS windows without creating
cross-pair trading signals. It is a research summary only.
"""

import math
from collections import Counter


def aggregate_pair_reports(reports):
    if not reports:
        raise ValueError("reports must not be empty")

    pairs = sorted(reports)
    pair_summaries = {}
    for pair in pairs:
        wf = reports[pair]["walk_forward"]
        pair_summaries[pair] = {
            "compounded_oos_return_pct": wf["compounded_oos_return_pct"],
            "average_oos_sharpe": wf["average_oos_sharpe"],
            "worst_oos_drawdown": wf["worst_oos_drawdown"],
            "profitable_oos_pct": wf["profitable_oos_pct"],
            "window_count": wf["window_count"],
        }

    # Equal-weight the pair-level compounded returns rather than summing them.
    equal_weight_return = sum(
        v["compounded_oos_return_pct"] for v in pair_summaries.values()
    ) / len(pair_summaries)

    all_windows = []
    selections = Counter()
    for pair in pairs:
        for window in reports[pair]["windows"]:
            row = dict(window)
            row["pair"] = pair
            all_windows.append(row)
            selections[window["selected_strategy"]] += 1

    profitable = sum(float(w["oos_return_pct"]) > 0 for w in all_windows)
    compounded_all = math.prod(
        1.0 + float(w["oos_return_pct"]) / 100.0 for w in all_windows
    )

    return {
        "pair_count": len(pairs),
        "pairs": pair_summaries,
        "equal_weight_pair_return_pct": equal_weight_return,
        "all_window_compounded_return_pct": (compounded_all - 1.0) * 100.0,
        "all_window_profitable_pct": (
            100.0 * profitable / len(all_windows) if all_windows else 0.0
        ),
        "strategy_selection_frequency": dict(selections),
    }
