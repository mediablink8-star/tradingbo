"""Reproducible offline FX research runner.

Runs independent pair research plus a joint portfolio-aware walk-forward and an
isolated final holdout. No broker or live execution is used.
"""
import argparse
import json
import os

from backtest import FXBacktester
from historical import load_json
from portfolio_backtest import MultiPairPortfolioBacktester
from portfolio_report import aggregate_pair_reports
from portfolio_selection import select_portfolio_strategies
from portfolio_walkforward import portfolio_true_walk_forward
from research_report import build_research_report
from strategies import default_strategy_candidates
from true_walkforward import optimize_window, true_walk_forward


DEFAULT_PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CHF")


def _pair_file(dataset_dir, pair):
    return os.path.join(dataset_dir, pair.replace("/", "_") + ".json")


def _portfolio_factory(cash):
    return MultiPairPortfolioBacktester(
        starting_cash=cash,
        per_position_notional=1000.0,
        max_exposure=3000.0,
        max_positions=3,
        spread_bps=1.0,
        slippage_bps=0.5,
        max_daily_loss=200.0,
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
        max_position_age=86400.0,
        max_currency_exposure=3000.0,
    )


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
        pre_holdout, backtester_factory, candidates,
        train_size=train_size, test_size=test_size, gap=gap, metric=metric,
        min_trades=min_trades, max_drawdown=max_drawdown,
        min_return_pct=min_return_pct,
    )
    selected, ranking = optimize_window(
        pre_holdout, backtester_factory(), candidates, metric=metric,
        min_trades=min_trades, max_drawdown=max_drawdown,
        min_return_pct=min_return_pct,
    )
    holdout_result = backtester_factory().run(holdout, dict(candidates)[selected["name"]]())
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


def run_shared_holdout_portfolio(datasets, holdout_size=100, starting_cash=10000.0):
    if not datasets:
        raise ValueError("datasets must not be empty")
    if any(holdout_size >= len(candles) for candles in datasets.values()):
        raise ValueError("holdout_size must leave data before the holdout")

    candidates = default_strategy_candidates()
    pre_holdout = {pair: candles[:-holdout_size] for pair, candles in datasets.items()}
    holdout = {pair: candles[-holdout_size:] for pair, candles in datasets.items()}
    candidate_map = {pair: candidates for pair in datasets}

    selection = select_portfolio_strategies(
        pre_holdout, candidate_map, metric="sharpe", max_iterations=2,
        portfolio_backtester_factory=lambda: _portfolio_factory(starting_cash),
    )
    signals = {
        pair: dict(candidate_map[pair])[name]()
        for pair, name in selection["selected"].items()
    }
    result = _portfolio_factory(starting_cash).run(holdout, signals)
    return {
        "selection": selection["selected"],
        "selection_training": selection["training_result"],
        "starting_cash": result["starting_cash"],
        "ending_cash": result["ending_cash"],
        "return_pct": result["return_pct"],
        "max_drawdown": result["max_drawdown"],
        "sharpe": result["sharpe"],
        "trades": len(result["trades"]),
        "history": result["history"],
    }


def run_dataset(
    dataset_dir,
    pairs=DEFAULT_PAIRS,
    train_size=500,
    test_size=100,
    gap=0,
    holdout_size=100,
):
    datasets = {}
    for pair in pairs:
        path = _pair_file(dataset_dir, pair)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        datasets[pair.upper()] = load_json(path)

    reports = {
        pair: run_pair(
            pair, candles, train_size=train_size, test_size=test_size,
            gap=gap, holdout_size=holdout_size,
        )
        for pair, candles in datasets.items()
    }
    candidate_map = {pair: default_strategy_candidates() for pair in datasets}
    portfolio_wf = portfolio_true_walk_forward(
        datasets,
        candidate_map,
        train_size=train_size,
        test_size=test_size,
        gap=gap,
        starting_cash=10000.0,
        portfolio_backtester_factory=_portfolio_factory,
        max_iterations=2,
    )
    portfolio_holdout = run_shared_holdout_portfolio(
        datasets, holdout_size=holdout_size,
        starting_cash=portfolio_wf["ending_cash"],
    )
    return {
        "pairs": reports,
        "portfolio": {
            "walk_forward": portfolio_wf,
            "final_holdout": portfolio_holdout,
        },
        "pair_aggregate": aggregate_pair_reports(reports),
    }


def main():
    parser = argparse.ArgumentParser(description="Run offline FX research.")
    parser.add_argument("dataset_dir")
    parser.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    parser.add_argument("--train-size", type=int, default=500)
    parser.add_argument("--test-size", type=int, default=100)
    parser.add_argument("--gap", type=int, default=0)
    parser.add_argument("--holdout-size", type=int, default=100)
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    pairs = tuple(p.strip().upper() for p in args.pairs.split(",") if p.strip())
    report = run_dataset(
        args.dataset_dir,
        pairs=pairs,
        train_size=args.train_size,
        test_size=args.test_size,
        gap=args.gap,
        holdout_size=args.holdout_size,
    )
    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output == "-":
        print(payload)
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")


if __name__ == "__main__":
    main()
