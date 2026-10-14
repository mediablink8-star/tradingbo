# Ember Six-Agent Autonomous Paper Trader

## Overview

This spellbook entry configures a six-agent autonomous paper trading system
using OpenRouter LLM models with proper risk gating and broker integration.

## Architecture

```
┌─────────────────┐    ┌─────────────┐    ┌─────────────┐
│  Market Data    │───▶│  Six Agents  │───▶│ Risk Engine │
│ (Yahoo Finance) │    │ (LLM Layer)  │    │ (Gate)      │
└─────────────────┘    └─────────────┘    └─────────────┘
                                                 │
                                                 ▼
                                          ┌─────────────┐
                                          │ Alpaca      │
                                          │ (Paper)     │
                                          └─────────────┘
```

## Prerequisites

- Python 3.10+
- OpenRouter API key with a free model available
- Alpaca paper trading account

## Environment Variables

Create a `.env` file in the `api/` directory:

```bash
# Paper trading (default)
ENV=paper

# Alpaca Paper Trading
ALPACA_API_KEY=YOUR_KEY_HERE
ALPACA_SECRET_KEY=YOUR_SECRET_HERE
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# OpenRouter LLM
LLM_API_KEY=sk-or-v1-your-key-here
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=your-model:free  # e.g. nvidia/nemotron-3-ultra-550b-a55b:free

# Risk Limits
MAX_PER_TRADE_USD=3.0
MAX_DAILY_LOSS_USD=5.0
MAX_OPEN_POSITIONS=3
MAX_EXPOSURE_USD=10.0
ARM_TTL_HOURS=24.0
```

## Quick Start

```bash
cd outputs/trading-lab/api
python start_trading.py
```

Or manually:

```bash
# Start server
python -m uvicorn main:app --host 0.0.0.0 --port 8080

# In another terminal:
# 1. Arm the risk gate
curl -X POST http://localhost:8080/api/autonomous/arm -d '{"hours":24}'

# 2. Start autonomous trading
curl -X POST http://localhost:8080/api/autonomous/start

# 3. Check status
curl http://localhost:8080/api/autonomous/status

# 4. Stop autonomous trading
curl -X POST http://localhost:8080/api/autonomous/stop

# 5. Disarm (emergency stop)
curl -X POST http://localhost:8080/api/autonomous/stop
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info and health |
| `/healthz` | GET | Health check |
| `/api/agents/roles` | GET | List the six agent roles |
| `/api/agents/cycle` | POST | Run single agent cycle |
| `/api/books/summary` | GET | Broker account status |
| `/api/live/status` | GET | Risk gate status |
| `/api/live/arm` | POST | Arm risk gate |
| `/api/live/disarm` | POST | Disarm risk gate |
| `/api/autonomous/status` | GET | Autonomous trader status |
| `/api/autonomous/arm` | POST | Arm autonomous trader |
| `/api/autonomous/start` | POST | Start auto loop |
| `/api/autonomous/stop` | POST | Stop auto loop |
| `/api/autonomous/run_once` | GET/POST | Run one cycle manually |

## The Six Agents

1. **Market Observer** — Describes prices, liquidity, data quality
2. **Technical Analyst** — Reads momentum/structure from observed series
3. **Macro/Narrative Analyst** — Flags regime risk from price patterns
4. **Strategy Proposer** — Proposes testable paper hypotheses
5. **Risk Critic** — Attacks proposals, favors abstention on weak edges
6. **Portfolio Coordinator** — Final decision under risk limits

## Risk Management

The system enforces strict risk controls:
- **Max per-trade**: Configurable (default $3)
- **Max daily loss**: Configurable (default $5)
- **Max open positions**: Configurable (default 3)
- **Max total exposure**: Configurable (default $10)
- **ARM TTL**: Risk gate expires after N hours (default 24h)

All trades must pass through the risk gate before execution.

## Files Modified

- `api/main.py` — Added autonomous trading endpoints
- `api/llm_research.py` — New LLM research layer for OpenRouter
- `api/autonomous_loop.py` — Autonomous trading scheduler and cycle logic
- `api/routers/agents.py` — Updated to use LLM layer with live market data
- `api/.env` — Environment configuration with credentials