# Release boundary: Forex paper trading only

## Current product

The supported instruments are EUR/USD, GBP/USD, USD/JPY, AUD/USD and USD/CHF.
The six-agent AI committee can deliberate, recommend and record simulated Forex
actions. The dashboard paper broker and deterministic risk engine are the only
execution path in this release. Paper prices and fills are simulations; this
system has not established a profitable strategy.

The Render service hosts the dashboard and persistent paper ledger. It does
not store IBKR credentials, connect to IB Gateway, or submit live orders. The
legacy crypto source is retained for historical compatibility but its
navigation, API routes, wallet key loading and auto-workers are disabled in the
Forex product.

## What the AI paper worker does

- Starts only after an operator explicitly starts it from the authenticated
  dashboard; it is stopped after every server restart.
- Runs a six-agent committee and requires every response, no Risk Critic veto,
  a supported currency pair and sufficient model-call/spend budget.
- Records the quote snapshot, recommendation, gate result, simulated action
  and resulting account in the persistent Forex database.
- Sends no live order. Every simulated entry still goes through current quote
  validation and deterministic paper risk limits.

## What remains before live trading

The `local_executor_gate.py` module, `instrument_catalog.py` validator and
`local_executor_service.py` control service are fail-closed foundations. The
local service runs on loopback, forces a durable kill switch after restart,
and accepts signed, expiring, replay-resistant kill/disarm commands. It has no
arm endpoint, IBKR API adapter, order endpoint, order reconciliation, broker
paper-account test or live control UI. The Render dashboard cannot serve as a
broker executor.

Before any live release, the project still needs a local executor next to IB
Gateway, authenticated expiring commands, idempotency and replay protection,
broker account/position/order/fill reconciliation, uncertain-submission
recovery, verified contract details, a durable kill switch, alerts/backups and
an operator-reviewed prospective paper record. A user-configured live risk
policy and a separate explicit live arm are also required. The AI cannot arm
itself or override deterministic limits.

No broker credentials, connected account, funding, live trading or profitability
are claimed. Continue with the [implementation roadmap](AUTONOMY-ROADMAP.md).
