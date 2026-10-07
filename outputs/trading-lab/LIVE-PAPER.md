# Continuous $100 live-data paper trial

This is a prospective, continuously scheduled **hypothetical paper portfolio**, not a real wallet or an executable trading system. It starts with exactly $100 simulated cash. Resume/restart retains the existing balance and positions and never adds capital.

## Use
Open http://127.0.0.1:8765 and use **Continuous $100 live paper trial**. The trial is started in **Observe only — waiting for AI setup** because no AI provider was selected. It records live market observations; AI entries remain blocked. The independent baseline can make hypothetical entries under its fixed rules.

To enable AI decisions later, pause the trial, wait for status paused, select configured Ollama or OpenAI plus an available model, set the estimated cost per call and daily call cap, then resume. Server environment API keys are described in AGENT-SETUP.md; never paste secrets into chat. No paid inference was activated in this update. Scripted/demo inference is deliberately unavailable in the live trial.

## What runs automatically
A worker polls every approximately 60 seconds while the machine and local server run. PumpPortal discovers tokens; the trial takes a bounded sample of up to 20 from persisted discovery history and retains it, prioritizing positions in either portfolio. This is a coverage-limited monitoring sample, not a complete market scanner; tokens outside it are not evaluated. No token is dropped from the discovery database.

DEX Screener's documented token-pairs endpoint supplies real pool prices, USD liquidity, pair identifiers and creation time. Raw responses, empty responses and failures are logged. Changing pools clears momentum history; missing intervals clear history. The provider gives no source freshness timestamp here: fetch time proves receipt, not on-chain freshness. No RPC security/authority checks are performed.

The original hypothesis stays fixed: pool age at least 24 hours, liquidity at least $100,000, six consecutive fresh observations, positive five-interval momentum of at least 3%. New launches generally fail the age requirement, and many disappear or have no eligible pools. Abstaining is expected; these requirements are never loosened automatically.

Five model role calls receive current/past live evidence and each earlier report. All five must approve entry; optional AI exits can only accelerate the hard exits. No model can change limits, access wallets or call tools. Invalid output, provider failure, excessive model latency or insufficient inference budget produces no approval. Default maximum 20 attempted calls per UTC day (four complete rounds), configurable 5–100. Estimated cost is reserved before a round and debited/persisted before each attempted call. Actual provider bills may differ; provider-side spending controls remain necessary.

## Fixed risk and accounting
Illustrative defaults, not financial recommendations: $10 position allocations, at most three positions/$30 allocated exposure, 10% initial-capital loss shutdown at $90 conservative liquidation equity. Once latched, shutdown cannot be unlocked by restarting or changing the AI provider. Mandatory paper exits continue when usable snapshots return. Market gaps and costs can take losses beyond the threshold.

Paper fills occur on a later fresh observation, never on the signal's own snapshot. Pending orders expire after missed intervals. Fee 30 bps, adverse slippage 50 bps per side, approximate size impact, $0.02 network cost per fill, $0.005 operating cost per polling cycle, plus configured AI cost estimates. These are modeling assumptions, not measured executable prices or actual bills. Estimated liquidation costs are included in equity. Missing routes/snapshots value positions at zero and retain them for exit retries; actual route executability is **unverified**. No Jupiter quote or chain execution is used by this trial.

Baseline has its own identical $100 starting balance, screen, capital caps, delayed fills and execution/operating costs. It enters eligible screened tokens after enough observations without the momentum/AI approval requirement, holding up to 12 minutes. Strategy exits at -5%, +8%, 12 minutes, AI early exit or shutdown. Net P&L, conservative drawdown, cash, allocated exposure, open positions, and closed trades persist for each portfolio.

## Persistence and operation
SQLite tables live_state and live_log preserve state, settings, observation snapshots, signals, fills, rejections, valuations and agent reports. Other synthetic experiments remain separate. AI calls are checkpointed before submission to retain attempted cost/call counts after interruption. Resume clears stale momentum and expires overdue orders. Pause cancels pending entries and retains cash/positions; no fictitious forced liquidation is applied.

An enabled trial automatically resumes when the server starts. A paused trial stays paused. The server does not automatically launch when Windows boots, and cannot collect while the computer sleeps, loses network, closes the server or powers off. This is local continuous operation, not a deployed always-on service or a profitability guarantee. Server restart during a request may create observation gaps; logs retain them.

## Verification
33 automated tests cover the existing lab and the new live engine, including delayed fills, missing-data shutdown and position retention, expired orders, no-provider abstention, invalid model abstention, pause and durable restoration. Synthetic fixtures used by tests are not actual market results.

The actual public DEX API connection was verified using explicit JSON/application headers after the default Python header received HTTP 403. Browser automation was unavailable due to an environment sandbox-helper error; server/API flow and dashboard JavaScript syntax were checked instead. Provider inference remains unverified and unactivated because provider selection was deferred.

Official data documentation: https://docs.dexscreener.com/api/reference


Coverage refinement: after three polls without a usable price, unheld tokens enter a one-hour monitoring cooldown and free a slot for other discoveries. All their missing/empty/raw responses stay in the ledger; held tokens always remain monitored. This is bounded coverage, not a complete or survivor-filtered backtest universe.

Market observer update: prices are fetched through DEX Screener's documented tokens batch endpoint, up to 20 tokens per cycle. Held tokens take priority, followed by recorded PumpPortal migrations. Unpriced tokens retain their cooldown. Pool age, liquidity and momentum requirements remain unchanged. Readiness reports screening reasons, provider status and modeled costs. The modeled operating cost is $7.20 per 24 hours at a one-minute cadence, plus configured inference estimates; these are assumptions, not actual billing. No profitability claim is made.

Verification: 36 unit tests passed; dashboard JavaScript syntax passed. Updated local server resumed the persisted trial. No AI provider was selected or billed. Browser visual verification was unavailable in this session.
