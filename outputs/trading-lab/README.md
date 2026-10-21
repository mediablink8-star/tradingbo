# Ember Capital research and paper-trading lab

Ember Capital combines a broker-neutral FX research and paper-trading system,
a Solana meme-coin research and paper portfolio, and a persistent virtual
company dashboard. The AI agent company currently makes paper decisions. A
separate browser-approved Jupiter pilot is described below; it requires an
explicit Phantom approval for each transaction and does not execute the agent
company's decisions. A legacy server-side Jupiter worker is present in the
repository; it is disabled by default in `render.yaml` and must not be treated
as a production execution path. See [live execution status](LIVE-AUTONOMY.md).

## Run the paper dashboard

Requires Python 3.10+ and the standard library.

```
cd outputs/trading-lab
python app.py
```

Open the local dashboard at `http://127.0.0.1:8765`.

The immersive office is available at `http://127.0.0.1:8765/company.html` and has a return link to the Research Floor. It now connects to a real, recorded, deterministic paper-agent pipeline through `/api/forex/agents` and `/api/forex/agents/run`. Press **Run agent cycle** to execute research, strategy, independent risk review, paper-only coordination, and performance/audit recording. Reports are persisted in SQLite and are distinct from the office animations. The baseline strategy uses short observed-price momentum; it is an engineering baseline, not a validated profitable strategy.

The dashboard also has **Start FX paper agent** and **Stop agent** controls. Starting it runs the existing ForexAgentRuntime every 60 seconds while the server stays up; cycles are serialized with manual cycles and recorded in SQLite. Stop takes effect after an in-progress paper cycle finishes. This is an opt-in rules-based FX paper workflow; AI research stays advisory and cannot authorize an order. The FX paper broker remains the only execution path.

Automatic paper cycles are **off by default**. To opt in, set `EMBER_FOREX_AUTORUN=1` before starting `python app.py`; the server then attempts a cycle every 60 seconds. A cycle may abstain if quotes are stale, there are too few distinct observations, a risk limit is reached, or the broker rejects the paper order. ECB reference rates are not executable prices. No live broker execution is enabled.

The live paper-agent snapshot tries Yahoo intraday candles first, using 1-minute candles by default so the strict 5-minute quote-freshness gate can work. Override with `FX_YAHOO_INTERVAL` only if you understand the resulting freshness behavior. If Yahoo fails, the data layer falls back to ECB reference rates through Frankfurter; those daily reference rates are intentionally rejected by the agent freshness gate and must never be treated as executable prices. For historical daily data, Frankfurter can pin to the ECB source: https://frankfurter.dev/providers/ecb/.

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

## Solana meme-coin research (read-only)

