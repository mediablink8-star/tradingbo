# Autonomous Live Execution

The repository now has a guarded autonomous execution boundary. The trading worker never receives a private key.

Flow:

agent decision -> live policy -> Jupiter preparation/simulation -> external signer -> signed-message verification -> Jupiter execute -> on-chain reconciliation.

Required environment:

- AUTONOMOUS_LIVE_ENABLE=1
- AUTONOMOUS_API_TOKEN=<strong-random-bearer-token>
- SIGNER_ENDPOINT
- SIGNER_API_TOKEN
- JUPITER_API_KEY

The external signer must be an independently operated HSM/MPC/KMS-backed service. It must authorize only the dedicated trading wallet, decode and independently verify the requested transaction before signing, recompute the policy from the decoded transaction, verify the requested message hash, and make signing idempotent by intent ID.

Pilot limits remain enforced by the existing live control:

- $10 maximum intent
- $25 daily intent budget
- explicit operator arm
- latched kill switch
- token-risk screening
- exact-input quote and slippage checks
- transaction simulation
- post-execution reconciliation

Signer contract:

POST SIGNER_ENDPOINT/v1/sign

Request JSON contains wallet, transaction, intent_id, message_hash and policy_hash.

Response JSON contains signedTransaction.

Before signing, the signer must independently verify the exact transaction semantics: required signer is the dedicated wallet; expiry is valid; top-level programs are allowlisted; the intended input mint/amount and output mint/minimum are satisfied; no unexpected wallet-owned asset transfer is present; and the recomputed policy hash equals the supplied policy hash. The signer must resolve versioned address-table accounts with a trusted Solana RPC when required. The trading worker's message hash is not a substitute for these independent checks.

The application verifies that the signed transaction contains exactly the prepared message before calling Jupiter execute.

No private key, seed phrase, or signing secret is stored in this repository or passed to the agent process.

This code establishes the integration boundary; real-money autonomous execution is still OFF until an external signer is provisioned, independently tested, funded with a dedicated low-balance wallet, and explicitly enabled.


## Position lifecycle

Autonomous buys create a persistent position record only after on-chain reconciliation
reports a verified positive token balance delta. Autonomous sells may close all or part
of that tracked position. The position ledger is separate from model state, so an agent
cannot invent a position or claim an exit without a reconciled transaction.

If any autonomous transaction is confirmed but reconciliation is not `verified`,
the executor immediately latches the existing live kill switch and refuses further
autonomous execution until an operator explicitly resets it.

Endpoints:

- `POST /api/autonomous/buy`
- `POST /api/autonomous/sell`

Both endpoints remain bound to the local browser origin and the autonomous/live gates.

## API authentication

The autonomous BUY/SELL HTTP endpoints require a bearer token in `Authorization: Bearer ...`. The token is independent of the external signer credential and must not be exposed to browser code. The server also remains bound to localhost by default. If the token is missing, autonomous HTTP execution fails closed.
