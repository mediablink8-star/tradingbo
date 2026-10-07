# Controlled live trading

This branch adds a separate live execution boundary to the existing paper system.

## Authority model

AI agents still only produce approvals/exits. They do not receive wallet keys, transaction builders, RPC tools, or arbitrary execution access.

The live path is:
AI decision -> deterministic controller -> ControlledLiveExecution -> Jupiter preparation/simulation -> dedicated signer -> Solana RPC -> confirmation/reconciliation.

Only the strategy portfolio can be connected to the live executor. Baseline/rules portfolios remain paper-only.

## Arming

Live execution is off by default. It requires LIVE_TRADING_ENABLE=1, LIVE_TRADING_KEYPAIR containing a dedicated Solana JSON keypair, PyNaCl installed, a configured Jupiter API key, and an explicit arm action.

Never put a seed/private key in Git, chat, browser storage, SQLite, or logs. Use a dedicated low-balance hot wallet; do not use a primary wallet.

Hard controls: $10 maximum per buy, $25 daily live-buy budget, one live open position, and a persistent kill switch. A live buy is rejected unless the existing Jupiter preparation path passes token-risk, route, simulation, signer/program, fee, and minimum-output checks.

## Kill switch

/api/live-trading/kill permanently latches the database guard until an operator explicitly enables LIVE_TRADING_RESET_KILL=1 and resets it. Disarming stops new live entries but does not undo a transaction already broadcast.

## Limitations

This is a controlled execution architecture, not proof that the strategy is profitable or that token-risk checks are complete. It has not been exercised against a funded wallet in this environment. Start with a tiny dedicated wallet and compare every live transaction against the mirrored paper ledger.

PyNaCl provides Ed25519 signing from a 32-byte seed. Keep that seed secret.