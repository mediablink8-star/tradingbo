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
from portfolio_report import aggregate_pair_reports
from portfolio_backtest import MultiPairPortfolioBacktester
from portfolio_selection import select_portfolio_strategies
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


def run_shared_holdout_portfolio(reports, datasets, holdout_size=100, starting_cash=10000.0):
    """Evaluate a portfolio selected jointly on pre-holdout data."""
    if not reports:
        raise ValueError("reports must not be empty")

    candidates = default_strategy_candidates()
    pre_holdout = {
        pair: candles[:-holdout_size]
        for pair, candles in datasets.items()
    }
    holdout_data = {
        pair: candles[-holdout_size:]
        for pair, candles in datasets.items()
    }
    candidate_map = {pair: candidates for pair in datasets}
    selection = select_portfolio_strategies(
        pre_holdout,
        candidate_map,
        metric="sharpe",
        max_iterations=2,
    )
    factories = dict(candidates)
    signals = {
        pair: factories[name]()
        for pair, name in selection["selected"].items()
    }
    result = MultiPairPortfolioBacktester(
        starting_cash=starting_cash,
        per_position_notional=1000.0,
        max_exposure=3000.0,
        max_positions=3,
        spread_bps=1.0,
        slippage_bps=0.5,
    ).run(holdout_data, signals)
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

