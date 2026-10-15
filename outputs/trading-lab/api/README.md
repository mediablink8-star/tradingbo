# TradingLab API — Phase 1

FastAPI foundation for multi-broker paper → live.

## Brokers

| Book   | Backend        | Status                          |
|--------|----------------|---------------------------------|
| Stocks | Alpaca paper   | Ready when keys set             |
| Forex  | FX simulation  | Default until OANDA             |
| Solana | Jupiter        | Status only until wallet + ARM  |

## Risk

All new orders go through `RiskGate`:

- Manual **ARM** (TTL default 24h)
- **DISARM** freezes new orders
- max $/trade, daily loss, open count, exposure

## Run

```bash
cd outputs/trading-lab/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-api.txt
cp .env.example .env   # fill Alpaca keys
uvicorn main:app --host 0.0.0.0 --port 8080
```

Open `/docs` for interactive API.

## Endpoints

- `GET /healthz`
- `GET /api/books/summary`
- `GET /api/live/status`
- `POST /api/live/arm`  `{ "hours": 24 }`
- `POST /api/live/disarm`
- `POST /api/stocks/order` `{ "symbol": "AAPL", "notional_usd": 10, "side": "buy" }`