The initial meme-coin research engine uses the public DexScreener API to combine
latest token-profile and boost lists, deduplicate Solana token addresses, inspect
each token's available pools, and score the highest-liquidity matching Solana
pair. Paid profiles/boosts are discovery sources only and do not add score.
See the [official DexScreener API reference](https://docs.dexscreener.com/api/reference).

Start the local server, then request a scan:

```bash
curl -s http://127.0.0.1:8765/api/meme/research
curl -s -X POST http://127.0.0.1:8765/api/meme/research/run \
  -H 'Content-Type: application/json' -d '{"limit":20}'
```

The scan returns a ranked candidate list, market-data rejection reasons, source
metadata, and provider errors. Defaults require at least $10,000 liquidity,
$20,000 24-hour volume, 100 transactions, a pair age between 5 minutes and
72 hours, and reject a one-hour price spike above 80%. The bounded score uses
liquidity, turnover, activity, buy/sell balance and modest positive momentum.
These are starting engineering filters, not a validated profitable strategy.

**Important limitations:** DexScreener market data does not establish contract
safety. A separate on-demand, read-only Solana RPC check is available:

```bash
curl -s -X POST http://127.0.0.1:8765/api/meme/security/check \
  -H 'Content-Type: application/json' -d '{"mint_address":"YOUR_SOLANA_MINT_ADDRESS"}'
```

It checks the mint account's SPL Token program, active mint/freeze authorities,
token supply, and the percentage of supply represented by the 20 largest token
accounts. These are risk indicators, not an audit: token accounts are not the
same as unique beneficial holders, and pools may appear among the largest accounts.
It does not test swap sellability or comprehensively inspect Token-2022 extensions.
If RPC checks fail, the response is `INCOMPLETE` and must not be treated as clean.
A `WATCH` label means only that market-data filters passed; it is not a buy signal.
The system is read-only: it cannot connect a wallet, prepare a swap, or submit a transaction.
Do not enable real-money execution on the strength of these checks alone.

## Tests

```
cd outputs/trading-lab
python -m unittest -v test_forex.py test_forex_lab.py test_forex_agents.py test_forex_market.py test_meme_research.py test_meme_safety.py test_backtest.py test_strategies.py test_robustness.py test_historical.py test_dataset.py test_intraday.py test_intraday_dataset.py test_true_walkforward.py test_research_selection.py test_research_report.py test_research_runner.py test_portfolio_report.py test_portfolio_backtest.py test_portfolio_selection.py test_portfolio_walkforward.py
```

Live broker execution remains intentionally out of scope.

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

## Equity/stocks evaluation foundation

The repository now includes a separate long-only, cash-only equity backtester in
`equity_backtest.py`. It reuses the same `Candle` format and the existing
chronological `true_walk_forward` selector used by FX research. It supports
explicit spread, slippage and per-fill commission assumptions, next-bar-open
fills after completed-candle signals, end-of-data liquidation, and trade,
equity, drawdown and risk-adjusted summaries. It has no broker or live-order
integration.

Use `true_walk_forward` with an `EquityBacktester` factory and candidate
signal factories to select on training windows and score later windows. Choose
a `periods_per_year` value appropriate to the candle interval.

**Important limitations:** fractional shares are assumed; dividends, splits,
taxes, borrow, halts, delistings and corporate actions are not modeled. This
module does not fetch stock prices. Historical studies must use timestamped,
point-in-time data and a survivorship-aware universe, or results can be
misleading. Neither this module nor its tests imply profitability. See the
[QuantConnect research guide](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide)
for discussion of walk-forward validation and look-ahead/survivorship bias.

### Forward-outcome paper evaluation

Every research scan now records WATCH candidates with a valid observed USD price
in a local SQLite database (`meme-paper.sqlite`). When a later scan or an
explicit update runs, the tracker samples current DexScreener prices for due
snapshots at 5-minute, 15-minute, 1-hour, 4-hour, and 24-hour horizons. It
reports gross returns, net returns after configurable *modeled* costs, average
net return, and win rate.

```bash
# Summary of accumulated paper observations
curl -s http://127.0.0.1:8765/api/meme/paper

# Sample due outcomes now (useful for a scheduled local task)
curl -s -X POST http://127.0.0.1:8765/api/meme/paper/update \
  -H 'Content-Type: application/json' -d '{}'
```

Default assumptions are 50 bps slippage per side and 30 bps fees per side
(1.6% modeled round-trip cost). Set `MEME_PAPER_SLIPPAGE_BPS` and
`MEME_PAPER_FEE_BPS` in the environment before starting the server to change
them. These are assumptions, not measured fills. Outcome prices are sampled near each target horizon, within a grace window
(maximum of 60 seconds or 25% of the horizon). Late samples are marked missed
and excluded from return statistics instead of being misreported as target-time
returns. Missed provider prices remain pending rather than being counted as
losses or zeros. Each scan is a
separate sample, so repeated scans can create overlapping observations. The
tracker is paper-only and never submits trades.

## Tests

```
cd outputs/trading-lab
python -m unittest -v test_forex.py test_forex_lab.py test_forex_agents.py test_forex_market.py test_meme_research.py test_meme_safety.py test_meme_paper.py test_backtest.py test_strategies.py test_robustness.py test_historical.py test_dataset.py test_intraday.py test_intraday_dataset.py test_true_walkforward.py test_research_selection.py test_research_report.py test_research_runner.py test_portfolio_report.py test_portfolio_backtest.py test_portfolio_selection.py test_portfolio_walkforward.py
```

Live broker execution remains intentionally out of scope.

## Hosted deployment (Render)

The repository root contains a Render Blueprint at `render.yaml`. In Render, create a new Blueprint Instance from this repository and follow the prompts for `TRADINGLAB_USERNAME` and `TRADINGLAB_PASSWORD`. Use a unique username and a password of at least 16 characters; do not commit either value to Git. Render deploys the Python app from this directory, exposes it on the platform-provided port, and mounts a persistent disk at `/var/data` for both SQLite databases.

Hosted mode enables HTTP Basic Authentication for the dashboard, API routes, and static assets. The public `/healthz` endpoint is reserved for Render's health check. Paper-agent auto-run remains disabled by default; you can use the office's **Run agent cycle** control after signing in. This service is for research and paper trading only; it does not enable live broker or wallet execution.

This Blueprint uses Render's Free web-service plan and does not create a persistent disk. It should cost $0 for compute within Render's free usage limits, but the service may sleep after inactivity and SQLite files/local changes can be lost when the instance restarts, spins down, or redeploys. Treat hosted paper-trading history as disposable; do not use this free deployment as a durable ledger. To preserve data, use a durable external database or a paid service with a persistent disk. After the first deploy, test the root dashboard and `/company.html` while signed in. The service remains research/paper-only.



## Autonomous Solana meme-coin paper trading

The dashboard's **Autonomous Paper Trader** is a separate simulated portfolio; it is not the forward-outcome tracker above. A paper cycle scans candidates, applies deterministic entry gates, requires a complete read-only mint check, and records simulated positions in `meme-trader.sqlite`. It does not connect a wallet, sign, prepare, or submit swaps.

Default controls are intentionally conservative and configurable via environment variables:

- `MEME_PAPER_POSITION_USD=50` — maximum simulated entry notional.
- `MEME_PAPER_MAX_POSITIONS=3` — concurrent position cap.
- `MEME_PAPER_DAILY_LOSS_LIMIT_USD=50` — realized-loss halt threshold.
- `MEME_PAPER_FEE_BPS=30` and `MEME_PAPER_SLIPPAGE_BPS=50` — modeled costs per side.
- `MEME_PAPER_AUTORUN=1` opts into an in-process scan/management loop; it is **off by default**.
- `MEME_PAPER_INTERVAL_SECONDS=300` changes the loop interval (minimum 60 seconds).

Each position uses a 12% stop loss, 20% take-profit target, and four-hour maximum holding time. Entry gates also require score >=75, at least $25k liquidity, $50k 24-hour volume, 150 transactions, a bounded buy ratio, and no excessive one-hour pump. These are experimental engineering defaults, not a profitable or validated strategy. Stop/target decisions use sampled provider quotes, so gaps and slippage can make real execution materially different.

API:
- `GET /api/meme/trader` — portfolio, positions, and audit events.
- `POST /api/meme/trader/run` with `{"limit":20}` — run discovery, risk/safety checks, and paper decisions.
- `POST /api/meme/trader/tick` with `{}` — refresh positions and evaluate exits only.

The trader fails closed when safety data is incomplete, when mint/freeze authorities remain active, or when high-severity concentration findings are present. A completed check is still not a token audit or proof of sellability. Paper orders are not executable fills.

**Hosted storage requirement:** SQLite persists across process restarts only when its directory persists. The current Render service uses the free plan and has no configured persistent disk; its local database files can be lost on replacement/deploy. Before relying on history or enabling unattended hosted runs, attach durable storage or move the state to a managed database, set `TRADINGLAB_DATA_DIR` to that persistent location, and verify the database survives a redeploy.
