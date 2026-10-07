# Unattended trading: outstanding integration

Recommended architecture: a dedicated trading wallet with only the intended 100-dollar allocation, controlled by a signing service that enforces policy outside the AI. Turnkey documents policies for Jupiter program IDs, token mints, spend amounts and fees: https://www.turnkey.com/blog/jupiter-solana-swap-policies . This is a candidate architecture, not an installed or verified Turnkey integration.

Required before unattended real trades can operate:
1. A selected signing-service account, trading wallet and scoped API credentials. No signer or trading-wallet funding has been configured. Signing policies must be installed and tested against permitted and forbidden transactions; app-side reservation caps do not substitute for signing policies.
2. Connect the configured AI team to real proposals through independent hard limits and a separate real portfolio controller. Current AI roles continue making paper decisions. They do not call the real swap endpoints or authorize signatures.
3. Track real positions, actual fees and account balances; add timed and loss-based exits, latching loss controls, failed-exit recovery, idempotent broadcast, pending transaction reconciliation, and automatic alerts. The wallet-approved pilot is not this unattended controller.
4. Persistent secret management suitable for the chosen host and signing provider; current dashboard keys are session only.
5. Hosting credentials for an always-on machine/service and operational deployment. The local recovery launcher does not supply hosting or keep a laptop awake.
6. Prospective paper evaluation and a controlled live execution test. No evidence of a profitable edge has been established.

No profits, funded account, signing-service integration, cloud deployment or 24/7 operation are claimed. The next dependent implementation requires the user's signing-service and hosting setup; those accounts and credentials cannot be inferred or invented.
