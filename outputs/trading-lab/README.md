# Forex research + paper-trading lab

TradingLab is now a broker-neutral FX research and paper-trading system. It has
no wallet connection, blockchain integration, token discovery, or live broker
execution.

## Run the paper dashboard

Requires Python 3.10+ and the standard library.

```
cd outputs/trading-lab
python app.py
```

Open the local dashboard at `http://127.0.0.1:8765`.

The immersive office is available at `http://127.0.0.1:8765/company.html` and has a return link to the Research Floor. It now connects to a real, recorded, deterministic paper-agent pipeline through `/api/forex/agents` and `/api/forex/agents/run`. Press **Run agent cycle** to execute research, strategy, independent risk review, paper-only coordination, and performance/audit recording. Reports are persisted in SQLite and are distinct from the office animations. The baseline strategy uses short observed-price momentum; it is an engineering baseline, not a validated profitable strategy.

Automatic paper cycles are **off by default**. To opt in, set `EMBER_FOREX_AUTORUN=1` before starting `python app.py`; the server then attempts a cycle every 60 seconds. A cycle may abstain if quotes are stale, there are too few distinct observations, a risk limit is reached, or the broker rejects the paper order. ECB reference rates are not executable prices. No live broker execution is enabled.

Market data defaults to ECB reference rates through Frankfurter. Frankfurter
supports provider pinning, so the historical pipeline can use the ECB source
rather than a blended feed. See https://frankfurter.dev/providers/ecb/.

## Architecture

```
historical/intraday data
        ↓
candidate strategies
        ↓
chronological train / gap / OOS
        ↓
portfolio-aware selection
        ↓
shared-capital portfolio backtest
        ↓
isolated final holdout
        ↓
research report
```

The AI layer is advisory only: market research, macro analysis, strategy
hypotheses and risk criticism. It has no execution tools and cannot override
deterministic risk controls.

## Research methodology

The research layer uses chronological walk-forward evaluation rather than
randomized cross-validation. Signals are formed from completed candles and
filled at the next candle's open in the single-pair and portfolio engines,
avoiding same-close signal look-ahead. Portfolio stop/target checks use candle
highs and lows, assume the stop is hit first if both levels are crossed, and
model gaps through a stop at the worse opening price. A gap can also be
inserted between train and test windows.

The joint portfolio evaluator:

- aligns pairs on common timestamps;
- selects one candidate per pair using only the training window;
- applies shared capital, exposure, position-count and currency-concentration
  limits during selection;
- carries OOS capital forward from one window to the next;
- records strategy choices and risk events per OOS window;
- keeps the final holdout untouched until all walk-forward decisions are done.

The portfolio selector is deterministic greedy coordinate descent, not an
exhaustive optimizer. That is intentional: the candidate universe is too
large for brute-force combinations across five pairs. The report therefore
also exposes strategy-selection frequency so unstable choices are visible.

## Portfolio risk model

The research portfolio supports:

- fixed USD position notional;
- maximum total exposure;
- maximum open positions;
- maximum daily realized loss;
- stop loss;
- take profit;
- maximum position age;
- maximum per-currency USD exposure.

These are engineering defaults for controlled paper research, not trading
recommendations.

## Historical data

The daily pipeline loads provider-pinned ECB reference rates. These are daily
reference/mid rates, not executable broker OHLC data, so the loader intentionally
does not fabricate intraday highs/lows.

```
python -c "from dataset import build_dataset; build_dataset(['EUR/USD','GBP/USD','USD/JPY','AUD/USD','USD/CHF'],'2020-01-01','2025-12-31','data/fx-daily')"
```

Frankfurter provides daily rates and historical ranges and supports selecting a
specific provider. See https://frankfurter.dev/.

For intraday research, the Alpha Vantage adapter supports monthly FX intraday
datasets at supported intervals. The resulting OHLC candles can feed the same
deterministic backtester.

```
python -c "from intraday_dataset import build_dataset; build_dataset(['EUR/USD'],'2025-01','2025-12','data/fx-15m','15min')"
```

Intraday gaps are reported instead of blindly filled.

## Run the full research study

After building the dataset:

```
cd outputs/trading-lab
python research_runner.py data/fx-daily --train-size 500 --test-size 100 --holdout-size 100 --output research-report.json
```

The report contains:

- independent pair walk-forward results;
- pair-level aggregate statistics;
- joint portfolio walk-forward results;
- selected strategy combination per OOS window;
- carried portfolio capital;
- risk events and trades;
- isolated final portfolio holdout.

Do not judge the system from a single backtest return. The useful evidence is
consistency across unseen windows, drawdown, Sharpe, costs, stability of
strategy selection, and performance on the untouched final holdout.

## Tests

```
cd outputs/trading-lab
python -m unittest -v test_forex.py test_forex_lab.py test_forex_agents.py test_backtest.py test_strategies.py test_robustness.py test_historical.py test_dataset.py test_intraday.py test_intraday_dataset.py test_true_walkforward.py test_research_selection.py test_research_report.py test_research_runner.py test_portfolio_report.py test_portfolio_backtest.py test_portfolio_selection.py test_portfolio_walkforward.py
```

Live broker execution remains intentionally out of scope.
