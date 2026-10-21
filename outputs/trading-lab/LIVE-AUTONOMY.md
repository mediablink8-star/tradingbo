# Live execution status and release boundary

## Current product boundary

The AI agent company runs research and paper decisions. It does not submit its
proposals to a real broker or wallet. A separate Jupiter code path exists in
`jupiter_bot.py`; when explicitly enabled with `JUPITER_AUTORUN=1`, the launcher
loads the server wallet key, arms that path's in-memory risk gate and starts an
automatic worker. That worker only processes the static mint list in
`JUPITER_AUTOTRADE_TOKENS`, using `JUPITER_AUTOTRADE_SOL`. It does not consume
the AI company's proposals or the persistent `/api/live/*` gate.

The Render Blueprint sets `JUPITER_AUTORUN=0`. With that setting, the launcher
removes `SOLANA_PRIVATE_KEY` from the process environment and blocks its
server-side connect and swap endpoints. Keep this setting at `0` until the
separate live path has been reviewed and retired or deliberately redesigned.

There is also a distinct wallet-approved Jupiter pilot documented in
`REAL-SWAPS.md`. That flow asks the user's connected Phantom wallet to approve
transactions; it is not the server-side auto-trader and it is not autonomous
AI execution.

## What exists today

- An operator-started Forex paper-agent loop. It uses the existing fresh-quote checks, deterministic FX strategy and risk gate, records paper actions, and exposes start/stop controls in the dashboard. AI remains advisory; no broker orders are submitted.

- Deterministic paper portfolios, research and recorded agent decisions.
- AI roles that can advise or veto within the paper pipeline; deterministic
  risk controls remain authoritative there.
- A persistent live ARM/DISARM risk API with default limits of a $100 wallet
  cap, $12 per order, $25 daily realized-loss limit, two open positions, $30
  total exposure and a 24-hour ARM lifetime. This controller is separate from
  the `JUPITER_AUTORUN` worker.
- A browser-approved Jupiter swap pilot with transaction checks, simulation,
  explicit Phantom approval and persistent reservations; see `REAL-SWAPS.md`.
- A legacy-style server-side Jupiter worker that can submit real transactions
  if its environment flag and wallet key are both configured.

These pieces do not yet form one coherent, production-ready autonomous trading
system. The company and live-execution controls are not wired together.

## Work required before an autonomous live-trading release

1. Choose one live execution architecture and remove or disable the competing
   path. Require every order to pass through the same persistent risk and
   accounting controller.
2. Ensure the controller reserves exposure atomically before execution and
   reconciles orders, fills, balances, losses and uncertain submissions against
   the chain. Fail closed on stale or incomplete state.
3. Keep signing authority outside the AI process, with a narrowly scoped wallet
   and enforced program, asset, amount and fee policies.
4. Run the complete agent-to-paper pipeline prospectively and compare it with
   fixed rules using out-of-sample evidence after all costs. No profitable edge
   is established by the current backtests or UI.
5. Add operational recovery for pending or failed exits, idempotent requests,
   durable alerts, backups, and a documented incident procedure.
6. Verify the deployed configuration, secrets, persistent storage, access
   controls and wallet policy before any funded pilot.

No actual wallet, signer, cloud account, funding, profitable strategy or
24/7-operated trading company is claimed. The live worker stays disabled in
the checked-in Render configuration.
