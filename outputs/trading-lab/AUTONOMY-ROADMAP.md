# Forex-only AI paper trader: implementation and release roadmap

This plan describes the supported product: EUR/USD, GBP/USD, USD/JPY,
AUD/USD and USD/CHF. Render hosts the authenticated dashboard and durable
paper ledger. A future live executor must run locally beside IB Gateway so the
hosted AI service never stores broker credentials or reaches a public gateway.
The current release is paper-only; it is not evidence of profitability.

## Stage 1 — Forex product boundary (complete)

- [x] Limit the active market catalog, quote API, charts and paper broker to the
  five supported currency pairs.
- [x] Hide legacy crypto/Polymarket navigation and controls; disable legacy
  crypto API routes, wallet keys and auto-workers while preserving old source
  and local data for reference.
- [x] Keep Render configured for the Python dashboard, auth and persistent
  paper-data disk only.

Acceptance: the active UI, API and Render setup describe one Forex product.

## Stage 2 — Instrument and quote contract (partially complete)

- [x] Maintain one canonical five-pair catalog with currencies, units, session
  labels and supported order types.
- [x] Reject unsupported symbols in market snapshots, chart history and the
  paper broker.
- [x] Preserve quote source, timestamp, bid and ask in the dashboard and AI
  cycle audit; mark paper quotes as non-executable.
- [x] Provide a validator that rejects non-IBKR, stale, crossed, or mismatched
  quotes if a future local execution adapter calls it.
- [ ] Resolve IBKR contract details, lot sizes, tick sizes, trading hours and
  adapter-side source provenance; no IBKR adapter exists yet.

Acceptance: paper use is clearly separated from executable IBKR quotes; no live
entry can be submitted in this release.

## Stage 3 — Risk and autonomous paper workflow (implemented)

- [x] Keep deterministic limits authoritative for notional, exposure, currency
  concentration, position count, daily loss, leverage, stops and position age.
- [x] Make the six-agent Forex AI cycle operator-started, single-flight and
  paper-only. Require all six responses, no Risk Critic veto, a supported pair,
  fresh entry quotes and passing deterministic broker checks.
- [x] Require enough remaining daily model-call and spend budget for a complete
  six-call cycle. Stop the worker when another full cycle cannot be funded.
- [x] Persist the quote snapshot, committee reports, gate result, paper action
  and resulting account with a retrievable cycle audit.
- [ ] Collect and review prospective paper records; no performance edge is
  established by implementation tests or backtests alone.

Acceptance: model failure, missing data, incomplete committee, budget shortage,
risk veto or paper-broker rejection results in no new entry and an inspectable
reason.

## Stage 4 — Local IBKR executor (not implemented)

- [x] Keep a standalone fail-closed heartbeat/arm lease primitive and quote
  validator as design foundations.
- [ ] Build a local service with authenticated, replay-resistant, expiring
  commands, durable kill switch and audit.
- [ ] Connect IB Gateway locally; reconcile account, orders, fills, positions,
  partial fills, commissions, disconnects and uncertain submissions.
- [ ] Re-run deterministic risk and quote checks immediately before every
  order; define safe cancel and risk-reducing behavior.

Acceptance: all live failure and recovery cases pass in an unfunded IBKR paper
account before any funded trial is considered.

## Stage 5 — Operator desk (paper state complete; live controls pending)

- [x] Show the Forex universe, quote quality, risk limits, agent reports and
  paper positions with an explicit paper-only label.
- [x] Add AI cycle, worker start/stop and model-budget state.
- [ ] Add connected local-executor health, live-arm lease and persistent kill
  control only after the local executor exists.
- [ ] Show reconciled broker orders, fills, exposure and execution outcomes.

Acceptance: no UI state suggests a live order exists without broker
confirmation.

## Stage 6 — Paper graduation (integration-ready; review pending)

- [x] Verify core paper controls, stale-data rejection, committee failure,
  risk veto, unsupported symbol and budget-exhaustion paths.
- [ ] Run and manually review a prospective paper record with the intended
  provider configuration. A minimum duration or trade count does not prove
  profitability.
- [ ] Only after review, configure user-owned live risk limits and explicitly
  arm a local executor for an unfunded broker paper environment.

## Stage 7 — Operations and deployment (code ready; account verification pending)

- [x] Provide authenticated Render configuration with persistent SQLite data
  and a health endpoint.
- [ ] Verify the intended Render workspace, current deploy, `/healthz`,
  authenticated dashboard, persistent database path and runtime logs.
- [ ] Before a live pilot, configure local secrets, backups, alerting, recovery,
  upgrade/rollback and incident procedures.

No step in this plan enables real trading automatically. No broker account,
credentials, funding, live adapter or profitable strategy is assumed.
