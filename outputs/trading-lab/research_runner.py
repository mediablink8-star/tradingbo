"""Reproducible offline FX research runner.

Loads previously-built historical datasets, performs constrained rolling
walk-forward selection, then evaluates the final selected candidate on an
isolated final holdout. It never connects to a broker or executes trades.
"""

import argparse
import json
import os

from backtest import FXBacktester
from historical import load_json
from research_report import build_research_report
from strategies import default_strategy_candidates
from true_walkforward import optimize_window, true_walk_forward


DEFAULT_PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF")


def _pair_file(dataset_dir, pair):
    return os.path.join(dataset_dir, pair.replace("/", "_") + ".json")


def run_pair(
    pair,
    candles,
    train_size=500,
    test_size=100,
    gap=0,
    holdout_size=100,
    metric="sharpe",
    min_trades=1,
    max_drawdown=None,
    min_return_pct=None,
):
    if holdout_size >= len(candles):
        raise ValueError("holdout_size must leave data for walk-forward evaluation")

    pre_holdout = candles[:-holdout_size]
    holdout = candles[-holdout_size:]
    candidates = default_strategy_candidates()

    def backtester_factory():
        return FXBacktester(pair=pair, spread_bps=1.0, slippage_bps=0.5, notional=500)

    wf = true_walk_forward(
        pre_holdout,
        backtester_factory,
        candidates,
        train_size=train_size,
        test_size=test_size,
        gap=gap,
        metric=metric,
        min_trades=min_trades,
        max_drawdown=max_drawdown,
        min_return_pct=min_return_pct,
    )

    selected, ranking = optimize_window(
        pre_holdout,
        backtester_factory(),
        candidates,
        metric=metric,
        min_trades=min_trades,
        max_drawdown=max_drawdown,
        min_return_pct=min_return_pct,
    )
    holdout_result = backtester_factory().run(
        holdout,
        dict(candidates)[selected["name"]](),
    )
    holdout_report = {
        "selected_strategy": selected["name"],
        "selection_score": selected["score"],
        "pre_holdout_ranking": ranking,
        "holdout_start": holdout[0].timestamp,
        "holdout_end": holdout[-1].timestamp,
        "return_pct": holdout_result["return_pct"],
        "sharpe": holdout_result["sharpe"],
        "max_drawdown": holdout_result["max_drawdown"],
        "profit_factor": holdout_result["profit_factor"],
        "expectancy": holdout_result["expectancy"],
        "trades": len(holdout_result["trades"]),
    }
    return build_research_report(pair, wf, holdout_report)


def run_dataset(dataset_dir, pairs=DEFAULT_PAIRS, **kwargs):
    reports = {}
    for pair in pairs:
        path = _pair_file(dataset_dir, pair)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        candles = load_json(path)
        reports[pair] = run_pair(pair, candles, **kwargs)
    return {
        "dataset_dir": dataset_dir,
        "pairs": reports,
    }


def main():
    parser = argparse.ArgumentParser(description="Run offline FX walk-forward research")
    parser.add_argument("dataset_dir")
    parser.add_argument("--output", default="research-report.json")
    parser.add_argument("--pairs", nargs="+", default=list(DEFAULT_PAIRS))
    parser.add_argument("--train-size", type=int, default=500)
    parser.add_argument("--test-size", type=int, default=100)
    parser.add_argument("--gap", type=int, default=0)
    parser.add_argument("--holdout-size", type=int, default=100)
    parser.add_argument("--metric", default="sharpe")
    parser.add_argument("--min-trades", type=int, default=1)
    parser.add_argument("--max-drawdown", type=float)
    parser.add_argument("--min-return-pct", type=float)
    args = parser.parse_args()

    report = run_dataset(
        args.dataset_dir,
        pairs=tuple(args.pairs),
        train_size=args.train_size,
        test_size=args.test_size,
        gap=args.gap,
        holdout_size=args.holdout_size,
        metric=args.metric,
        min_trades=args.min_trades,
        max_drawdown=args.max_drawdown,
        min_return_pct=args.min_return_pct,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({
        "output": args.output,
        "pairs": list(report["pairs"]),
    }, indent=2))


if __name__ == "__main__":
    main()
