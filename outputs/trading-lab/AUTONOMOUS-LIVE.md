# Autonomous Live Execution

The repository now has a guarded autonomous execution boundary. The trading worker never receives a private key.

Flow:

agent decision -> live policy -> Jupiter preparation/simulation -> external signer -> signed-message verification -> Jupiter execute -> on-chain reconciliation.

Required environment:

- AUTONOMOUS_LIVE_ENABLE=1
- SIGNER_ENDPOINT
- SIGNER_API_TOKEN
- JUPITER_API_KEY

The external signer must be an independently operated HSM/MPC/KMS-backed service. It must authorize only the dedicated trading wallet, verify the requested message hash against its own policy, and make signing idempotent by intent ID.

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

Request JSON contains wallet, transaction, intent_id and message_hash.

Response JSON contains signedTransaction.

The application verifies that the signed transaction contains exactly the prepared message before calling Jupiter execute.

No private key, seed phrase, or signing secret is stored in this repository or passed to the agent process.

This code establishes the integration boundary; real-money autonomous execution is still OFF until an external signer is provisioned, independently tested, funded with a dedicated low-balance wallet, and explicitly enabled.
