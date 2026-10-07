# Controlled live trading boundary

This branch adds a persistent operator/risk gate around the repository's existing **Phantom-approved Jupiter swap pilot**. It does **not** add unattended private-key signing or automatic broadcasting.

## Authority model

AI decision -> deterministic strategy/risk checks -> live intent gate -> exact Jupiter transaction preparation/simulation -> human wallet approval -> Solana -> confirmation/reconciliation

AI agents still have no wallet keys, transaction tools, RPC execution tools, or authority to change limits.

## Hard controls

The live gate is off by default and requires LIVE_TRADING_ENABLE=1 plus an explicit arm action.

Current conservative limits:
- $10 maximum per live intent
- $25 maximum live intent budget per UTC day
- persistent kill switch
- wallet approval remains mandatory
- existing Jupiter token-risk, route, simulation, signer/program, fee and minimum-output checks remain in force

/api/live-trading/arm, /api/live-trading/disarm, /api/live-trading/kill, and /api/live-trading/reset-kill operate the persistent gate.

The kill switch stops new handoffs. It cannot cancel a transaction already approved or broadcast by the wallet.

## Secrets

No wallet private key or seed is added to the application. The existing Phantom flow remains the signer boundary. Never put a seed/private key in Git, chat, browser storage, SQLite, or logs.

## Verification

Run: python -m unittest -v test_live_control.py

The repository's existing real-swap tests remain separate. A funded-wallet end-to-end test is intentionally not claimed here.

## Important limitation

This architecture controls execution authority and failure modes; it does not establish profitability, token safety, or guaranteed maximum loss. Real-money operation should begin with a dedicated, low-balance wallet and human review of every transaction.