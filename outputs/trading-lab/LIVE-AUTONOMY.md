# Live execution status and release boundary

## Current product boundary

The supported product is a personal FX, metals, and US stocks trading desk.
The AI committee can deliberate and the existing FX paper workflow can record
simulated outcomes. There is no supported live broker executor today. AI
recommendations are not live orders, and no profitability or live readiness is
claimed.

The hosted dashboard must not store IBKR credentials or reach IB Gateway. The
future execution service is designed to run on the user's PC beside IB Gateway.
The new `local_executor_gate.py` contains only fail-closed heartbeat, arm-lease,
and disarm primitives; it has no broker connection, order submission,
persistence, authentication, or UI integration. It is a foundation, not an
execution adapter. Do not configure it as a live trading service.

Legacy Solana/Jupiter paths remain in the repository for historical reference.
They are outside the active product, must remain disabled in deployment, and
must not be used for autonomous execution. The Render service should serve the
dashboard only.

## Implemented in this branch

- Explicit supported universe remains the existing five FX pairs, XAU/USD, and
  six US large-cap stocks. No additional instruments are introduced.
- A local executor lease primitive requires a fresh heartbeat before arming,
  caps arm duration, and fails closed on disconnect, stale heartbeat, lease
  expiry, or explicit disarm.
- The existing deterministic paper risk engine remains the final authority for
  the paper workflow. Its current defaults are engineering defaults, not live
  limits or recommendations.
- A staged implementation and acceptance checklist is recorded in
  [AUTONOMY-ROADMAP.md](AUTONOMY-ROADMAP.md).

## Required before a live release

1. Retire crypto surfaces from active navigation and remove crypto secrets and
   autorun settings from the Render deployment while preserving legacy data.
2. Unify instrument metadata and quote freshness; live orders must only use
   executable IBKR quotes. Reference or synthetic fallback prices must block
   order entry.
3. Build the local, authenticated executor beside IB Gateway. Keep broker
   credentials local. Use outbound authenticated TLS communication with the
   hosted dashboard, heartbeat leases, idempotent commands, and durable audit.
4. Implement an IBKR adapter that reconciles orders, executions, positions,
   balances, commissions, and uncertain submissions. Re-check deterministic
   risk constraints immediately before every order.
5. Finish the desk UI with explicit paper/live state, quote source and age,
   order status, account exposure, loss limits, committee activity, and a
   persistent kill control.
6. Complete end-to-end paper integration and failure-recovery checks. Paper
   mode is an integration gate, not evidence of profitability.
7. Require a user-reviewed paper record and manual sign-off. Then require
   user-configured live risk limits and an explicit manual live arm. Only after
   those gates may the AI submit orders without per-order confirmation, and
   every proposed order must still pass deterministic controls.
8. Prepare operations: credential handling, backups, alerts, recovery, kill
   behavior, and documented incident steps. A disconnected executor blocks
   new entries; risk-reducing management must be defined and verified before
   live launch.

## Trading and safety model

The AI can propose an action and explain evidence. It cannot change risk
settings, arm itself, widen limits, or override a rejection. Manual disarm
blocks new entries and cancels unfilled entry orders; the live design must keep
risk-reducing management available and must not force liquidation by default.
No local machine, broker account, or strategy is currently configured for live
trading.
