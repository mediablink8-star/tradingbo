# FX, metals, and stocks autonomy roadmap

This checklist is the implementation contract for the personal trading desk.
The product uses FX, XAU/USD, and the six existing US large-cap stocks. The
dashboard runs on Render; the broker executor belongs on the user's PC beside
IB Gateway. Offline PC or lost gateway means no new trades. The AI may submit
orders only after the paper and manual live-arming gates below.

## Stage 1 — Product boundary and legacy isolation

- [ ] Make FX, gold, and stocks the only active product universe.
- [ ] Remove crypto/Polymarket active navigation, controls, secrets, and deploy
  settings while preserving historical code/data where needed.
- [ ] Replace old live trading claims with the current release boundary.

Acceptance: onboarding, dashboard, deployment docs, and APIs expose one clear
product; no server-side wallet or unrelated worker can auto-start.

## Stage 2 — Instrument and market-data contract

- [ ] Define one metadata record per supported instrument: class, symbol,
  base/quote currency, trading hours, tick size, lot/quantity units, and
  supported order types.
- [ ] Separate research/reference data from executable broker quotes.
- [ ] Display quote source, timestamp, age, and market-open state.
- [ ] Reject live entries for stale, synthetic, fallback, or non-IBKR quotes.

Acceptance: each quote and order carries a validated instrument identity and
source; stale or ineligible data cannot reach an execution command.

## Stage 3 — Risk and paper workflow

- [ ] Keep deterministic limits authoritative across FX, metals, and stocks:
  per-order risk/notional, gross exposure, concentration, open positions,
  daily loss, leverage, stops, and trading-session controls.
- [ ] Make paper AI cycles opt-in, serialized, budget-aware, auditable, and
  reproducible.
- [ ] Enforce the six-call committee budget and hold when the 40-call daily
  budget is exhausted.
- [ ] Capture recommendations, input quote snapshots, risk decisions, orders,
  fills, fees, and resulting positions.

Acceptance: all allowed instruments can complete an end-to-end paper cycle;
every reject has a user-readable reason; model failure or missing data means
hold.

## Stage 4 — Local IBKR executor

- [ ] Run beside IB Gateway on the user's PC; keep credentials and API access
  local.
- [ ] Authenticate dashboard-to-executor commands over outbound TLS; do not
  expose IB Gateway to the public internet.
- [ ] Add heartbeat lease, explicit live arm, persistent kill switch,
  idempotency, command expiry, replay protection, and durable audit.
- [ ] Implement IBKR quote/account/order/fill reconciliation and uncertain
  submission recovery.
- [ ] Re-check all limits at the executor immediately before submission.
- [ ] On disconnect or expired lease, block new entries. Define and test
  risk-reducing order handling and cancellation behavior.

Acceptance: fail closed during stale quotes, lost connection, duplicate
commands, process restart, partial fill, timeout, and kill-switch operation.
The executor gate in this branch is only a primitive and does not satisfy this
stage by itself.

## Stage 5 — Trading desk UI

- [ ] Replace legacy mixed navigation with a dense, polished dark terminal.
- [ ] Put environment and account state, live/paper status, arm lease, and kill
  control in persistent view.
- [ ] Show instruments, quote source/age, exposure, P&L, risk headroom,
  positions, orders, fills, and agent decisions.
- [ ] Make AI rationale, dissent, risk veto, and exact execution result
  inspectable.

Acceptance: no visual state implies an order is live unless confirmed by the
executor; disconnected/stale/paused states are unmistakable.

## Stage 6 — Paper integration and manual graduation

- [ ] Run the complete system in paper mode and verify normal operations and
  failure paths; treat paper fills as integration evidence, not profitability.
- [ ] Review the resulting paper record manually; no fixed duration or trade
  count substitutes for user sign-off.
- [ ] Require user-configured risk limits and a new explicit live arm before
  the first live entry.
- [ ] After manual arming, AI orders may be submitted without per-order human
  approval, but every order remains subject to deterministic rejection.

Acceptance: there is no path from AI proposal to a live order before the
review/sign-off, configured limits, and live arm are all present.

## Stage 7 — Operations and release

- [ ] Secure local credentials, maintain backups, alert on exceptions, define
  recovery and incident handling, and document upgrades/rollback.
- [ ] Verify production secrets, access controls, persistent storage, broker
  environment, and kill behavior before any funded pilot.
- [ ] Keep the live path off until every prior acceptance item passes.

Acceptance: operator can identify current state, halt new entries, recover
uncertain orders, and audit every decision and broker event.
