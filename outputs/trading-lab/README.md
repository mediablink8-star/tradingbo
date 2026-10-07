# Forex paper-trading lab

Ember is now a broker-neutral FX trading dashboard. The system tracks major currency pairs, paper positions, P/L and deterministic risk limits. It has no wallet connection, blockchain integration, token discovery or cryptocurrency execution.

## Run

Requires Python 3.10+ and the standard library.

```
cd outputs/trading-lab
python app.py
```

Open http://127.0.0.1:8765.

Market data defaults to ECB reference rates through Frankfurter. Set `FX_MARKET_DATA_URL` to a compatible provider endpoint when moving to a broker-grade intraday feed.

## Forex architecture

Market data → AI analysis → deterministic FX risk gate → paper broker → position ledger → P/L.

The deterministic risk layer is authoritative. Default limits are $1,000 maximum trade notional, $3,000 total exposure, three open positions, $200 daily loss, 1% stop loss, 2% take profit and 1× leverage. These are engineering defaults, not trading recommendations.

The paper broker supports long and short currency-pair positions and persists the account in `lab.sqlite`. No broker credentials or signing keys are required.

## AI agents

The agent layer is FX-specific: market researcher, macro analyst, strategy analyst, risk critic and portfolio coordinator. Agents can recommend paper actions but do not have execution tools and cannot override deterministic risk controls.

Live broker execution is intentionally not part of this migration. A future broker adapter should implement the same interface without exposing credentials to agents.

## Tests

```
cd outputs/trading-lab
python -m unittest -v test_forex.py
```


## Backtesting

The lab includes a deterministic OHLC backtester in `backtest.py`. It models configurable spread and slippage, calculates trade P/L, win rate and maximum drawdown, and keeps strategy signals separate from execution. It is intended for research and paper evaluation only; backtest results are not evidence of future profitability.

Alpha Vantage documents `FX_INTRADAY` for intraday OHLC FX history at 1, 5, 15, 30 and 60 minute intervals; its intraday endpoint is a premium API. citeturn0search0
