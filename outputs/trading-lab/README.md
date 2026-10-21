# Ember Capital Forex trading desk

A Forex-only research and paper-trading product for EUR/USD, GBP/USD, USD/JPY,
AUD/USD and USD/CHF. Market data may be delayed or reference-only; simulated
orders pass through deterministic risk controls. The six-agent AI committee
can recommend paper actions only. No live broker connection or order path is
enabled. Legacy crypto code remains outside the active UI and API surface.

See [the staged autonomy and release plan](AUTONOMY-ROADMAP.md) and
[live execution status](LIVE-AUTONOMY.md) before enabling any automated mode.

## Run the paper dashboard

Requires Python 3.10+ and the standard library.

```
cd outputs/trading-lab
python app.py
```

Open the local dashboard at `http://127.0.0.1:8765`.

The immersive office is available at `http://127.0.0.1:8765/company.html` and has a return link to the Research Floor. The recorded Forex paper pipeline is available through `/api/forex/agents` and `/api/forex/agents/run`. **Run agent cycle** is a deterministic baseline pass; **Run AI paper cycle** runs the six-agent committee, stores its recommendation and input quote snapshot, and applies only an allowed paper action. Reports are persisted in SQLite and are distinct from office animations. The baseline strategy is an engineering reference, not a validated profitable strategy.

The dashboard also has **Start autonomous AI paper** and **Stop AI agent** controls. Starting the worker requires a configured model and at least six remaining model calls in the daily budget. It runs one six-agent committee cycle every five minutes by default (`FX_AI_AUTONOMOUS_INTERVAL`, minimum 60 seconds), while the server stays up. The worker is off after restart; cycles are serialized with manual cycles and recorded in SQLite. Stop takes effect after an in-progress model or market-data request completes. AI failures, any missing committee response, a risk-critic veto, unsupported pairs, stale quotes or deterministic risk rejections all result in no entry. The FX paper broker remains the only execution path.

Paper automation is **off by default** and must be started from the authenticated dashboard. The AI cycle costs up to six model calls; it refuses to start if the daily call or spend allowance cannot cover the full committee. After the daily budget is exhausted, the worker stops. No wallet, IBKR credentials or live orders are used.

The paper market snapshot tries Yahoo intraday candles first, using 1-minute candles by default. Override `FX_YAHOO_INTERVAL` only if you understand the resulting freshness behavior. If Yahoo fails, the data layer can fall back to ECB reference rates through Frankfurter; those daily reference rates are intentionally rejected by the agent freshness gate and must never be treated as executable prices. For historical daily data, Frankfurter can pin to the ECB source: https://frankfurter.dev/providers/ecb/.

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

## Archived code outside the product scope

Older Solana, Jupiter, equity and cross-asset modules remain in the repository for historical compatibility. They are not exposed as product navigation or API routes, are not configured in Render, and cannot auto-start. The active product universe and broker are Forex-only.

## Indicator warm-up in out-of-sample tests

Walk-forward and isolated holdout evaluation carry the immediately preceding
candles into each test window as indicator context, while suppressing signals
and orders during warm-up. Signals begin only after the first out-of-sample
candle closes and can fill no earlier than the following candle's open.
Warm-up observations are excluded from reported out-of-sample history and the
Sharpe calculation. The research runner uses up to 100 preceding candles,
covering the current candidate library's longest EMA lookback. This avoids
silently evaluating long-lookback strategies with empty indicator history at
every test-window boundary.

## Tests

```bash
cd outputs/trading-lab
python -m unittest -v test_forex.py test_forex_lab.py test_forex_agents.py test_forex_market.py test_execution_safety.py test_deployment_config.py test_backtest.py test_strategies.py test_robustness.py test_historical.py test_dataset.py test_intraday.py test_intraday_dataset.py test_true_walkforward.py test_research_selection.py test_research_report.py test_research_runner.py test_portfolio_report.py test_portfolio_backtest.py test_portfolio_selection.py test_portfolio_walkforward.py
```

Live broker execution remains disabled. The local executor gate is not a broker adapter; see [the live execution boundary](LIVE-AUTONOMY.md).

## Hosted deployment (Render)

The repository root contains the Render Blueprint at `render.yaml`. It deploys the Python app from `outputs/trading-lab`, requires `TRADINGLAB_USERNAME` and `TRADINGLAB_PASSWORD` to be supplied in Render, and mounts a 1 GB persistent disk at `/data/tradingbo` for SQLite state. Do not commit credentials to Git. The Blueprint uses a Starter web-service plan; service health is checked at `/healthz`.

Hosted mode enables HTTP Basic Authentication for dashboard mutations, the AI paper-cycle endpoint, and static assets. Read-only paper status remains available to the dashboard. Sign in, configure and verify an AI provider in the AI Desk, then explicitly start the autonomous Forex paper worker. It stops after a restart and is not a live broker service. No Vercel deployment is required.
