# Shadow-Live Execution

The trading lab now separates **agent decisions** from **execution authority**.

## Flow

1. Market observations are collected from live DEX data.
2. Screening, market-quality and token-risk gates run deterministically.
3. Five-agent consensus produces an approve/exit decision.
4. Approved entries are mirrored into the shadow ledger.
5. Jupiter executable quotes are fetched and validated; no transaction is built, signed or sent.
6. The simulated fill is persisted with the quote evidence and decision hash.
7. Positions are reconciled against supplied balances/prices and discrepancies are recorded.
8. The existing paper strategy remains available for comparison.

## Hard shadow limits

- $10 maximum entry
- $25 daily entry budget
- 3 open positions
- $25 maximum shadow exposure
- 30-second quote freshness requirement

These limits are independent of the existing paper-trial accounting.

## Reconciliation

`ShadowLedger.reconcile()` checks:
- expected position versus observed token balance
- negative/invalid balances
- unexpected token balances
- current marks and unrealized P&L
- persistent reconciliation events

The HTTP surface exposes:
- `GET /api/shadow`
- `POST /api/shadow/reconcile`

The reconcile endpoint accepts `balances` and `prices` objects so a deployment-specific balance provider can be attached without giving the agents wallet authority.

## Security boundary

The shadow path contains no private key, signer, seed phrase, transaction submission, or wallet broadcast capability. Jupiter's current order/execute architecture requires a signed transaction for execution; this branch intentionally stops before that signing boundary.

## Validation

Run: `python -m unittest outputs/trading-lab/test_shadow_execution.py`

The tests cover reservation, daily budget, position limits and reconciliation discrepancy detection.

## Production deployment checklist

- use a dedicated low-balance trading wallet
- keep signing outside the agent process
- require deterministic transaction-policy validation before signing
- use an external secret/KMS/MPC boundary
- make signing requests idempotent
- reconcile every execution by signature and resulting balances
- alert on unexpected balances, failed executions and stale state
- keep the global kill switch outside the model decision path
- start in shadow mode and compare simulated versus executable outcomes for a meaningful sample

The system does not claim profitability or token safety.