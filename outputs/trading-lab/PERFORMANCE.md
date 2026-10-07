# Performance and learning workflows

The upgrade adds six workflows without resetting existing capital, trades or model-cost history.

## Matched prospective comparison

Research now contains three separate fresh $100 paper accounts: observed AI decisions, fixed momentum and a holding baseline. Every account receives the same observation cycle, market universe, security gates, one-cycle delays, quote adapter and frozen configurable strategy settings. Only the AI account pays inference costs recorded since that run began. Positions with unavailable exits remain held and are marked conservatively; rejected orders and quote failures remain in the observations. SQLite retains run settings and complete frames.

This is an observational comparison: the AI account reuses approvals from the production team, whose own positions and history may differ. It does not establish that AI causes superior performance. Quote access requires a Jupiter key. These are paper accounts, not real executions or a forecast. The implementation and data-source integrations themselves are not immutable across future software upgrades.

## Learning review

A recorded losing production trade triggers a deterministic analyst/auditor proposal; the owner can also select **Review recorded losses**. No losses with attributable P&L means no invented proposal. The initial proposal tests a stricter 5% momentum threshold. Its hypothesis, underlying losses, caveats and settings are recorded.

**Start frozen prospective test** creates a new $100 challenger using only subsequent observations. The challenger changes the fixed-rule entry threshold; AI and baseline arms retain their matched control policy. One active challenger is allowed. **End test and archive results** preserves its last observations, including any open paper positions, and allows another experiment. Archiving does not close positions on-chain. No proposal automatically changes the production policy. Reviews currently use deterministic rules; they are not additional model agents. Existing model reviews receive the recorded proposals as context.

## Market evidence

The app records provider-reported five-minute volume, buy/sell transaction counts, transaction-size averages, volume/liquidity ratios, receipt times and liquidity changes. Entry gates require at least $1,000 five-minute volume and 20 transactions; volume above available liquidity or a liquidity decline of at least 10% within retained observations blocks entries. Rejected tokens retain a separate six-observation liquidity history. Gaps clear momentum history. These are conservative configurable hypotheses, not validated optimal thresholds.

Source timestamps, unique traders, wash-trading verification and actual holder transactions remain unknown when unavailable. Holder comparisons measure sampled owner concentration only. DEX evidence is obtained from [DEX Screener's documented API](https://docs.dexscreener.com/api/reference); totals do not prove genuine demand or absence of fraud.

## Cost and uncertainty hurdle

Quote-based paper buys and owner-approved wallet buys require the assumed 8% upside target to exceed twice the conservative round-trip cost plus a 2% uncertainty allowance. The reverse quote uses minimum received tokens. Network costs are included: paper settings provide a scenario, while wallet preparation includes its simulation/fee estimate. The target is an assumption, not a profit forecast. Wallet fees and SOL/USDC valuation can still change.

## Execution audit and recovery

Unresolved duplicate intents for the same wallet, mint and side block another preparation; the final reservation uses a SQLite write transaction. Wallet handoff remains once-only. Confirmation verifies the prepared message against the on-chain transaction and prevents reusing one signature for another intent.

The execution panel compares quoted minimum output with confirmed transaction balance deltas. Missing metadata yields unknown output. Failed transactions and minimum-output breaches are shown explicitly. SOL deltas may include account rent and do not establish whole-wallet P&L. This uses [Solana transaction metadata](https://solana.com/docs/rpc/http/gettransaction).

For an interrupted wallet handoff, **Search chain and reconcile** searches the latest 20 signatures for that wallet. It never resends a transaction. Unmatched intents retain their reservation and require investigation; this limited search cannot prove no transaction exists. Actual network execution still needs wallet approval, and no funded unattended signer was added.

## Owner briefing

Overview shows existing paper capital, change across recorded UTC-day valuations, attributable closed AI trades, best/worst recorded outcomes, AI allowance and setup/incident attention. Trade-level P&L excludes unallocated inference and infrastructure costs. Missing evidence is labeled, rather than generating a narrative about nonexistent trades.

## Verification

125 backend checks passed after integration. Real Chrome checks covered seven routes, four new panels, three matched books, existing charts, ten company employees, unique element IDs, no runtime exceptions and no horizontal overflow at a 390px mobile viewport. Desktop and mobile screenshots were inspected. The running app collected new matched observations from real public market data; original paper equity remained $99.30500000000063. No paid model calls, private-key imports or real trades were performed. No model or Jupiter credentials were configured during verification.
